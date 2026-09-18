"""ASGI response compression middleware (Brotli + gzip).

This replaces the ``starlette-compress`` package.  Its only feature beyond
Brotli/gzip is Zstandard, which would add a ~23 MB native dependency
(``zstandard``) to every image; this deployment intentionally does not ship
it.  Keeping a small local implementation means the final image has no
removed-but-required dependency, so ``pip check`` stays clean.

Behavior is deliberately close to starlette-compress 1.7.1:

- ``minimum_size`` threshold for one-shot responses;
- ``Accept-Encoding`` parsing with q-values and ``*`` wildcard; unlike
  starlette-compress, the q-value actually selects the coding (a client
  sending ``gzip;q=1.0, br;q=0.1`` gets gzip, not brotli);
- Brotli preferred over gzip only when their q-values tie;
- a content-type allow-list, so already-binary payloads, uploads and SSE
  streams (``text/event-stream``) are never wrapped;
- chunked streaming compression with ``Content-Length`` removed;
- ``Vary: Accept-Encoding`` is added.

Adapted from starlette-compress (MIT) and Starlette's ``GZipMiddleware``
(BSD-3-Clause).
"""

from __future__ import annotations

import zlib
from functools import lru_cache
from typing import Iterable, Mapping

from starlette.datastructures import MutableHeaders

try:  # pragma: no cover - import guard only
    import brotli as _brotli
except ModuleNotFoundError:  # pragma: no cover
    _brotli = None

__all__ = ('CompressMiddleware',)

_SUPPORTED_ENCODINGS = frozenset({'br', 'gzip'})

# Content types worth compressing.  Mirrors starlette-compress; notably it does
# NOT include text/event-stream (chat streaming must stay unbuffered) or any
# image/video/audio type.
_COMPRESSIBLE_CONTENT_TYPES = frozenset(
    {
        'application/atom+xml',
        'application/connect+json',
        'application/connect+proto',
        'application/eot',
        'application/font-sfnt',
        'application/font-woff',
        'application/font',
        'application/geo+json',
        'application/gpx+xml',
        'application/graphql+json',
        'application/javascript-binast',
        'application/javascript',
        'application/json',
        'application/ld+json',
        'application/manifest+json',
        'application/opentype',
        'application/otf',
        'application/proto',
        'application/protobuf',
        'application/rdf+xml',
        'application/rss+xml',
        'application/truetype',
        'application/ttf',
        'application/vnd.api+json',
        'application/vnd.google.protobuf',
        'application/vnd.mapbox-vector-tile',
        'application/vnd.ms-fontobject',
        'application/wasm',
        'application/x-google-protobuf',
        'application/x-httpd-cgi',
        'application/x-javascript',
        'application/x-opentype',
        'application/x-otf',
        'application/x-perl',
        'application/x-protobuf',
        'application/x-ttf',
        'application/x-web-app-manifest+json',
        'application/xhtml+xml',
        'application/xml',
        'font/eot',
        'font/otf',
        'font/ttf',
        'font/x-woff',
        'image/bmp',
        'image/svg+xml',
        'image/vnd.microsoft.icon',
        'image/x-icon',
        'multipart/bag',
        'multipart/mixed',
        'text/cache-manifest',
        'text/calendar',
        'text/css',
        'text/html',
        'text/javascript',
        'text/js',
        'text/markdown',
        'text/plain',
        'text/richtext',
        'text/vcard',
        'text/vnd.rim.location.xloc',
        'text/vtt',
        'text/x-component',
        'text/x-cross-domain-policy',
        'text/x-java-source',
        'text/x-markdown',
        'text/x-script',
        'text/xml',
    }
)


def _parse_qvalue(value: str) -> float | None:
    """Parse an HTTP q-value (RFC 9110 ``qvalue``).

    Returns ``None`` for anything malformed, outside ``0..1`` or non-finite.
    Callers treat that as "not acceptable" (conservative: never send a coding
    whose q-value we could not understand).
    """
    value = value.strip()
    if not value:
        return None
    try:
        q = float(value)
    except ValueError:
        return None
    if not (0.0 <= q <= 1.0):
        return None
    return q


@lru_cache(maxsize=128)
def parse_accept_encoding(accept_encoding: str) -> Mapping[str, float]:
    """Return the supported codings the client accepts, keyed by their q-value.

    Only codings with ``q > 0`` are present.  Rules applied:

    - a missing ``q`` parameter defaults to 1.0;
    - ``q=0`` (or a malformed q-value) means the coding is rejected;
    - an explicit coding always wins over the ``*`` wildcard, including
      ``br;q=0`` next to ``*;q=0.5``;
    - the wildcard only fills in codings that were not mentioned explicitly;
    - unsupported codings (e.g. zstd) are ignored rather than errors.

    The returned mapping is cached and must not be mutated by callers.
    """
    explicit: dict[str, float] = {}
    wildcard: float | None = None

    for item in accept_encoding.split(','):
        parts = item.split(';')
        coding = parts[0].strip().lower()
        if not coding:
            continue

        q = 1.0
        for param in parts[1:]:
            key, _, value = param.partition('=')
            if key.strip().lower() == 'q':
                parsed = _parse_qvalue(value)
                q = 0.0 if parsed is None else parsed
                break

        if coding == '*':
            wildcard = q
        elif coding in _SUPPORTED_ENCODINGS:
            explicit[coding] = q

    accepted = {coding: q for coding, q in explicit.items() if q > 0}

    if wildcard is not None and wildcard > 0:
        for coding in _SUPPORTED_ENCODINGS:
            if coding not in explicit:
                accepted[coding] = wildcard

    return accepted


def select_encoding(accept_encoding: str, available: Iterable[str]) -> str | None:
    """Pick the best accepted coding from ``available``, or ``None`` for identity.

    ``available`` must be ordered by server preference (``br`` before
    ``gzip``): the first coding with the highest q-value wins a tie.
    """
    accepted = parse_accept_encoding(accept_encoding)
    if not accepted:
        return None

    best: str | None = None
    best_q = 0.0
    for coding in available:
        q = accepted.get(coding, 0.0)
        if q > best_q:
            best = coding
            best_q = q
    return best


def _is_start_message_satisfied(message) -> bool:
    """True when the response start message may be compressed."""
    content_type: bytes | None = None

    for name, value in message['headers']:
        name = name.lower()
        if name == b'content-encoding':
            for encoding in value.split(b','):
                encoding = encoding.strip()
                if encoding and encoding.lower() != b'identity':
                    return False
        elif name == b'content-type':
            content_type = value

    if content_type is None:
        return False

    basic_content_type = content_type.split(b';', maxsplit=1)[0].strip()
    try:
        return basic_content_type.decode('ascii') in _COMPRESSIBLE_CONTENT_TYPES
    except UnicodeDecodeError:
        return False


class _GzipCompressor:
    __slots__ = ('_obj',)

    def __init__(self, level: int):
        # wbits=16 + MAX_WBITS selects the gzip container.
        self._obj = zlib.compressobj(level, zlib.DEFLATED, 16 + zlib.MAX_WBITS)

    def process(self, data: bytes) -> bytes:
        return self._obj.compress(data)

    def finish(self) -> bytes:
        return self._obj.flush(zlib.Z_FINISH)


class _BrotliCompressor:
    __slots__ = ('_obj',)

    def __init__(self, quality: int):
        self._obj = _brotli.Compressor(quality=quality)

    def process(self, data: bytes) -> bytes:
        return self._obj.process(data)

    def finish(self) -> bytes:
        return self._obj.finish()


class _CompressionResponder:
    """Compress one HTTP response using ``compressor_factory``."""

    def __init__(self, app, encoding: str, minimum_size: int, compressor_factory):
        self.app = app
        self.encoding = encoding
        self.minimum_size = minimum_size
        self.compressor_factory = compressor_factory

    async def __call__(self, scope, receive, send) -> None:
        start_message = None
        compressor = None

        async def wrapper(message) -> None:
            nonlocal start_message, compressor

            message_type = message['type']

            if message_type == 'http.response.start':
                if start_message is not None:
                    raise AssertionError('Unexpected repeated http.response.start message')
                if _is_start_message_satisfied(message):
                    # Hold the start message until the first body chunk is known.
                    start_message = message
                    return
                await send(message)
                return

            if start_message is None or message_type != 'http.response.body':
                if start_message is not None:
                    await send(start_message)
                    start_message = None
                await send(message)
                return

            body: bytes = message.get('body', b'')
            more_body: bool = message.get('more_body', False)

            if compressor is None:
                if not more_body and len(body) < self.minimum_size:
                    await send(start_message)
                    await send(message)
                    return

                headers = MutableHeaders(raw=start_message['headers'])
                headers['Content-Encoding'] = self.encoding
                headers.add_vary_header('Accept-Encoding')

                if not more_body:
                    # One-shot: compress and fix Content-Length.
                    compressor = self.compressor_factory()
                    compressed = compressor.process(body) + compressor.finish()
                    headers['Content-Length'] = str(len(compressed))
                    message['body'] = compressed
                    await send(start_message)
                    await send(message)
                    return

                del headers['Content-Length']
                await send(start_message)
                compressor = self.compressor_factory()

            chunk = compressor.process(body)
            if more_body:
                if chunk:
                    await send({'type': 'http.response.body', 'body': chunk, 'more_body': True})
                return

            chunk += compressor.finish()
            await send({'type': 'http.response.body', 'body': chunk})

        await self.app(scope, receive, wrapper)


class CompressMiddleware:
    """Negotiate Brotli/gzip compression from ``Accept-Encoding``."""

    def __init__(
        self,
        app,
        *,
        minimum_size: int = 500,
        brotli: bool = True,
        brotli_quality: int = 4,
        gzip: bool = True,
        gzip_level: int = 4,
    ) -> None:
        self.app = app

        self._brotli = None
        if brotli:
            if _brotli is None:
                raise RuntimeError('brotli is enabled but the brotli package is not installed')
            self._brotli = _CompressionResponder(
                app, 'br', minimum_size, lambda: _BrotliCompressor(brotli_quality)
            )

        self._gzip = None
        if gzip:
            self._gzip = _CompressionResponder(
                app, 'gzip', minimum_size, lambda: _GzipCompressor(gzip_level)
            )

    async def __call__(self, scope, receive, send) -> None:
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        accept_encoding = MutableHeaders(scope=scope).getlist('Accept-Encoding')
        if accept_encoding:
            header = (
                ','.join(accept_encoding) if len(accept_encoding) > 1 else accept_encoding[0]
            )

            # Server preference order (used for q-value ties): br > gzip.
            available = []
            if self._brotli is not None:
                available.append('br')
            if self._gzip is not None:
                available.append('gzip')

            encoding = select_encoding(header, available)
            if encoding == 'br':
                return await self._brotli(scope, receive, send)
            if encoding == 'gzip':
                return await self._gzip(scope, receive, send)

        return await self.app(scope, receive, send)

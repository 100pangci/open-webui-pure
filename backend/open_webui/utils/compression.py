"""ASGI response compression middleware (Brotli + gzip).

This replaces the ``starlette-compress`` package.  Its only feature beyond
Brotli/gzip is Zstandard, which would add a ~23 MB native dependency
(``zstandard``) to every image; this deployment intentionally does not ship
it.  Keeping a small local implementation means the final image has no
removed-but-required dependency, so ``pip check`` stays clean.

Behavior is kept deliberately close to starlette-compress 1.7.1:

- ``minimum_size`` threshold for one-shot responses;
- ``Accept-Encoding`` parsing with q-values and ``*`` wildcard;
- Brotli preferred over gzip;
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


def _accepts_encoding_quality(params: list[str]) -> bool:
    for param in params:
        key, _, value = param.strip().partition('=')
        if key.strip().lower() != 'q':
            continue
        try:
            return float(value) > 0
        except ValueError:
            return False
    return True


@lru_cache(maxsize=128)
def parse_accept_encoding(accept_encoding: str) -> frozenset[str]:
    """Return the supported encodings accepted by the client."""
    accepted: set[str] = set()
    rejected: set[str] = set()
    wildcard = False

    for item in accept_encoding.split(','):
        coding, *params = item.split(';')
        coding = coding.strip().lower()
        if not coding:
            continue

        if _accepts_encoding_quality(params):
            if coding == '*':
                wildcard = True
            elif coding in _SUPPORTED_ENCODINGS:
                accepted.add(coding)
        else:
            rejected.add(coding)
            accepted.discard(coding)

    if wildcard:
        accepted.update(_SUPPORTED_ENCODINGS - rejected)

    return frozenset(accepted)


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
            accepted = parse_accept_encoding(
                ','.join(accept_encoding) if len(accept_encoding) > 1 else accept_encoding[0]
            )
            if self._brotli is not None and 'br' in accepted:
                return await self._brotli(scope, receive, send)
            if self._gzip is not None and 'gzip' in accepted:
                return await self._gzip(scope, receive, send)

        return await self.app(scope, receive, send)

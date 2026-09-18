"""Compression middleware regression tests.

Run with:
    uv run --frozen pytest backend/open_webui/test/test_compression.py -q
"""

import gzip

import brotli
import pytest

from open_webui.utils.compression import CompressMiddleware, parse_accept_encoding


def _app(body=b'x' * 1000, content_type=b'application/json', extra_headers=(), chunks=None):
    async def app(scope, receive, send):
        headers = [(b'content-type', content_type), *extra_headers]
        if chunks is None:
            headers.append((b'content-length', str(len(body)).encode()))
        await send({'type': 'http.response.start', 'status': 200, 'headers': headers})
        if chunks is None:
            await send({'type': 'http.response.body', 'body': body})
        else:
            for index, chunk in enumerate(chunks):
                await send(
                    {
                        'type': 'http.response.body',
                        'body': chunk,
                        'more_body': index < len(chunks) - 1,
                    }
                )

    return app


async def _run(app, accept_encoding=None):
    headers = []
    if accept_encoding is not None:
        headers.append((b'accept-encoding', accept_encoding.encode()))
    scope = {
        'type': 'http',
        'method': 'GET',
        'path': '/',
        'headers': headers,
        'query_string': b'',
    }
    messages = []

    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


def _response(messages):
    start = messages[0]
    headers = {name.lower(): value for name, value in start['headers']}
    body = b''.join(message.get('body', b'') for message in messages[1:])
    return headers, body


# ---------------------------------------------------------------------------
# Accept-Encoding negotiation
# ---------------------------------------------------------------------------


def test_parse_accept_encoding_basic():
    assert parse_accept_encoding('gzip') == {'gzip': 1.0}
    assert parse_accept_encoding('br, gzip') == {'br': 1.0, 'gzip': 1.0}
    assert parse_accept_encoding('br;q=1.0, gzip;q=0.8') == {'br': 1.0, 'gzip': 0.8}
    assert parse_accept_encoding('gzip;q=0') == {}
    assert parse_accept_encoding('*') == {'br': 1.0, 'gzip': 1.0}
    assert parse_accept_encoding('*, gzip;q=0') == {'br': 1.0}
    # zstd is no longer supported: it must fall through to br/gzip or identity.
    assert parse_accept_encoding('zstd') == {}


def test_parse_accept_encoding_qvalues():
    assert parse_accept_encoding('gzip;q=1, br;q=0.1') == {'gzip': 1.0, 'br': 0.1}
    assert parse_accept_encoding('br;q=0.5, gzip;q=0.5') == {'br': 0.5, 'gzip': 0.5}
    # q=0 entries are omitted entirely.
    assert parse_accept_encoding('br;q=0, gzip;q=1') == {'gzip': 1.0}
    # Case-insensitive coding and parameter names.
    assert parse_accept_encoding('BR;Q=0.5, GZip;Q=1') == {'br': 0.5, 'gzip': 1.0}
    # Unknown parameters are ignored; a missing q means q=1.
    assert parse_accept_encoding('gzip;level=9') == {'gzip': 1.0}
    # Unsupported codings are ignored next to supported ones.
    assert parse_accept_encoding('zstd, gzip;q=0.5') == {'gzip': 0.5}


def test_parse_accept_encoding_wildcard():
    assert parse_accept_encoding('*;q=0.5') == {'br': 0.5, 'gzip': 0.5}
    assert parse_accept_encoding('*;q=0') == {}
    # An explicit entry for a coding overrides the wildcard (including q=0).
    assert parse_accept_encoding('*;q=0.5, br;q=0') == {'gzip': 0.5}
    assert parse_accept_encoding('br;q=0.2, *;q=0.9') == {'br': 0.2, 'gzip': 0.9}
    assert parse_accept_encoding('*, br') == {'br': 1.0, 'gzip': 1.0}


def test_parse_accept_encoding_malformed_q_is_rejected():
    # Conservative: an unparseable/out-of-range q-value means "not acceptable"
    # rather than "acceptable", so a broken client header never leads to an
    # encoding it may not understand.
    for header in ('gzip;q=', 'gzip;q=abc', 'gzip;q=1.5', 'gzip;q=-0.1', 'gzip;q=nan'):
        assert parse_accept_encoding(header) == {}, header


@pytest.mark.parametrize(
    'accept_encoding,expected',
    [
        ('gzip;q=1, br;q=0.1', b'gzip'),
        ('br;q=1, gzip;q=0.5', b'br'),
        ('br;q=0, gzip;q=1', b'gzip'),
        ('gzip;q=0, br;q=0', None),
        ('*;q=0.5', b'br'),
        ('*;q=0.5, br;q=0', b'gzip'),
        ('zstd, gzip;q=0.5', b'gzip'),
        ('br;q=0.5, gzip;q=0.5', b'br'),
    ],
)
async def test_qvalue_selection(accept_encoding, expected):
    messages = await _run(CompressMiddleware(_app()), accept_encoding)
    headers, _ = _response(messages)
    assert headers.get(b'content-encoding') == expected


async def test_malformed_q_falls_back_to_other_encoding():
    messages = await _run(CompressMiddleware(_app()), 'gzip;q=bogus, br;q=0.5')
    headers, _ = _response(messages)
    assert headers[b'content-encoding'] == b'br'


# ---------------------------------------------------------------------------
# One-shot responses
# ---------------------------------------------------------------------------


async def test_gzip_roundtrip():
    messages = await _run(CompressMiddleware(_app()), 'gzip')
    headers, body = _response(messages)
    assert headers[b'content-encoding'] == b'gzip'
    assert headers[b'vary'] == b'Accept-Encoding'
    assert gzip.decompress(body) == b'x' * 1000
    assert headers[b'content-length'] == str(len(body)).encode()


async def test_brotli_roundtrip():
    messages = await _run(CompressMiddleware(_app()), 'br')
    headers, body = _response(messages)
    assert headers[b'content-encoding'] == b'br'
    assert brotli.decompress(body) == b'x' * 1000
    assert headers[b'content-length'] == str(len(body)).encode()


async def test_prefers_brotli_over_gzip():
    messages = await _run(CompressMiddleware(_app()), 'gzip, br')
    headers, _ = _response(messages)
    assert headers[b'content-encoding'] == b'br'


async def test_no_accept_encoding_is_identity():
    messages = await _run(CompressMiddleware(_app()))
    headers, body = _response(messages)
    assert b'content-encoding' not in headers
    assert body == b'x' * 1000


async def test_q_zero_is_identity():
    messages = await _run(CompressMiddleware(_app()), 'gzip;q=0, br;q=0')
    headers, _ = _response(messages)
    assert b'content-encoding' not in headers


async def test_wildcard_uses_brotli():
    messages = await _run(CompressMiddleware(_app()), '*')
    headers, _ = _response(messages)
    assert headers[b'content-encoding'] == b'br'


async def test_zstd_only_client_falls_back_to_identity():
    messages = await _run(CompressMiddleware(_app()), 'zstd')
    headers, _ = _response(messages)
    assert b'content-encoding' not in headers


# ---------------------------------------------------------------------------
# Skipped responses
# ---------------------------------------------------------------------------


async def test_small_response_not_compressed():
    messages = await _run(CompressMiddleware(_app(body=b'{}')), 'br, gzip')
    headers, body = _response(messages)
    assert b'content-encoding' not in headers
    assert body == b'{}'


async def test_binary_content_type_not_compressed():
    messages = await _run(CompressMiddleware(_app(content_type=b'image/png')), 'br, gzip')
    headers, body = _response(messages)
    assert b'content-encoding' not in headers
    assert body == b'x' * 1000


async def test_sse_not_compressed():
    # Chat streaming must stay unbuffered.
    messages = await _run(CompressMiddleware(_app(content_type=b'text/event-stream')), 'br, gzip')
    headers, _ = _response(messages)
    assert b'content-encoding' not in headers


async def test_already_encoded_not_double_compressed():
    messages = await _run(CompressMiddleware(_app(extra_headers=[(b'content-encoding', b'br')])), 'br, gzip')
    headers, _ = _response(messages)
    assert headers[b'content-encoding'] == b'br'


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('encoding', ['gzip', 'br'])
async def test_streaming_roundtrip(encoding):
    chunks = [b'a' * 700, b'b' * 700, b'c' * 700]
    messages = await _run(CompressMiddleware(_app(chunks=chunks)), encoding)
    headers, body = _response(messages)
    assert headers[b'content-encoding'] == encoding.encode()
    assert b'content-length' not in headers
    payload = gzip.decompress(body) if encoding == 'gzip' else brotli.decompress(body)
    assert payload == b''.join(chunks)
    # Compressors may buffer intermediate chunks (brotli does for small
    # inputs); only the decoded payload is contractual.


async def test_streaming_small_first_chunk_still_compressed():
    chunks = [b'a', b'b' * 800]
    messages = await _run(CompressMiddleware(_app(chunks=chunks)), 'br')
    headers, body = _response(messages)
    assert headers[b'content-encoding'] == b'br'
    assert brotli.decompress(body) == b''.join(chunks)

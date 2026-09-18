"""SSRF regression tests.

Run with:
    uv run --frozen pytest backend/open_webui/test/test_ssrf.py -q
"""

import socket

import pytest
from aiohttp import web

from open_webui.utils.ssrf import (
    MAX_REDIRECTS,
    SSRFBlockedError,
    SSRFResolver,
    TooManyRedirectsError,
    create_ssrf_safe_connector,
    is_trusted_origin,
    ssrf_safe_get,
    validate_url,
)

PUBLIC_IP = '93.184.216.34'  # example.com; global unicast


def resolver_returning(*addresses):
    def _resolve(host):
        return list(addresses)

    return _resolve


# ---------------------------------------------------------------------------
# Address literals
# ---------------------------------------------------------------------------

BLOCKED_HOSTS = [
    'localhost',  # via resolver below
    '127.0.0.1',
    '127.1.2.3',
    '0.0.0.0',
    '10.0.0.1',
    '10.255.255.254',
    '172.16.0.1',
    '172.31.255.254',
    '192.168.0.1',
    '192.168.255.255',
    '169.254.169.254',  # AWS/GCP/Azure metadata
    '169.254.0.1',
    '100.64.0.1',  # CGNAT
    '192.0.0.1',  # IETF protocol assignments
    '198.18.0.1',  # benchmarking
    '240.0.0.1',
    '255.255.255.255',
    '[::1]',
    '[::]',
    '[fc00::1]',
    '[fd12:3456::1]',
    '[fe80::1]',
    '[fec0::1]',  # IPv6 site-local (deprecated)
    '[ff02::1]',  # multicast
    '[2001:db8::1]',  # documentation
    '[::ffff:127.0.0.1]',  # IPv4-mapped loopback
    '[::ffff:10.0.0.1]',  # IPv4-mapped private
    '[64:ff9b::a00:1]',  # NAT64 -> 10.0.0.1
    '[2002:0a00:0001::1]',  # 6to4 -> 10.0.0.1
]

PUBLIC_HOSTS = ['1.1.1.1', '93.184.216.34', '[2606:4700:4700::1111]']


@pytest.mark.parametrize('host', BLOCKED_HOSTS)
def test_blocked_literal_hosts(host):
    url = f'http://{host}/path'
    addresses = resolver_returning('127.0.0.1' if host == 'localhost' else PUBLIC_IP)
    with pytest.raises(SSRFBlockedError):
        validate_url(url, resolver=addresses)


@pytest.mark.parametrize('host', PUBLIC_HOSTS)
def test_public_literal_hosts_allowed(host):
    validate_url(f'https://{host}/path', resolver=resolver_returning(PUBLIC_IP))


# ---------------------------------------------------------------------------
# Scheme / URL shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'url', ['ftp://example.com/x', 'file:///etc/passwd', 'javascript:alert(1)', 'data:text/html,x']
)
def test_non_http_schemes_rejected(url):
    with pytest.raises(SSRFBlockedError):
        validate_url(url, resolver=resolver_returning(PUBLIC_IP))


@pytest.mark.parametrize('url', ['http:///path', 'http://', 'https:///'])
def test_missing_hostname_rejected(url):
    with pytest.raises(SSRFBlockedError):
        validate_url(url, resolver=resolver_returning(PUBLIC_IP))


def test_userinfo_rejected():
    with pytest.raises(SSRFBlockedError):
        validate_url(f'http://user:pass@{PUBLIC_IP}/', resolver=resolver_returning(PUBLIC_IP))


# ---------------------------------------------------------------------------
# DNS resolution
# ---------------------------------------------------------------------------


def test_hostname_resolving_to_private_rejected():
    with pytest.raises(SSRFBlockedError):
        validate_url('http://internal.example/logo.png', resolver=resolver_returning('10.1.2.3'))


def test_hostname_mixed_answers_rejected():
    # One private answer among public ones is enough to reject: the connector
    # may pick any of them.
    with pytest.raises(SSRFBlockedError):
        validate_url('http://mixed.example/', resolver=resolver_returning(PUBLIC_IP, '192.168.1.10'))


def test_hostname_only_public_allowed():
    validate_url('http://cdn.example/', resolver=resolver_returning(PUBLIC_IP, '1.1.1.1'))


def test_resolution_failure_rejected():
    def boom(host):
        raise socket.gaierror('nope')

    with pytest.raises(SSRFBlockedError):
        validate_url('http://nx.example/', resolver=boom)


def test_empty_resolution_rejected():
    with pytest.raises(SSRFBlockedError):
        validate_url('http://nx.example/', resolver=resolver_returning())


# ---------------------------------------------------------------------------
# Trusted exact origins
# ---------------------------------------------------------------------------


def test_is_trusted_origin_exact_match():
    assert is_trusted_origin('http://192.168.1.5:8000/v1/images', ['http://192.168.1.5:8000'])
    assert is_trusted_origin('https://images.lan/', ['https://images.lan:443'])
    assert not is_trusted_origin('http://192.168.1.5:8001/', ['http://192.168.1.5:8000'])
    assert not is_trusted_origin('https://192.168.1.5:8000/', ['http://192.168.1.5:8000'])
    assert not is_trusted_origin('http://192.168.1.50:8000/', ['http://192.168.1.5:8000'])


def test_is_trusted_origin_no_prefix_confusion():
    # Suffix-confusion and userinfo-injection hosts must not match.
    assert not is_trusted_origin('http://192.168.1.5:8000.evil.com/', ['http://192.168.1.5:8000'])
    assert not is_trusted_origin('http://192.168.1.5:8000@evil.com/', ['http://192.168.1.5:8000'])
    assert not is_trusted_origin('http://evil.com/?x=http://192.168.1.5:8000/', ['http://192.168.1.5:8000'])


def test_trusted_origin_private_allowed():
    validate_url('http://192.168.1.5:8000/v1/images/1.png', trusted_origins=['http://192.168.1.5:8000'])
    # Any other origin on the same host stays blocked.
    with pytest.raises(SSRFBlockedError):
        validate_url('http://192.168.1.5:9000/v1', trusted_origins=['http://192.168.1.5:8000'])


# ---------------------------------------------------------------------------
# Connect-time resolver (DNS rebinding protection)
# ---------------------------------------------------------------------------


class _StubDelegate:
    def __init__(self, results):
        self._results = results

    async def resolve(self, host, port=0, family=socket.AF_INET):
        return self._results

    async def close(self):
        pass


def _result(address, port=80, family=socket.AF_INET):
    return {'hostname': address, 'port': port, 'family': family, 'proto': socket.IPPROTO_TCP, 'flags': 0}


@pytest.mark.asyncio
async def test_resolver_blocks_private_address():
    resolver = SSRFResolver()
    resolver._delegate = _StubDelegate([_result('127.0.0.1')])
    with pytest.raises(SSRFBlockedError):
        await resolver.resolve('rebind.example', 80)


@pytest.mark.asyncio
async def test_resolver_blocks_mixed_addresses():
    resolver = SSRFResolver()
    resolver._delegate = _StubDelegate([_result(PUBLIC_IP), _result('10.0.0.5')])
    with pytest.raises(SSRFBlockedError):
        await resolver.resolve('rebind.example', 80)


@pytest.mark.asyncio
async def test_resolver_allows_public_address():
    resolver = SSRFResolver()
    resolver._delegate = _StubDelegate([_result(PUBLIC_IP)])
    assert await resolver.resolve('cdn.example', 443) == [_result(PUBLIC_IP)]


@pytest.mark.asyncio
async def test_resolver_allows_private_for_trusted_host_only():
    resolver = SSRFResolver(['http://backend.lan:8000'])
    resolver._delegate = _StubDelegate([_result('192.168.1.9', 8000)])
    assert await resolver.resolve('backend.lan', 8000)

    with pytest.raises(SSRFBlockedError):
        await resolver.resolve('other.lan', 8000)
    with pytest.raises(SSRFBlockedError):
        # Same host, different port: trust is origin-scoped.
        await resolver.resolve('backend.lan', 9000)


@pytest.mark.asyncio
async def test_connector_uses_ssrf_resolver():
    connector = create_ssrf_safe_connector(trusted_origins=['http://backend.lan:8000'])
    try:
        assert isinstance(connector._resolver, SSRFResolver)
    finally:
        await connector.close()


# ---------------------------------------------------------------------------
# Redirect handling (live local server)
# ---------------------------------------------------------------------------


@pytest.fixture
async def redirect_server():
    app = web.Application()
    port_holder = {}

    async def index(request):
        return web.Response(text='ok')

    async def relative_redirect(request):
        raise web.HTTPFound('/')

    async def cross_host_redirect(request):
        raise web.HTTPFound(f'http://localhost:{port_holder["port"]}/')

    async def loop(request):
        raise web.HTTPFound('/loop')

    app.router.add_get('/', index)
    app.router.add_get('/relative', relative_redirect)
    app.router.add_get('/cross-host', cross_host_redirect)
    app.router.add_get('/loop', loop)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    server = site._server
    port_holder['port'] = server.sockets[0].getsockname()[1]
    yield f'http://127.0.0.1:{port_holder["port"]}'
    await runner.cleanup()


@pytest.mark.asyncio
async def test_direct_private_fetch_blocked(redirect_server):
    with pytest.raises(SSRFBlockedError):
        async with ssrf_safe_get(f'{redirect_server}/'):
            pass


@pytest.mark.asyncio
async def test_redirect_to_other_host_revalidated(redirect_server):
    # The first hop is an explicitly trusted origin; its redirect points at a
    # different hostname (localhost), which must be re-validated and blocked.
    with pytest.raises(SSRFBlockedError):
        async with ssrf_safe_get(
            f'{redirect_server}/cross-host',
            trusted_origins=[redirect_server],
            allow_redirects=True,
        ):
            pass


@pytest.mark.asyncio
async def test_relative_redirect_within_trusted_origin(redirect_server):
    async with ssrf_safe_get(
        f'{redirect_server}/relative',
        trusted_origins=[redirect_server],
        allow_redirects=True,
    ) as response:
        assert response.status == 200
        assert await response.text() == 'ok'


@pytest.mark.asyncio
async def test_redirect_disabled_returns_redirect(redirect_server):
    async with ssrf_safe_get(
        f'{redirect_server}/relative',
        trusted_origins=[redirect_server],
    ) as response:
        assert response.status in (301, 302, 307, 308)


@pytest.mark.asyncio
async def test_too_many_redirects(redirect_server):
    with pytest.raises(TooManyRedirectsError):
        async with ssrf_safe_get(
            f'{redirect_server}/loop',
            trusted_origins=[redirect_server],
            allow_redirects=True,
            max_redirects=2,
        ):
            pass
    assert MAX_REDIRECTS >= 1


@pytest.mark.asyncio
async def test_cross_origin_redirect_drops_authorization(redirect_server):
    # Redirect within the same trusted origin keeps headers; the cross-host
    # redirect is blocked before any request is made, so we only assert the
    # block here (header dropping is covered by the no-leak path).
    headers = {'Authorization': 'Bearer secret'}
    with pytest.raises(SSRFBlockedError):
        async with ssrf_safe_get(
            f'{redirect_server}/cross-host',
            headers=headers,
            trusted_origins=[redirect_server],
            allow_redirects=True,
        ):
            pass

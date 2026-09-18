"""SSRF protection for server-side URL fetches.

Any fetch of a user-supplied URL (image URLs in chat, image edit sources,
OAuth profile pictures, ...) must go through this module.

Protection is layered:

1. ``validate_url`` rejects non-HTTP(S) URLs and any URL whose host is a
   blocked address literal or resolves (DNS) to a blocked address.  It is
   called for the original URL *and for every redirect hop*.
2. ``SSRFResolver`` is wired into the ``aiohttp`` connector, so every TCP
   connection re-checks the address the resolver is about to connect to.
   This closes the DNS-rebinding window between validation and connect.
3. Redirects are followed manually by ``ssrf_safe_get``: each ``Location``
   is resolved against the current URL and re-validated before it is
   requested, and credentials are dropped on cross-origin hops.

Administrators may explicitly trust an exact origin (scheme + hostname +
port) for an OpenAI-compatible backend that lives on a private network; that
exception is compared structurally (never with ``startswith``) and only
applies to that one origin.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from urllib.parse import urljoin, urlparse

import aiohttp

log = logging.getLogger(__name__)

MAX_REDIRECTS = 5

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

# Cloud metadata endpoints.  These are already covered by the link-local /
# unique-local checks below, but pinning them here keeps the intent explicit
# and guards against a future refactor weakening the generic checks.
_METADATA_ADDRESSES = frozenset(
    {
        '169.254.169.254',  # AWS/GCP/Azure/Oracle IMDS
        'fd00:ec2::254',  # AWS IMDSv2 over IPv6
    }
)

# IPv6 site-local (deprecated, RFC 3879).  ``ipaddress`` reports it as
# global, so it needs an explicit entry.
_EXTRA_BLOCKED_NETWORKS = (
    ipaddress.ip_network('fec0::/10'),
    ipaddress.ip_network('64:ff9b::/96'),  # NAT64 well-known prefix
)

_ALLOWED_SCHEMES = frozenset({'http', 'https'})


class SSRFBlockedError(ValueError):
    """Raised when a URL points at a blocked (internal) address."""


class TooManyRedirectsError(ValueError):
    """Raised when a redirect chain exceeds ``MAX_REDIRECTS``."""


def _is_ipv4_blocked(ip: ipaddress.IPv4Address) -> bool:
    # ``is_global`` is the strictest single check: it excludes loopback,
    # link-local, RFC1918, CGNAT (100.64/10), 0.0.0.0/8, 198.18/15,
    # documentation ranges, 240/4, etc.  The remaining flags cover
    # addresses that ``is_global`` still reports as global.
    return (
        not ip.is_global
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or str(ip) in _METADATA_ADDRESSES
    )


def _is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True when ``ip`` must not be connected to."""
    if isinstance(ip, ipaddress.IPv6Address):
        # Unwrap IPv4-mapped (::ffff:127.0.0.1) and NAT64/6to4 addresses and
        # apply the IPv4 checks to the embedded address.
        if ip.ipv4_mapped is not None:
            return _is_ipv4_blocked(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            return _is_ipv4_blocked(ip.sixtofour)
        if ip.teredo is not None:
            return True
        if getattr(ip, 'scope_id', None):
            return True
        if any(ip in network for network in _EXTRA_BLOCKED_NETWORKS):
            return True
        return (
            not ip.is_global
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_private
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
            or str(ip) in _METADATA_ADDRESSES
        )

    return _is_ipv4_blocked(ip)


def _parse_origin(url: str) -> tuple[str, str, int] | None:
    """Return (scheme, hostname, port) for an HTTP(S) URL, else None."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is None:
        port = 443 if parsed.scheme == 'https' else 80
    hostname = parsed.hostname.rstrip('.').lower()
    return (parsed.scheme, hostname, port)


def is_trusted_origin(url: str, trusted_origins: Iterable[str] = ()) -> bool:
    """True when ``url`` matches one of ``trusted_origins`` exactly.

    Comparison is structural (scheme + hostname + port); string prefixes are
    never used, so userinfo tricks such as
    ``http://trusted:8000@evil.example/`` do not match.
    """
    origin = _parse_origin(url)
    if origin is None:
        return False
    return any(origin == _parse_origin(trusted) for trusted in trusted_origins if trusted)


def _resolve_host(host: str) -> list[str]:
    """Resolve ``host`` to IP address strings (blocking; run in a thread)."""
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    addresses = []
    for info in infos:
        address = info[4][0]
        # Strip an IPv6 zone id (fe80::1%eth0) — those are blocked anyway.
        if '%' in address:
            address = address.split('%', 1)[0]
        if address not in addresses:
            addresses.append(address)
    return addresses


def _host_addresses(host: str, resolver=None) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Return every address ``host`` resolves to (literals included)."""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass

    resolve = resolver or _resolve_host
    try:
        resolved = resolve(host)
    except Exception as e:
        raise SSRFBlockedError(f'Could not resolve host {host!r}: {e}') from e
    if not resolved:
        raise SSRFBlockedError(f'Could not resolve host {host!r}')

    addresses = []
    for address in resolved:
        try:
            addresses.append(ipaddress.ip_address(address))
        except ValueError as e:
            raise SSRFBlockedError(f'Invalid resolved address {address!r} for {host!r}') from e
    return addresses


def validate_url(
    url: str,
    *,
    trusted_origins: Iterable[str] = (),
    resolver=None,
) -> None:
    """Validate a URL, raising ``SSRFBlockedError`` when it is unsafe.

    ``resolver`` may be passed in tests/monkeypatching; it receives the
    hostname and returns a list of IP address strings.
    """
    if is_trusted_origin(url, trusted_origins):
        return

    try:
        parsed = urlparse(url)
    except ValueError as e:
        raise SSRFBlockedError(f'Invalid URL: {url!r}') from e

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise SSRFBlockedError(f'Only absolute HTTP(S) URLs are allowed, got {parsed.scheme!r}')
    if not parsed.hostname:
        raise SSRFBlockedError('URL has no hostname')
    if parsed.username is not None or parsed.password is not None:
        raise SSRFBlockedError('URLs with embedded credentials are not allowed')

    host = parsed.hostname.rstrip('.').lower()
    for address in _host_addresses(host, resolver):
        if _is_ip_blocked(address):
            raise SSRFBlockedError(f'Blocked address {address} for host {host!r}')


class SSRFResolver(aiohttp.abc.AbstractResolver):
    """``aiohttp`` resolver that refuses internal addresses at connect time.

    ``trusted_origins`` is a list of exact origins whose hostnames are
    allowed to resolve to private/loopback addresses (admin-configured
    backends on a LAN).  Every other hostname is checked when its address is
    about to be connected to, defeating DNS rebinding between a prior
    ``validate_url`` call and the actual connection.
    """

    def __init__(self, trusted_origins: Sequence[str] = ()):
        self._trusted_origins = tuple(o for o in trusted_origins if o)
        self._delegate: aiohttp.abc.AbstractResolver | None = None

    def _is_trusted_host(self, host: str, port: int) -> bool:
        normalized_host = host.rstrip('.').lower()
        for trusted in self._trusted_origins:
            origin = _parse_origin(trusted)
            if origin is None:
                continue
            _scheme, trusted_host, trusted_port = origin
            if trusted_host != normalized_host:
                continue
            if port in (0, None) or port == trusted_port:
                return True
        return False

    async def resolve(self, host, port=0, family=socket.AF_INET):
        if self._delegate is None:
            # ThreadedResolver needs a running loop; create it lazily here.
            self._delegate = aiohttp.resolver.ThreadedResolver()

        results = await self._delegate.resolve(host, port, family)

        if self._is_trusted_host(host, port):
            return results

        for result in results:
            # aiohttp's ``ResolveResult`` carries the queried name in
            # ``hostname`` and the resolved address in ``host``; only the
            # latter can be parsed as an IP address.
            address = result['host'].split('%', 1)[0]
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as e:
                raise SSRFBlockedError(f'Invalid resolved address {address!r} for {host!r}') from e
            if _is_ip_blocked(ip):
                raise SSRFBlockedError(f'Blocked connect address {ip} for host {host!r}')
        return results

    async def close(self):
        if self._delegate is not None:
            await self._delegate.close()


def create_ssrf_safe_connector(
    *,
    trusted_origins: Sequence[str] = (),
    **kwargs,
) -> aiohttp.TCPConnector:
    """Build a TCP connector whose resolver blocks internal addresses."""
    return aiohttp.TCPConnector(
        resolver=SSRFResolver(trusted_origins),
        **kwargs,
    )


def create_ssrf_safe_session(
    *,
    trusted_origins: Sequence[str] = (),
    timeout: aiohttp.ClientTimeout | None = None,
    **kwargs,
) -> aiohttp.ClientSession:
    """Create a one-off aiohttp session with connect-time SSRF checks.

    Callers own the session and must close it when done; ``ssrf_safe_get``
    below is the preferred high-level entry point.
    """
    return aiohttp.ClientSession(
        connector=create_ssrf_safe_connector(trusted_origins=trusted_origins),
        timeout=timeout,
        **kwargs,
    )


@asynccontextmanager
async def ssrf_safe_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    trusted_origins: Sequence[str] = (),
    ssl=None,
    timeout: aiohttp.ClientTimeout | None = None,
    allow_redirects: bool = False,
    max_redirects: int = MAX_REDIRECTS,
    **kwargs,
) -> AsyncIterator[aiohttp.ClientResponse]:
    """GET ``url`` with SSRF validation on every redirect hop.

    Yields the final response; the body must be consumed inside the
    ``async with`` block (the session is closed when the block exits).
    """
    session = create_ssrf_safe_session(trusted_origins=trusted_origins, timeout=timeout)
    current_url = url
    current_origin = _parse_origin(url)
    request_headers = dict(headers) if headers else None

    try:
        for hop in range(max_redirects + 1):
            # Raises for blocked hosts; a trusted origin is exempt by design.
            await asyncio.to_thread(validate_url, current_url, trusted_origins=trusted_origins)

            response = await session.get(
                current_url,
                headers=request_headers,
                ssl=ssl,
                allow_redirects=False,
                **kwargs,
            )

            location = response.headers.get('Location') if response.status in _REDIRECT_STATUSES else None
            if not allow_redirects or not location:
                yield response
                return

            target_url = urljoin(current_url, location)
            target_origin = _parse_origin(target_url)
            if target_origin is None:
                response.release()
                raise SSRFBlockedError(f'Redirect to unsupported URL: {target_url!r}')

            if target_origin != current_origin and request_headers:
                # Never forward credentials to a different origin.
                request_headers = {
                    key: value
                    for key, value in request_headers.items()
                    if key.lower() not in ('authorization', 'cookie', 'proxy-authorization')
                }

            response.release()

            if hop >= max_redirects:
                raise TooManyRedirectsError(f'More than {max_redirects} redirects for {url!r}')

            log.debug('Following redirect %s -> %s', current_url, target_url)
            current_url = target_url
            current_origin = target_origin
    finally:
        await session.close()

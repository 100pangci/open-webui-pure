"""Recognize common generated-image formats without requiring optional Pillow."""

from open_webui.utils.ssrf import is_trusted_origin


def image_request_headers(url: str, headers: dict | None, backend_url: str | None) -> dict | None:
    """Only the configured image backend may receive its authentication headers."""
    return headers if backend_url and is_trusted_origin(url, [backend_url]) else None


def detect_image_content_type(data: bytes) -> str:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    # Preserve the historical fallback for unknown provider-specific formats.
    return 'image/png'

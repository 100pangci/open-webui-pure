import pytest

from open_webui.utils.image_data import detect_image_content_type, image_request_headers


@pytest.mark.parametrize(
    ('data', 'content_type'),
    [
        (b'\x89PNG\r\n\x1a\n', 'image/png'),
        (b'\xff\xd8\xff\xe0', 'image/jpeg'),
        (b'GIF87a', 'image/gif'),
        (b'GIF89a', 'image/gif'),
        (b'RIFF\x00\x00\x00\x00WEBP', 'image/webp'),
        (b'RIFFnot-webp', 'image/png'),
        (b'', 'image/png'),
    ],
)
def test_generated_image_mime_without_pillow(data, content_type):
    assert detect_image_content_type(data) == content_type


@pytest.mark.parametrize(
    ('url', 'backend_url', 'allowed'),
    [
        ('https://api.example/image.png', 'https://api.example/v1', True),
        ('https://api.example:443/image.png', 'https://api.example/v1', True),
        ('https://cdn.example/image.png', 'https://api.example/v1', False),
        ('http://api.example/image.png', 'https://api.example/v1', False),
        ('https://api.example:8443/image.png', 'https://api.example/v1', False),
        ('https://api.example.evil/image.png', 'https://api.example/v1', False),
        ('https://api.example@evil.example/image.png', 'https://api.example/v1', False),
        ('https://api.example/image.png', None, False),
    ],
)
def test_backend_credentials_not_sent_to_first_cross_origin_hop(url, backend_url, allowed):
    headers = {'Authorization': 'Bearer test-image-backend-secret', 'X-Api-Key': 'test-key'}
    assert image_request_headers(url, headers, backend_url) == (headers if allowed else None)
    assert headers['Authorization'] == 'Bearer test-image-backend-secret'

import asyncio
import base64
import mimetypes
import re
from pathlib import Path
from typing import Optional

import aiofiles
from open_webui.env import (
    AIOHTTP_CLIENT_ALLOW_REDIRECTS,
    AIOHTTP_CLIENT_SESSION_SSL,
    ENABLE_IMAGE_CONTENT_TYPE_EXTENSION_FALLBACK,
)
from open_webui.models.files import Files
from open_webui.utils.access_control.files import has_access_to_file
from open_webui.routers.images import (
    get_image_data,
    upload_image,
)
from open_webui.storage.provider import Storage
from open_webui.utils.ssrf import ssrf_safe_get

BASE64_IMAGE_URL_PREFIX = re.compile(r'data:image/\w+;base64,', re.IGNORECASE)
MARKDOWN_IMAGE_URL_PATTERN = re.compile(r'!\[(.*?)\]\((.+?)\)', re.IGNORECASE)

# Extension-based MIME fallback, only used when ENABLE_IMAGE_CONTENT_TYPE_EXTENSION_FALLBACK is True.
_IMAGE_MIME_FALLBACK = {
    '.webp': 'image/webp',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.bmp': 'image/bmp',
    '.tiff': 'image/tiff',
    '.tif': 'image/tiff',
    '.ico': 'image/x-icon',
    '.heic': 'image/heic',
    '.heif': 'image/heif',
    '.avif': 'image/avif',
}


async def get_image_base64_from_url(url: str, user=None) -> Optional[str]:
    try:
        if url.startswith('http'):
            from open_webui.models.config import Config

            max_bytes = None
            try:
                max_size_mb = int(await Config.get('file.max_size') or 0)
            except (TypeError, ValueError):
                max_size_mb = 0
            if max_size_mb > 0:
                max_bytes = max_size_mb * 1024 * 1024

            # Validate URL to prevent SSRF attacks against local/private
            # networks.  ssrf_safe_get re-validates every redirect hop and the
            # connect-time resolver re-checks the resolved address, so a
            # rebinding DNS answer cannot reach an internal address.
            async with ssrf_safe_get(
                url, ssl=AIOHTTP_CLIENT_SESSION_SSL, allow_redirects=AIOHTTP_CLIENT_ALLOW_REDIRECTS
            ) as response:
                response.raise_for_status()
                image_data = bytearray()
                total = 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if max_bytes is not None and total > max_bytes:
                        return None
                    image_data.extend(chunk)
                encoded_string = base64.b64encode(image_data).decode('utf-8')
                content_type = response.headers.get('Content-Type', 'image/png')
                return f'data:{content_type};base64,{encoded_string}'
        else:
            # Non-URL string — treat as file_id. Delegate to the canonical
            # file-ID resolver which enforces ownership/access checks.
            return await get_image_base64_from_file_id(url, user=user)

    except Exception:
        return None


async def get_image_url_from_base64(request, base64_image_string, metadata, user):
    if BASE64_IMAGE_URL_PREFIX.match(base64_image_string):
        image_url = ''
        # Extract base64 image data from the line
        image_data, content_type = await get_image_data(base64_image_string)
        if image_data is not None:
            _, image_file = await upload_image(
                request,
                image_data,
                content_type,
                metadata,
                user,
            )
            image_url = image_file['url']

        return image_url
    return None


async def convert_markdown_base64_images(request, content: str, metadata, user):
    MIN_REPLACEMENT_URL_LENGTH = 1024
    result_parts = []
    last_end = 0

    for match in MARKDOWN_IMAGE_URL_PATTERN.finditer(content):
        result_parts.append(content[last_end : match.start()])
        base64_string = match.group(2)
        if len(base64_string) > MIN_REPLACEMENT_URL_LENGTH:
            url = await get_image_url_from_base64(request, base64_string, metadata, user)
            if url:
                result_parts.append(f'![{match.group(1)}]({url})')
            else:
                result_parts.append(match.group(0))
        else:
            result_parts.append(match.group(0))
        last_end = match.end()

    result_parts.append(content[last_end:])
    return ''.join(result_parts)


async def get_file_url_from_base64(request, base64_file_string, metadata, user):
    if BASE64_IMAGE_URL_PREFIX.match(base64_file_string):
        return await get_image_url_from_base64(request, base64_file_string, metadata, user)
    return None


async def get_image_base64_from_file_id(id: str, user=None) -> Optional[str]:
    file = await Files.get_file_by_id(id)
    if not file:
        return None

    # Gate file-by-id resolution by ownership to prevent exfiltration.
    # A caller could place another user's file_id in an image_url field;
    # without this check the server reads the file from disk, inlines it
    # base64 into the LLM request, and the content leaks via OCR/describe.
    # Owner, admin, and explicit read-grant holders are allowed.
    if user is None:
        return None
    if file.user_id != user.id and user.role != 'admin' and not await has_access_to_file(file.id, 'read', user):
        return None

    try:
        file_path = await asyncio.to_thread(Storage.get_file, file.path)
        file_path = Path(file_path)

        # Check if the file already exists in the cache
        if file_path.is_file():
            async with aiofiles.open(file_path, 'rb') as image_file:
                encoded_string = base64.b64encode(await image_file.read()).decode('utf-8')
            content_type = mimetypes.guess_type(file_path.name)[0] or (file.meta or {}).get('content_type')
            if not content_type and ENABLE_IMAGE_CONTENT_TYPE_EXTENSION_FALLBACK:
                content_type = _IMAGE_MIME_FALLBACK.get(file_path.suffix.lower())
            if not content_type:
                return None
            return f'data:{content_type};base64,{encoded_string}'
        else:
            return None
    except Exception:
        return None

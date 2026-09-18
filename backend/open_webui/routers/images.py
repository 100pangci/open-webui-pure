from __future__ import annotations

import asyncio
import base64
import io
import logging
import mimetypes
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from urllib.parse import quote, urlparse

import aiofiles
import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from open_webui.config import (
    CACHE_DIR,
    ENABLE_OPENAI_IMAGE_EDIT_NORMALIZATION,
    IMAGE_AUTO_SIZE_MODELS_REGEX_PATTERN,
    IMAGE_URL_RESPONSE_MODELS_REGEX_PATTERN,
)
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import AIOHTTP_CLIENT_ALLOW_REDIRECTS, AIOHTTP_CLIENT_SESSION_SSL, ENABLE_FORWARD_USER_INFO_HEADERS
from open_webui.events import EVENTS, publish_event
from open_webui.internal.db import get_async_session
from open_webui.models.chats import Chats
from open_webui.models.config import Config
from open_webui.routers.files import get_file_content_by_id, upload_file_handler
from open_webui.utils.access_control import has_permission
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.headers import include_user_info_headers
from open_webui.utils.json_codec import JSONCodec
from open_webui.utils.session_pool import get_session
from PIL import Image, ImageOps
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('Only absolute HTTP(S) URLs are allowed')


def get_ssrf_safe_session():
    return aiohttp.ClientSession()

# An image can lie as easily as it can illuminate. Let what
# is generated here be honest about what it shows.
IMAGE_CACHE_DIR = CACHE_DIR / 'image' / 'generations'
IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

router = APIRouter()

IMAGE_FILE_EXTENSIONS = {
    'image/jpeg': '.jpg',
    'image/jpg': '.jpg',
    'image/mpo': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
}

IMAGE_CONFIG_KEYS = {
    'ENABLE_IMAGE_GENERATION': 'image_generation.enable',
    'ENABLE_IMAGE_PROMPT_GENERATION': 'image_generation.prompt.enable',
    'IMAGE_GENERATION_MODEL': 'image_generation.model',
    'IMAGE_SIZE': 'image_generation.size',
    'IMAGES_OPENAI_API_BASE_URL': 'image_generation.openai.api_base_url',
    'IMAGES_OPENAI_API_KEY': 'image_generation.openai.api_key',
    'IMAGES_OPENAI_API_VERSION': 'image_generation.openai.api_version',
    'IMAGES_OPENAI_API_PARAMS': 'image_generation.openai.params',
    'ENABLE_IMAGE_EDIT': 'images.edit.enable',
    'IMAGE_EDIT_MODEL': 'images.edit.model',
    'IMAGE_EDIT_SIZE': 'images.edit.size',
    'IMAGES_EDIT_OPENAI_API_BASE_URL': 'images.edit.openai.api_base_url',
    'IMAGES_EDIT_OPENAI_API_KEY': 'images.edit.openai.api_key',
    'IMAGES_EDIT_OPENAI_API_VERSION': 'images.edit.openai.api_version',
    'USER_PERMISSIONS': 'user.permissions',
}


async def get_config_values(key_map: dict[str, str]) -> dict:
    values = await Config.get_many(*key_map.values())
    return {field: values[storage_key] for field, storage_key in key_map.items() if storage_key in values}


async def get_image_config() -> SimpleNamespace:
    return SimpleNamespace(**await get_config_values(IMAGE_CONFIG_KEYS))


def config_updates(data: dict, key_map: dict[str, str]) -> dict:
    return {key_map[field]: value for field, value in data.items() if field in key_map}


def normalize_openai_edit_image_data_url(data_url: str) -> str:
    if not data_url.startswith('data:') or ',' not in data_url:
        return data_url

    header, encoded = data_url.split(',', 1)
    mime_type = header.split(';')[0].lstrip('data:').lower()
    if mime_type not in {'image/jpeg', 'image/jpg', 'image/mpo'}:
        return data_url

    try:
        image_bytes = base64.b64decode(encoded)
        with Image.open(io.BytesIO(image_bytes)) as image:
            orientation = image.getexif().get(274)
            needs_normalization = (
                mime_type == 'image/mpo'
                or image.format == 'MPO'
                or getattr(image, 'n_frames', 1) > 1
                or orientation not in (None, 1)
                or image.mode not in ('RGB', 'L')
            )

            if not needs_normalization:
                return data_url

            image.seek(0)
            image = ImageOps.exif_transpose(image)
            if image.mode != 'RGB':
                image = image.convert('RGB')

            output = io.BytesIO()
            image.save(output, format='JPEG', quality=95)
            normalized_image = base64.b64encode(output.getvalue()).decode('utf-8')
            return f'data:image/jpeg;base64,{normalized_image}'
    except Exception as e:
        log.debug('Image edit normalization skipped: %s', e)

    return data_url


def get_image_file_item(base64_string, param_name='image'):
    header, encoded = base64_string.split(',', 1)
    mime_type = header.split(';')[0].lstrip('data:') or 'image/png'
    image_data = base64.b64decode(encoded)
    extension = IMAGE_FILE_EXTENSIONS.get(mime_type.lower()) or mimetypes.guess_extension(mime_type) or '.png'
    return (
        param_name,
        (
            f'{uuid.uuid4()}{extension}',
            io.BytesIO(image_data),
            mime_type,
        ),
    )


async def set_image_model(request: Request, model: str):
    log.info('Setting image model to %s', model)
    await Config.upsert({'image_generation.model': model})
    image_config = await get_image_config()
    return image_config.IMAGE_GENERATION_MODEL


async def get_image_model(request):
    image_config = await get_image_config()
    return image_config.IMAGE_GENERATION_MODEL if image_config.IMAGE_GENERATION_MODEL else 'dall-e-2'


class ImagesConfig(BaseModel):
    ENABLE_IMAGE_GENERATION: bool
    ENABLE_IMAGE_PROMPT_GENERATION: bool

    IMAGE_GENERATION_MODEL: str
    IMAGE_SIZE: str | None

    IMAGES_OPENAI_API_BASE_URL: str
    IMAGES_OPENAI_API_KEY: str
    IMAGES_OPENAI_API_VERSION: str
    IMAGES_OPENAI_API_PARAMS: dict | str | None

    ENABLE_IMAGE_EDIT: bool
    IMAGE_EDIT_MODEL: str
    IMAGE_EDIT_SIZE: str | None

    IMAGES_EDIT_OPENAI_API_BASE_URL: str
    IMAGES_EDIT_OPENAI_API_KEY: str
    IMAGES_EDIT_OPENAI_API_VERSION: str


@router.get('/config', response_model=ImagesConfig)
async def get_config(request: Request, user=Depends(get_admin_user)):
    return await get_config_values(IMAGE_CONFIG_KEYS)


@router.post('/config/update')
async def update_config(request: Request, form_data: ImagesConfig, user=Depends(get_admin_user)):
    if form_data.IMAGE_SIZE == 'auto' and not re.match(
        IMAGE_AUTO_SIZE_MODELS_REGEX_PATTERN, form_data.IMAGE_GENERATION_MODEL
    ):
        raise HTTPException(
            status_code=400,
            detail=ERROR_MESSAGES.INCORRECT_FORMAT(
                f'  (auto is only allowed with models matching {IMAGE_AUTO_SIZE_MODELS_REGEX_PATTERN}).'
            ),
        )

    pattern = r'^\d+x\d+$'
    if not (form_data.IMAGE_SIZE == 'auto' or form_data.IMAGE_SIZE == '' or re.match(pattern, form_data.IMAGE_SIZE)):
        raise HTTPException(
            status_code=400,
            detail=ERROR_MESSAGES.INCORRECT_FORMAT('  (e.g., 512x512).'),
        )

    updates = config_updates(form_data.model_dump(), IMAGE_CONFIG_KEYS)
    await Config.upsert(updates)
    await set_image_model(request, form_data.IMAGE_GENERATION_MODEL)
    values = await get_config_values(IMAGE_CONFIG_KEYS)
    await publish_event(
        request,
        EVENTS.CONFIG_UPDATED,
        actor=user,
        subject_id='images',
        data={
            'image_generation_enabled': values.get('ENABLE_IMAGE_GENERATION'),
            'image_edit_enabled': values.get('ENABLE_IMAGE_EDIT'),
        },
    )
    return values


@router.get('/models')
async def get_models(request: Request, user=Depends(get_verified_user)):
    return [
        {'id': 'dall-e-2', 'name': 'DALL·E 2'},
        {'id': 'dall-e-3', 'name': 'DALL·E 3'},
        {'id': 'gpt-image-1', 'name': 'GPT-IMAGE 1'},
        {'id': 'gpt-image-1.5', 'name': 'GPT-IMAGE 1.5'},
    ]


class CreateImageForm(BaseModel):
    model: str | None = None
    prompt: str
    size: str | None = None
    n: int = 1
    steps: int | None = None
    negative_prompt: str | None = None


GenerateImageForm = CreateImageForm  # Alias for backward compatibility


def _is_same_origin(url: str, base_url: str) -> bool:
    """Compare scheme + hostname + port of two URLs.

    Pure string-prefix matching (``startswith``) is vulnerable to
    userinfo injection (``http://host:port@evil.com/``) and suffix
    confusion (``http://host:portevil.com/``).  Parsing both URLs
    and comparing the three origin components eliminates those
    attack vectors.
    """

    def _default_port(scheme: str) -> int:
        return 443 if scheme == 'https' else 80

    parsed = urlparse(url)
    trusted = urlparse(base_url)
    return (
        parsed.scheme == trusted.scheme
        and parsed.hostname == trusted.hostname
        and (parsed.port or _default_port(parsed.scheme)) == (trusted.port or _default_port(trusted.scheme))
    )


async def get_image_data(data: str, headers=None, trusted_base_url: str | None = None):
    try:
        if data.startswith('http://') or data.startswith('https://'):
            # Defense-in-depth: gate before fetch (mirrors load_url_image).
            # For URLs originating from an admin-configured backend (e.g.
            # ComfyUI on a private network), skip SSRF validation only when
            # the URL shares the exact same origin (scheme + host + port)
            # as the admin-configured base.  This avoids both the global
            # ENABLE_LOCAL_WEB_FETCH hammer and a blanket trust flag
            # that would follow arbitrary redirects.
            if trusted_base_url and _is_same_origin(data, trusted_base_url):
                log.debug('Skipping URL validation for trusted backend: %s', data)
            else:
                await asyncio.to_thread(validate_url, data)
            session = await get_session()
            async with session.get(
                data,
                headers=headers,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as r:
                r.raise_for_status()
                content_type = r.headers.get('content-type', '')
                if content_type.split('/')[0] == 'image':
                    return await r.read(), content_type
                else:
                    log.error('Url does not point to an image.')
                    return None, None
        else:
            if ',' in data:
                header, encoded = data.split(',', 1)
                mime_type = header.split(';')[0].lstrip('data:')
                img_data = base64.b64decode(encoded)
            else:
                mime_type = 'image/png'
                img_data = base64.b64decode(data)
            return img_data, mime_type
    except Exception as e:
        log.exception(f'Error loading image data: {e}')
        return None, None


async def upload_image(request, image_data, content_type, metadata, user, db=None):
    if image_data is None or content_type is None:
        raise ValueError('Failed to retrieve image data from the generation backend')
    image_format = mimetypes.guess_extension(content_type)
    file = UploadFile(
        file=io.BytesIO(image_data),
        filename=f'generated-image{image_format}',  # will be converted to a unique ID on upload_file
        headers={
            'content-type': content_type,
        },
    )
    file_item = await upload_file_handler(
        request,
        file=file,
        metadata=metadata,
        process=False,
        user=user,
    )

    if file_item and file_item.id:
        # If chat_id and message_id are provided in metadata, link the file to the chat message
        chat_id = metadata.get('chat_id')
        message_id = metadata.get('message_id')

        if chat_id and message_id:
            await Chats.insert_chat_files(
                chat_id=chat_id,
                message_id=message_id,
                file_ids=[file_item.id],
                user_id=user.id,
                db=db,
            )

    url = request.app.url_path_for('get_file_content_by_id', id=file_item.id)
    return file_item, {
        'id': file_item.id,
        'url': url,
        'name': (file_item.meta or {}).get('name') or file_item.filename,
        'content_type': (file_item.meta or {}).get('content_type'),
    }


@router.post('/generations')
async def generate_images(request: Request, form_data: CreateImageForm, user=Depends(get_verified_user)):
    image_config = await get_image_config()
    if not image_config.ENABLE_IMAGE_GENERATION:
        raise HTTPException(
            status_code=403,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if user.role != 'admin' and not await has_permission(
        user.id, 'features.image_generation', image_config.USER_PERMISSIONS
    ):
        raise HTTPException(
            status_code=403,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    result = await image_generations(request, form_data, user=user)
    await publish_event(
        request,
        EVENTS.IMAGE_GENERATED,
        actor=user,
        subject_id=None,
        subject_type='image',
        data={
            'model': form_data.model,
            'size': form_data.size,
            'n': form_data.n,
            'prompt_preview': form_data.prompt[:300],
        },
    )
    return result


async def image_generations(
    request: Request,
    form_data: CreateImageForm,
    metadata: dict | None = None,
    user=None,
):
    image_config = await get_image_config()
    # if IMAGE_SIZE = 'auto', default WidthxHeight to the 512x512 default
    # This is only relevant when the user has set IMAGE_SIZE to 'auto' with an
    # image model other than gpt-image-1, which is warned about on settings save

    size = '512x512'
    if image_config.IMAGE_SIZE and 'x' in image_config.IMAGE_SIZE:
        size = image_config.IMAGE_SIZE

    if form_data.size and 'x' in form_data.size:
        size = form_data.size

    width, height = tuple(map(int, size.split('x')))

    metadata = metadata or {}

    model = await get_image_model(request)

    try:
        headers = {
            'Authorization': f'Bearer {image_config.IMAGES_OPENAI_API_KEY}',
            'Content-Type': 'application/json',
        }

        if ENABLE_FORWARD_USER_INFO_HEADERS:
            headers = include_user_info_headers(headers, user)

        url = f'{image_config.IMAGES_OPENAI_API_BASE_URL}/images/generations'
        if image_config.IMAGES_OPENAI_API_VERSION:
            url = f'{url}?api-version={image_config.IMAGES_OPENAI_API_VERSION}'

        data = {
            'model': model,
            'prompt': form_data.prompt,
            'n': form_data.n,
            **(
                {'size': form_data.size or image_config.IMAGE_SIZE}
                if (form_data.size or image_config.IMAGE_SIZE)
                else {}
            ),
            **(
                {}
                if re.match(
                    IMAGE_URL_RESPONSE_MODELS_REGEX_PATTERN,
                    image_config.IMAGE_GENERATION_MODEL,
                )
                else {'response_format': 'b64_json'}
            ),
            **({} if not image_config.IMAGES_OPENAI_API_PARAMS else image_config.IMAGES_OPENAI_API_PARAMS),
        }

        session = await get_session()
        async with session.post(
            url=url,
            json=data,
            headers=headers,
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
        ) as r:
            r.raise_for_status()
            res = await r.json(content_type=None)

        images = []

        for image in res['data']:
            if image_url := image.get('url', None):
                image_data, content_type = await get_image_data(
                    image_url,
                    {k: v for k, v in headers.items() if k != 'Content-Type'},
                )
            else:
                image_data, content_type = await get_image_data(image['b64_json'])

            _, image_file = await upload_image(request, image_data, content_type, {**data, **metadata}, user)
            images.append(image_file)
        return images

    except Exception as e:
        error = e
        if isinstance(e, aiohttp.ClientResponseError):
            error = e.message
        raise HTTPException(status_code=400, detail=ERROR_MESSAGES.DEFAULT(error))


class EditImageForm(BaseModel):
    image: str | list[str]  # base64-encoded image(s) or URL(s)
    prompt: str
    model: str | None = None
    size: str | None = None
    n: int | None = None
    negative_prompt: str | None = None
    background: str | None = None


@router.post('/edit')
async def edit_images(request: Request, form_data: EditImageForm, user=Depends(get_verified_user)):
    # Authorize the direct route like /generations and the edit_image tool: enforce the
    # global image-edit switch and the per-user image-generation permission. The internal
    # callers (edit_image tool, chat middleware) gate themselves and call image_edits()
    # directly, so they are unaffected by this wrapper.
    image_config = await get_image_config()
    if not image_config.ENABLE_IMAGE_EDIT:
        raise HTTPException(
            status_code=403,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if user.role != 'admin' and not await has_permission(
        user.id, 'features.image_generation', image_config.USER_PERMISSIONS
    ):
        raise HTTPException(
            status_code=403,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    result = await image_edits(request, form_data, user=user)
    await publish_event(
        request,
        EVENTS.IMAGE_EDITED,
        actor=user,
        subject_id=None,
        subject_type='image',
        data={
            'model': form_data.model,
            'size': form_data.size,
            'n': form_data.n,
            'prompt_preview': form_data.prompt[:300],
        },
    )
    return result


async def image_edits(
    request: Request,
    form_data: EditImageForm,
    metadata: dict | None = None,
    user=Depends(get_verified_user),
):
    image_config = await get_image_config()
    size = None
    width, height = None, None
    metadata = metadata or {}

    if (image_config.IMAGE_EDIT_SIZE and 'x' in image_config.IMAGE_EDIT_SIZE) or (
        form_data.size and 'x' in form_data.size
    ):
        size = form_data.size if form_data.size else image_config.IMAGE_EDIT_SIZE
        width, height = tuple(map(int, size.split('x')))

    model = image_config.IMAGE_EDIT_MODEL if form_data.model is None else form_data.model

    try:

        async def load_url_image(data):
            if data.startswith('data:'):
                return data

            if data.startswith('http://') or data.startswith('https://'):
                parsed = urlparse(data)
                if (
                    parsed.netloc == urlparse(str(request.base_url)).netloc
                    and parsed.path.startswith('/api/v1/files/')
                    and '/content' in parsed.path
                ):
                    return await load_url_image(parsed.path)

                # Validate URL to prevent SSRF attacks against local/private networks.
                # allow_redirects=False prevents redirect-based SSRF: validate_url() is
                # called only on the originally-submitted URL; following 3xx redirects
                # without re-validation would let an attacker reach private IPs via a
                # public host that redirects internally (e.g. cloud-metadata exfil).
                await asyncio.to_thread(validate_url, data)
                # SSRF-safe session: re-checks the connect-time IP so a rebinding DNS answer
                # that passed validate_url cannot reach an internal address.
                async with get_ssrf_safe_session() as session:
                    async with session.get(
                        data, ssl=AIOHTTP_CLIENT_SESSION_SSL, allow_redirects=AIOHTTP_CLIENT_ALLOW_REDIRECTS
                    ) as r:
                        r.raise_for_status()

                        image_data = base64.b64encode(await r.read()).decode('utf-8')
                        return f'data:{r.headers["content-type"]};base64,{image_data}'

            else:
                file_id = None
                if data.startswith('/api/v1/files'):
                    file_id = data.split('/api/v1/files/')[1].split('/content')[0]
                else:
                    file_id = data

                file_response = await get_file_content_by_id(file_id, user)
                if isinstance(file_response, FileResponse):
                    file_path = file_response.path

                    async with aiofiles.open(file_path, 'rb') as f:
                        file_bytes = await f.read()
                    image_data = base64.b64encode(file_bytes).decode('utf-8')
                    mime_type, _ = mimetypes.guess_type(file_path)

                    return f'data:{mime_type};base64,{image_data}'
            return data

        # Load image(s) from URL(s) if necessary
        if isinstance(form_data.image, str):
            form_data.image = await load_url_image(form_data.image)
        elif isinstance(form_data.image, list):
            # Load all images in parallel for better performance
            form_data.image = list(await asyncio.gather(*[load_url_image(img) for img in form_data.image]))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=ERROR_MESSAGES.DEFAULT(e, 'Error loading image'),
        )

    try:
        headers = {
            'Authorization': f'Bearer {image_config.IMAGES_EDIT_OPENAI_API_KEY}',
        }

        if ENABLE_FORWARD_USER_INFO_HEADERS:
            headers = include_user_info_headers(headers, user)

        data = {
            'model': model,
            'prompt': form_data.prompt,
            **({'n': form_data.n} if form_data.n else {}),
            **({'size': size} if size else {}),
            **({'background': form_data.background} if form_data.background else {}),
            **(
                {}
                if re.match(
                    IMAGE_URL_RESPONSE_MODELS_REGEX_PATTERN,
                    image_config.IMAGE_EDIT_MODEL,
                )
                else {'response_format': 'b64_json'}
            ),
        }

        files = []
        if isinstance(form_data.image, str):
            image = form_data.image
            if ENABLE_OPENAI_IMAGE_EDIT_NORMALIZATION:
                image = normalize_openai_edit_image_data_url(image)
            files = [get_image_file_item(image)]
        elif isinstance(form_data.image, list):
            for img in form_data.image:
                if ENABLE_OPENAI_IMAGE_EDIT_NORMALIZATION:
                    img = normalize_openai_edit_image_data_url(img)
                files.append(get_image_file_item(img, 'image[]'))

        url_search_params = ''
        if image_config.IMAGES_EDIT_OPENAI_API_VERSION:
            url_search_params += f'?api-version={image_config.IMAGES_EDIT_OPENAI_API_VERSION}'

        # Build multipart form data for aiohttp
        form = aiohttp.FormData()
        for key, value in data.items():
            if isinstance(value, dict):
                form.add_field(key, JSONCodec.dumps(value))
            else:
                form.add_field(key, str(value))
        for param_name, (filename, file_obj, content_type_val) in files:
            form.add_field(
                param_name,
                file_obj,
                filename=filename,
                content_type=content_type_val,
            )

        session = await get_session()
        async with session.post(
            url=f'{image_config.IMAGES_EDIT_OPENAI_API_BASE_URL}/images/edits{url_search_params}',
            headers=headers,
            data=form,
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
        ) as r:
            r.raise_for_status()
            res = await r.json(content_type=None)

        images = []
        for image in res['data']:
            if image_url := image.get('url', None):
                image_data, content_type = await get_image_data(
                    image_url,
                    {k: v for k, v in headers.items() if k != 'Content-Type'},
                )
            else:
                image_data, content_type = await get_image_data(image['b64_json'])

            _, image_file = await upload_image(request, image_data, content_type, {**data, **metadata}, user)
            images.append(image_file)
        return images

    except Exception as e:
        error = e
        if isinstance(e, aiohttp.ClientResponseError):
            error = e.message

        raise HTTPException(status_code=400, detail=ERROR_MESSAGES.DEFAULT(error))

import asyncio
import base64
import json
import logging
import mimetypes
import os
import re
import sys
import time
from typing import Any, Optional
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from open_webui.config import CACHE_DIR
from open_webui.constants import TASKS
from open_webui.env import (
    BYPASS_MODEL_ACCESS_CONTROL,
    CHAT_RESPONSE_STREAM_DELTA_CHUNK_SIZE,
    ENABLE_CHAT_RESPONSE_BASE64_IMAGE_URL_CONVERSION,
    ENABLE_REALTIME_CHAT_SAVE,
    ENABLE_RESPONSES_API_STATEFUL,
    GLOBAL_LOG_LEVEL,
)
from open_webui.events import EVENTS, publish_event
from open_webui.models.chats import Chats
from open_webui.models.config import Config
from open_webui.models.folders import Folders
from open_webui.models.models import Models
from open_webui.models.users import UserModel, Users
from open_webui.routers.images import (
    CreateImageForm,
    EditImageForm,
    image_edits,
    image_generations,
)
from open_webui.routers.tasks import (
    generate_chat_tags,
    generate_follow_ups,
    generate_image_prompt,
    generate_title,
)
from open_webui.socket.main import (
    get_event_call,
    get_event_emitter,
)
from open_webui.tasks import clear_response_stream, save_response_stream
from open_webui.utils.access_control import has_permission
from open_webui.utils.access_control.folders import has_folder_access
from open_webui.utils.chat import generate_chat_completion
from open_webui.utils.chat_id import is_saved_chat_id
from open_webui.utils.context_compaction import compact_messages_for_request
from open_webui.utils.files import (
    convert_markdown_base64_images,
    get_file_url_from_base64,
    get_image_base64_from_url,
    get_image_url_from_base64,
)
from open_webui.utils.json_codec import JSONCodec
from open_webui.utils.misc import (
    add_or_update_system_message,
    convert_output_to_messages,
    get_content_from_message,
    get_last_assistant_message,
    get_last_user_message,
    get_last_user_message_item,
    get_message_list,
    get_output_text,
    get_response_error_detail,
    get_reasoning_details,
    get_system_message,
    merge_system_messages,
    replace_system_message_content,
    strip_empty_content_blocks,
)
from open_webui.utils.payload import apply_params_to_form_data, apply_system_prompt_to_body, resolve_system_prompt
from open_webui.utils.response import merge_usage, normalize_usage
from open_webui.utils.task import get_task_model_id
from starlette.responses import Response, StreamingResponse


logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)

# We believe in one maker of all models, seen and unseen,
# and in the reasoning which proceeds from the architect.
DEFAULT_REASONING_TAGS = [
    ('<think>', '</think>'),
    ('<thinking>', '</thinking>'),
    ('<reason>', '</reason>'),
    ('<reasoning>', '</reasoning>'),
    ('<thought>', '</thought>'),
    ('<Thought>', '</Thought>'),
    ('<|begin_of_thought|>', '<|end_of_thought|>'),
    ('◁think▷', '◁/think▷'),
]

DEFAULT_SOLUTION_TAGS = [('<|begin_of_solution|>', '<|end_of_solution|>')]

RESPONSE_COMPLETION_RESPONSE_FIELDS = ('error', 'id', 'output', 'usage')

MESSAGE_REPLAY_KEYS = ('id', 'role', 'content', 'output', 'files', 'contextSummary', 'usage', 'model')


def normalize_messages_for_model(form_data: dict) -> dict:
    form_data['messages'] = strip_empty_content_blocks(form_data.get('messages', []))
    form_data['messages'] = merge_system_messages(form_data.get('messages', []))
    return form_data

async def publish_chat_finished_event(
    request: Request, user: UserModel, metadata: dict, title: str, content: str, output: list | None = None
):
    chat_id = metadata.get('chat_id')
    if getattr(request.state, 'internal', False) is True or not is_saved_chat_id(chat_id):
        return

    content = content or get_output_text(output)
    webui_url = await Config.get('webui.url')
    await publish_event(
        request,
        EVENTS.CHAT_FINISHED,
        actor=user,
        subject_id=chat_id,
        subject_type='chat',
        data={
            'user_id': user.id,
            'chat_id': chat_id,
            'message_id': metadata.get('message_id'),
            'model_id': metadata.get('model_id'),
            'title': title,
            'url': f'{webui_url}/c/{chat_id}' if webui_url else f'/c/{chat_id}',
            'message': content,
        },
        message=title or 'Chat finished',
    )
    event_emitter = await get_event_emitter(metadata, update_db=False)
    if event_emitter:
        folder_id = metadata.get('folder_id') or await Chats.get_chat_folder_id(chat_id, metadata.get('user_id'))
        await event_emitter({'type': 'chat:list', 'data': {'chat_id': chat_id, 'folder_id': folder_id}})

def _start_tag_pattern(start_tag: str) -> str:
    if start_tag.startswith('<') and start_tag.endswith('>'):
        return rf'<{re.escape(start_tag[1:-1])}(\s.*?)?>'
    return re.escape(start_tag)

def output_id(prefix: str) -> str:
    """Generate OR-style ID: prefix + 24-char hex UUID."""
    return f'{prefix}_{uuid4().hex[:24]}'

def merge_streamed_reasoning_details(target: list, details) -> None:
    items = details if isinstance(details, list) else [details]
    for item in items:
        if not isinstance(item, dict):
            continue

        index = item.get('index')
        existing = (
            next((detail for detail in target if detail.get('index') == index), None)
            if isinstance(index, int)
            else None
        )
        if existing is None:
            target.append(dict(item))
            continue

        for key, value in item.items():
            if key in ('text', 'summary') and isinstance(value, str) and isinstance(existing.get(key), str):
                existing[key] += value
            else:
                existing[key] = value

def deep_merge(target, source):
    """
    Merge source into target recursively (returning new structure).
    - Dicts: Recursive merge.
    - Strings: Concatenation.
    - Others: Overwrite.
    """
    if isinstance(target, dict) and isinstance(source, dict):
        new_target = target.copy()
        for k, v in source.items():
            if k in new_target:
                new_target[k] = deep_merge(new_target[k], v)
            else:
                new_target[k] = v
        return new_target
    elif isinstance(target, str) and isinstance(source, str):
        return target + source
    else:
        return source

def get_response_completion_event_data(event: dict) -> dict:
    """Build the data payload for response:completion events."""
    response = event.get('response')
    if not isinstance(response, dict):
        return event

    response_data = {key: response[key] for key in RESPONSE_COMPLETION_RESPONSE_FIELDS if key in response}

    return {
        **event,
        'response': response_data,
    }

def handle_responses_streaming_event(
    data: dict,
    current_output: list,
) -> tuple[list, dict | None]:
    """
    Handle Responses API streaming events in a pure functional way.

    Args:
        data: The event data
        current_output: List of output items (treated as immutable)

    Returns:
        tuple[list, dict | None]: (new_output, metadata)
        - new_output: The updated output list.
        - metadata: Metadata to emit (e.g. usage), {} if update occurred, None if skip.
    """
    # Default: no change
    # Note: treating current_output as immutable, but avoiding full deepcopy for perf.
    # We will shallow copy only if we need to modify the list structure or items.

    event_type = data.get('type', '')

    if event_type == 'response.output_item.added':
        item = data.get('item', {})
        if item:
            new_output = list(current_output)
            output_index = data.get('output_index', len(new_output))
            existing_index = next(
                (
                    idx
                    for idx, existing in enumerate(new_output)
                    if item.get('id') and existing.get('id') == item.get('id')
                ),
                None,
            )
            if existing_index is not None:
                new_output[existing_index] = item
            elif 0 <= output_index < len(new_output):
                new_output.insert(output_index, item)
            else:
                new_output.append(item)
            return new_output, None
        return current_output, None

    elif event_type == 'response.content_part.added':
        part = data.get('part', {})
        output_index = data.get('output_index', len(current_output) - 1)

        if current_output and 0 <= output_index < len(current_output):
            new_output = list(current_output)
            # Copy the item to mutate it
            item = new_output[output_index].copy()
            new_output[output_index] = item

            if 'content' not in item:
                item['content'] = []
            else:
                # Copy content list
                item['content'] = list(item['content'])

            if item.get('type') == 'reasoning':
                # Reasoning items should not have content parts
                pass
            else:
                item['content'].append(part)
            return new_output, None
        return current_output, None

    elif event_type == 'response.reasoning_summary_part.added':
        part = data.get('part', {})
        output_index = data.get('output_index', len(current_output) - 1)

        if current_output and 0 <= output_index < len(current_output):
            new_output = list(current_output)
            item = new_output[output_index].copy()
            new_output[output_index] = item

            if 'summary' not in item:
                item['summary'] = []
            else:
                item['summary'] = list(item['summary'])

            item['summary'].append(part)
            return new_output, None
        return current_output, None

    elif event_type.startswith('response.') and event_type.endswith('.delta'):
        # Generic Delta Handling
        parts = event_type.split('.')
        if len(parts) >= 3:
            delta_type = parts[1]
            delta = data.get('delta', '')

            output_index = data.get('output_index', len(current_output) - 1)

            if current_output and 0 <= output_index < len(current_output):
                new_output = list(current_output)
                item = new_output[output_index].copy()
                new_output[output_index] = item
                item_type = item.get('type', '')

                # Determine target field and object based on delta_type and item_type
                if True:
                    # Generic handling, refined by item type below
                    pass

                    if item_type == 'message':
                        # Message items: "text"/"output_text" -> "text"
                        # "reasoning_text" -> Skipped (should use reasoning item)
                        if delta_type in ['text', 'output_text']:
                            key = 'text'
                        elif delta_type in ['reasoning_text', 'reasoning_summary_text']:
                            # Skip reasoning updates for message items
                            return new_output, None
                        else:
                            key = delta_type

                        content_index = data.get('content_index', 0)
                        if 'content' not in item:
                            item['content'] = []
                        else:
                            item['content'] = list(item['content'])
                        content_list = item['content']

                        while len(content_list) <= content_index:
                            content_list.append({'type': 'text', 'text': ''})

                        # Copy the part to mutate it
                        part = content_list[content_index].copy()
                        content_list[content_index] = part

                        current_val = part.get(key)
                        if current_val is None:
                            # Initialize based on delta type
                            current_val = {} if isinstance(delta, dict) else ''

                        part[key] = deep_merge(current_val, delta)

                    elif item_type == 'reasoning':
                        # Reasoning items: "reasoning_text"/"reasoning_summary_text" -> "text"
                        # "text"/"output_text" -> Skipped (should use message item)
                        if delta_type == 'reasoning_summary_text':
                            # Summary updates -> item['summary']
                            key = 'text'
                            summary_index = data.get('summary_index', 0)
                            if 'summary' not in item:
                                item['summary'] = []
                            else:
                                item['summary'] = list(item['summary'])
                            summary_list = item['summary']

                            while len(summary_list) <= summary_index:
                                summary_list.append({'type': 'summary_text', 'text': ''})

                            part = summary_list[summary_index].copy()
                            summary_list[summary_index] = part

                            target_val = part.get(key, '')
                            part[key] = deep_merge(target_val, delta)

                        elif delta_type == 'reasoning_text':
                            # Reasoning body updates -> item['content']
                            key = 'text'
                            content_index = data.get('content_index', 0)
                            if 'content' not in item:
                                item['content'] = []
                            else:
                                item['content'] = list(item['content'])
                            content_list = item['content']

                            while len(content_list) <= content_index:
                                # Reasoning content parts default to text
                                content_list.append({'type': 'text', 'text': ''})

                            part = content_list[content_index].copy()
                            content_list[content_index] = part

                            target_val = part.get(key, '')
                            part[key] = deep_merge(target_val, delta)

                        elif delta_type in ['text', 'output_text']:
                            return new_output, None
                        else:
                            # Fallback just in case other deltas target reasoning?
                            pass

                    else:
                        # Fallback for other item types
                        if delta_type in ['text', 'output_text']:
                            key = 'text'
                        else:
                            key = delta_type

                        current_val = item.get(key)
                        if current_val is None:
                            current_val = {} if isinstance(delta, dict) else ''
                        item[key] = deep_merge(current_val, delta)

                return new_output, None

        return current_output, None

    elif event_type == 'response.output_item.done':
        # Delta Event: Output item complete
        item = data.get('item')
        output_index = data.get('output_index', len(current_output) - 1)

        new_output = list(current_output)
        if item and 0 <= output_index < len(current_output):
            new_output[output_index] = item
        elif item:
            new_output.append(item)
        return new_output, {}

    elif event_type.startswith('response.') and event_type.endswith('.done'):
        # Delta Events: response.content_part.done, response.text.done, etc.
        parts = event_type.split('.')
        if len(parts) >= 3:
            type_name = parts[1]

            # 1. Handle specific Delta "done" signals
            if type_name == 'content_part':
                # "Signaling that no further changes will occur to a content part"
                # If payloads contains the full part, we could update it.
                # Usually purely signaling in standard implementation, but we check payload.
                part = data.get('part')
                output_index = data.get('output_index', len(current_output) - 1)

                if part and current_output and 0 <= output_index < len(current_output):
                    new_output = list(current_output)
                    item = new_output[output_index].copy()
                    new_output[output_index] = item

                    if 'content' in item:
                        item['content'] = list(item['content'])
                        content_index = data.get('content_index', len(item['content']) - 1)
                        if 0 <= content_index < len(item['content']):
                            item['content'][content_index] = part
                            return new_output, {}
                return current_output, None

            elif type_name == 'reasoning_summary_part':
                part = data.get('part')
                output_index = data.get('output_index', len(current_output) - 1)

                if part and current_output and 0 <= output_index < len(current_output):
                    new_output = list(current_output)
                    item = new_output[output_index].copy()
                    new_output[output_index] = item

                    if 'summary' in item:
                        item['summary'] = list(item['summary'])
                        summary_index = data.get('summary_index', len(item['summary']) - 1)
                        if 0 <= summary_index < len(item['summary']):
                            item['summary'][summary_index] = part
                            return new_output, {}
                return current_output, None

            # 2. Generic Field Done (text.done, audio.done)
            if type_name not in ['completed', 'failed']:
                output_index = data.get('output_index', len(current_output) - 1)
                if current_output and 0 <= output_index < len(current_output):
                    key = (
                        'text'
                        if type_name
                        in [
                            'text',
                            'output_text',
                            'reasoning_text',
                            'reasoning_summary_text',
                        ]
                        else type_name
                    )
                    if key in data:
                        final_value = data[key]
                        new_output = list(current_output)
                        item = new_output[output_index].copy()
                        new_output[output_index] = item
                        item_type = item.get('type', '')

                        if item_type == 'message':
                            content_index = data.get('content_index', 0)
                            if 'content' in item:
                                item['content'] = list(item['content'])
                                if len(item['content']) > content_index:
                                    part = item['content'][content_index].copy()
                                    item['content'][content_index] = part
                                    part[key] = final_value
                        elif item_type == 'reasoning':
                            item['status'] = 'completed'
                        else:
                            item[key] = final_value

                        return new_output, {}

        return current_output, None

    elif event_type == 'response.completed':
        # State Machine Event: Completed
        response_data = data.get('response', {})
        final_output = response_data.get('output')

        # Some providers send an empty output on response.completed despite having streamed items
        new_output = final_output if final_output else current_output

        # Ensure reasoning items are marked as completed in the final output
        if new_output:
            for item in new_output:
                if item.get('type') == 'reasoning' and item.get('status') != 'completed':
                    item['status'] = 'completed'

        return new_output, {
            'usage': response_data.get('usage'),
            'done': True,
            'response_id': response_data.get('id'),
        }

    elif event_type == 'response.in_progress':
        # State Machine Event: In Progress
        # We could extract metadata if needed, but for now just acknowledge iteration
        return current_output, None

    elif event_type == 'response.failed':
        # State Machine Event: Failed
        error = data.get('response', {}).get('error', {})
        return current_output, {'error': error}

    else:
        return current_output, None

def get_images_from_messages(message_list):
    images = []

    for message in reversed(message_list):
        message_images = []
        for file in message.get('files', []):
            if file.get('type') == 'image':
                message_images.append(file.get('url'))
            elif file.get('content_type', '').startswith('image/'):
                message_images.append(file.get('url'))

        if message_images:
            images.append(message_images)

    return images

async def get_image_urls(delta_images, request, metadata, user) -> list[str]:
    if not isinstance(delta_images, list):
        return []

    image_urls = []
    for img in delta_images:
        if not isinstance(img, dict) or img.get('type') != 'image_url':
            continue

        url = img.get('image_url', {}).get('url')
        if not url:
            continue

        if url.startswith('data:image/png;base64'):
            url = await get_image_url_from_base64(request, url, metadata, user)

        image_urls.append(url)

    return image_urls

async def chat_image_generation_handler(request: Request, form_data: dict, extra_params: dict, user):
    metadata = extra_params.get('__metadata__', {})
    chat_id = metadata.get('chat_id', None)
    __event_emitter__ = extra_params.get('__event_emitter__', None)

    if not chat_id or not isinstance(chat_id, str) or not __event_emitter__:
        return form_data

    is_channel_chat = chat_id.startswith('channel:')
    image_metadata = {
        'message_id': metadata.get('message_id', None),
        **({'channel_id': chat_id.removeprefix('channel:')} if is_channel_chat else {'chat_id': chat_id}),
    }

    if not is_saved_chat_id(chat_id):
        message_list = form_data.get('messages', [])
    else:
        chat = await Chats.get_chat_by_id_and_user_id(chat_id, user.id)

        messages_map = chat.chat.get('history', {}).get('messages', {})
        message_id = chat.chat.get('history', {}).get('currentId')
        message_list = get_message_list(messages_map, message_id)

    user_message = get_last_user_message(message_list)

    prompt = user_message
    message_images = get_images_from_messages(message_list)

    # Limit to first 2 sets of images
    # We may want to change this in the future to allow more images
    input_images = []
    for idx, images in enumerate(message_images):
        if idx >= 2:
            break
        for image in images:
            input_images.append(image)

    # Called directly, bypassing the /images routes that enforce these switches.
    editing = len(input_images) > 0 and await Config.get('images.edit.enable')
    if not editing and not await Config.get('image_generation.enable'):
        return form_data

    if is_saved_chat_id(chat_id):
        await __event_emitter__(
            {
                'type': 'status',
                'data': {'description': 'Creating image', 'done': False},
            }
        )

    system_message_content = ''

    if editing:
        # Edit image(s)
        try:
            images = await image_edits(
                request=request,
                form_data=EditImageForm(**{'prompt': prompt, 'image': input_images}),
                metadata=image_metadata,
                user=user,
            )

            await __event_emitter__(
                {
                    'type': 'status',
                    'data': {'description': 'Image created', 'done': True},
                }
            )

            await __event_emitter__(
                {
                    'type': 'files',
                    'data': {
                        'files': [
                            {
                                'type': 'image',
                                **image,
                            }
                            for image in images
                        ]
                    },
                }
            )

            system_message_content = '<context>The requested image has been edited and created and is now being shown to the user. Let them know that it has been generated.</context>'
        except Exception as e:
            log.debug(e)

            error_message = ''
            if isinstance(e, HTTPException):
                if e.detail and isinstance(e.detail, dict):
                    error_message = e.detail.get('message', str(e.detail))
                else:
                    error_message = str(e.detail)

            await __event_emitter__(
                {
                    'type': 'status',
                    'data': {
                        'description': f'An error occurred while generating an image',
                        'done': True,
                    },
                }
            )

            system_message_content = f'<context>Image generation was attempted but failed. The system is currently unable to generate the image. Tell the user that the following error occurred: {error_message}</context>'

    elif not await Config.get('image_generation.enable'):
        await __event_emitter__(
            {
                'type': 'status',
                'data': {
                    'description': 'Image generation is disabled',
                    'done': True,
                },
            }
        )

        system_message_content = '<context>Image generation was requested but the feature is currently disabled by the administrator, so no image was created. Let the user know that image generation is currently unavailable.</context>'

    else:
        # Create image(s)
        if await Config.get('image_generation.prompt.enable'):
            try:
                res = await generate_image_prompt(
                    request,
                    {
                        'model': form_data['model'],
                        'messages': form_data['messages'],
                        'chat_id': metadata.get('chat_id'),
                    },
                    user,
                )

                # Handle JSONResponse from error paths
                if isinstance(res, JSONResponse):
                    try:
                        error_body = JSONCodec.loads(res.body)
                        detail = error_body.get('detail', 'Image prompt generation failed')
                    except Exception:
                        detail = 'Image prompt generation failed'
                    raise Exception(detail)

                response = res['choices'][0]['message']['content']

                try:
                    bracket_start = response.rfind('{')
                    bracket_end = response.rfind('}') + 1

                    if bracket_start == -1 or bracket_end == -1:
                        raise Exception('No JSON object found in the response')

                    response = response[bracket_start:bracket_end]
                    response = JSONCodec.loads(response)
                    prompt = response.get('prompt', [])
                except Exception as e:
                    prompt = user_message

            except Exception as e:
                log.exception(e)
                prompt = user_message

        try:
            images = await image_generations(
                request=request,
                form_data=CreateImageForm(**{'prompt': prompt}),
                metadata=image_metadata,
                user=user,
            )

            await __event_emitter__(
                {
                    'type': 'status',
                    'data': {'description': 'Image created', 'done': True},
                }
            )

            await __event_emitter__(
                {
                    'type': 'files',
                    'data': {
                        'files': [
                            {
                                'type': 'image',
                                **image,
                            }
                            for image in images
                        ]
                    },
                }
            )

            system_message_content = '<context>The requested image has been created by the system successfully and is now being shown to the user. Let the user know that the image they requested has been generated and is now shown in the chat.</context>'
        except Exception as e:
            log.debug(e)

            error_message = ''
            if isinstance(e, HTTPException):
                if e.detail and isinstance(e.detail, dict):
                    error_message = e.detail.get('message', str(e.detail))
                else:
                    error_message = str(e.detail)

            await __event_emitter__(
                {
                    'type': 'status',
                    'data': {
                        'description': f'An error occurred while generating an image',
                        'done': True,
                    },
                }
            )

            system_message_content = f'<context>Image generation was attempted but failed because of an error. The system is currently unable to generate the image. Tell the user that the following error occurred: {error_message}</context>'

    if system_message_content:
        form_data['messages'] = add_or_update_system_message(system_message_content, form_data['messages'])

    return form_data

async def convert_url_images_to_base64(form_data, user=None):
    messages = form_data.get('messages', [])

    for message in messages:
        content = message.get('content')
        if not isinstance(content, list):
            continue

        new_content = []

        for item in content:
            if not isinstance(item, dict) or item.get('type') != 'image_url':
                new_content.append(item)
                continue

            image_url_data = item.get('image_url', {})
            if isinstance(image_url_data, dict):
                image_url = image_url_data.get('url') or ''
            elif isinstance(image_url_data, str):
                image_url = image_url_data
            else:
                image_url = ''
            if image_url.startswith('data:image/'):
                new_content.append(item)
                continue

            try:
                base64_data = await get_image_base64_from_url(image_url, user=user)
                if base64_data:
                    image_url_payload = {'url': base64_data}
                    if isinstance(image_url_data, dict) and image_url_data.get('detail'):
                        image_url_payload['detail'] = image_url_data['detail']
                    new_content.append(
                        {
                            'type': 'image_url',
                            'image_url': image_url_payload,
                        }
                    )
                else:
                    new_content.append(item)
            except Exception as e:
                log.debug('Error converting image URL to base64: %s', e)
                new_content.append(item)

        message['content'] = new_content

    return form_data

async def load_messages_from_db(chat_id: str, message_id: str) -> Optional[list[dict]]:
    """
    Load the message chain from DB up to message_id,
    keeping only fields needed to rebuild the LLM payload.
    """
    messages_map = await Chats.get_messages_map_by_chat_id(chat_id)
    if not messages_map:
        return None

    db_messages = get_message_list(messages_map, message_id)
    if not db_messages:
        return None

    return [{k: v for k, v in msg.items() if k in MESSAGE_REPLAY_KEYS} for msg in db_messages]

def get_reasoning_format(model: dict) -> str | None:
    """
    Determine how reasoning should be included in reconstructed messages.

    Returns:
        'thinking': Ollama expects reasoning in the native thinking field.
        'think_tags': wrap reasoning in <think> tags inside content.
        'reasoning_content': llama.cpp supports reasoning_content as a top-level field.
        None: skip reasoning (safe default for strict providers).
    """
    provider = model.get('provider', '')
    if model.get('owned_by') == 'ollama':
        return 'thinking'
    if provider == 'llama.cpp':
        return 'reasoning_content'
    return None

def strip_reasoning_details(output: list) -> list:
    return [
        {key: value for key, value in item.items() if key != 'reasoning_details'} if isinstance(item, dict) else item
        for item in output
    ]

def process_messages_with_output(
    messages: list[dict],
    reasoning_format: str | None = None,
) -> list[dict]:
    """
    Process messages with OR-aligned output items for LLM consumption.

    For assistant messages with an 'output' field, rebuilds clean assistant
    messages (text + optional reasoning). Strips 'output' before the LLM call.
    """
    processed = []

    for message in messages:
        if message.get('role') == 'assistant' and message.get('output'):
            # Use output items for clean OpenAI-format messages
            output_messages = convert_output_to_messages(
                message['output'],
                raw=True,
                reasoning_format=reasoning_format,
            )
            if output_messages:
                processed.extend(output_messages)
                continue

        clean_message = dict(message)
        for key in ('id', 'files', 'output', 'model', 'contextSummary', 'context_summary', 'usage'):
            clean_message.pop(key, None)
        processed.append(clean_message)

    return processed

async def get_event_emitter_and_caller(metadata):
    event_emitter = None
    event_caller = None

    # event_emitter only needs user_id + chat_id + message_id.
    # It broadcasts to user:{user_id} room AND persists to DB,
    # so it works for backend-initiated calls (automations, API).
    if metadata.get('chat_id') and metadata.get('message_id'):
        event_emitter = await get_event_emitter(metadata)

    # event_caller needs session_id — it calls back to a specific
    # websocket session (used by direct tools, pyodide code interpreter).
    if metadata.get('session_id') and metadata.get('chat_id') and metadata.get('message_id'):
        event_caller = await get_event_call(metadata)

    return event_emitter, event_caller

async def build_chat_response_context(request, form_data, user, model, metadata, tasks, events):
    event_emitter, event_caller = await get_event_emitter_and_caller(metadata)
    return {
        'request': request,
        'form_data': form_data,
        'user': user,
        'model': model,
        'metadata': metadata,
        'tasks': tasks,
        'events': events,
        'event_emitter': event_emitter,
        'event_caller': event_caller,
    }

def get_response_data(response):
    if isinstance(response, list) and len(response) == 1:
        # If the response is a single-item list, unwrap it #17213
        response = response[0]

    if isinstance(response, JSONResponse):
        if isinstance(response.body, bytes):
            try:
                response_data = JSONCodec.loads(response.body.decode('utf-8', 'replace'))
            except JSONCodec.JSONDecodeError:
                response_data = {'error': {'detail': 'Invalid JSON response'}}
        else:
            response_data = response
    elif isinstance(response, dict):
        response_data = response
    else:
        response_data = None

    return response, response_data

def merge_events_into_response(response_data, events):
    if events and isinstance(events, list):
        extra_response = {}
        for event in events:
            if isinstance(event, dict):
                extra_response.update(event)
            else:
                extra_response[event] = True

        return {
            **extra_response,
            **response_data,
        }
    return response_data

def build_response_object(response, response_data):
    if isinstance(response, dict):
        return response_data
    if isinstance(response, JSONResponse):
        return JSONResponse(
            content=response_data,
            headers=response.headers,
            status_code=response.status_code,
        )
    return response

async def background_tasks_handler(ctx):
    request = ctx['request']
    form_data = ctx['form_data']
    user = ctx['user']
    metadata = ctx['metadata']
    tasks = ctx['tasks']
    event_emitter = ctx['event_emitter']

    message = None
    messages = []

    if is_saved_chat_id(metadata.get('chat_id')):
        messages_map = await Chats.get_messages_map_by_chat_id(metadata['chat_id'])
        if not messages_map:
            # Chat was deleted while the response was streaming — skip background tasks
            return
        message = messages_map.get(metadata['message_id'])

        message_list = get_message_list(messages_map, metadata['message_id'])

        # Remove details tags and files from the messages.
        # as get_message_list creates a new list, it does not affect
        # the original messages outside of this handler

        messages = []
        for message in message_list:
            content = message.get('content', '')
            if isinstance(content, list):
                for item in content:
                    if item.get('type') == 'text':
                        content = item['text']
                        break

            if isinstance(content, str):
                content = re.sub(
                    r'<details\b[^>]*>.*?<\/details>|!\[.*?\]\(.*?\)',
                    '',
                    content,
                    flags=re.S | re.I,
                ).strip()

            messages.append(
                {
                    **message,
                    'role': message.get('role', 'assistant'),  # Safe fallback for missing role
                    'content': content,
                }
            )
    else:
        # Local temp chat, get the model and message from the form_data
        message = get_last_user_message_item(form_data.get('messages', []))
        messages = form_data.get('messages', [])
        if message:
            message['model'] = form_data.get('model')

    if message and 'model' in message:
        if tasks and messages:
            if TASKS.FOLLOW_UP_GENERATION in tasks and tasks[TASKS.FOLLOW_UP_GENERATION]:
                res = await generate_follow_ups(
                    request,
                    {
                        'model': message['model'],
                        'messages': messages,
                        'message_id': metadata['message_id'],
                        'chat_id': metadata['chat_id'],
                    },
                    user,
                )

                if res and isinstance(res, dict):
                    if len(res.get('choices', [])) == 1:
                        response_message = res.get('choices', [])[0].get('message', {})

                        follow_ups_string = response_message.get('content') or response_message.get(
                            'reasoning_content', ''
                        )
                    else:
                        follow_ups_string = ''

                    follow_ups_string = follow_ups_string[
                        follow_ups_string.find('{') : follow_ups_string.rfind('}') + 1
                    ]

                    try:
                        follow_ups = JSONCodec.loads(follow_ups_string).get('follow_ups', [])
                        await event_emitter(
                            {
                                'type': 'chat:message:follow_ups',
                                'data': {
                                    'follow_ups': follow_ups,
                                },
                            }
                        )

                        if is_saved_chat_id(metadata.get('chat_id')):
                            await Chats.upsert_message_to_chat_by_id_and_message_id(
                                metadata['chat_id'],
                                metadata['message_id'],
                                {
                                    'followUps': follow_ups,
                                },
                                touch=False,
                            )

                    except Exception as e:
                        pass

            if is_saved_chat_id(metadata.get('chat_id')):  # Only update titles and tags for saved chats
                if TASKS.TITLE_GENERATION in tasks:
                    user_message = get_last_user_message(messages)
                    if user_message and len(user_message) > 100:
                        user_message = user_message[:100] + '...'

                    title = None
                    if tasks[TASKS.TITLE_GENERATION]:
                        res = await generate_title(
                            request,
                            {
                                'model': message['model'],
                                'messages': messages,
                                'chat_id': metadata['chat_id'],
                            },
                            user,
                        )

                        if res and isinstance(res, dict):
                            if len(res.get('choices', [])) == 1:
                                response_message = res.get('choices', [])[0].get('message', {})

                                title_string = (
                                    response_message.get('content')
                                    or response_message.get(
                                        'reasoning_content',
                                    )
                                    or message.get('content', user_message)
                                )
                            else:
                                title_string = ''

                            title_string = title_string[title_string.find('{') : title_string.rfind('}') + 1]

                            try:
                                title = JSONCodec.loads(title_string).get('title', user_message)
                            except Exception as e:
                                title = ''

                            if not title:
                                title = messages[0].get('content', user_message)

                            await Chats.update_chat_title_by_id(metadata['chat_id'], title)

                            await event_emitter(
                                {
                                    'type': 'chat:title',
                                    'data': title,
                                }
                            )

                    if title == None and len(messages) == 2 and (not messages_map or len(messages_map) <= 2):
                        title = messages[0].get('content', user_message)

                        await Chats.update_chat_title_by_id(metadata['chat_id'], title)

                        await event_emitter(
                            {
                                'type': 'chat:title',
                                'data': message.get('content', user_message),
                            }
                        )

                if TASKS.TAGS_GENERATION in tasks and tasks[TASKS.TAGS_GENERATION]:
                    res = await generate_chat_tags(
                        request,
                        {
                            'model': message['model'],
                            'messages': messages,
                            'chat_id': metadata['chat_id'],
                        },
                        user,
                    )

                    if res and isinstance(res, dict):
                        if len(res.get('choices', [])) == 1:
                            response_message = res.get('choices', [])[0].get('message', {})

                            tags_string = response_message.get('content') or response_message.get(
                                'reasoning_content', ''
                            )
                        else:
                            tags_string = ''

                        tags_string = tags_string[tags_string.find('{') : tags_string.rfind('}') + 1]

                        try:
                            tags = JSONCodec.loads(tags_string).get('tags', [])
                            await Chats.update_chat_tags_by_id(metadata['chat_id'], tags, user)

                            await event_emitter(
                                {
                                    'type': 'chat:tags',
                                    'data': tags,
                                }
                            )
                        except Exception as e:
                            pass

async def non_streaming_chat_response_handler(response, ctx):
    request = ctx['request']

    user = ctx['user']
    metadata = ctx['metadata']
    events = ctx['events']

    event_emitter = ctx['event_emitter']

    response, response_data = get_response_data(response)
    if response_data is None:
        return response

    chat_id = metadata.get('chat_id') or ''
    save_to_chat = is_saved_chat_id(chat_id)

    if event_emitter:
        try:
            if 'error' in response_data:
                error = response_data.get('error')

                if isinstance(error, dict):
                    error = error.get('detail', error)
                else:
                    error = str(error)

                log.error('Provider returned error (non-streaming): %s', error)

                if save_to_chat:
                    await Chats.upsert_message_to_chat_by_id_and_message_id(
                        metadata['chat_id'],
                        metadata['message_id'],
                        {
                            'error': {'content': error},
                        },
                    )
                if isinstance(error, str) or isinstance(error, dict):
                    await event_emitter(
                        {
                            'type': 'chat:message:error',
                            'data': {'error': {'content': error}},
                        }
                    )

            if 'selected_model_id' in response_data and save_to_chat:
                await Chats.upsert_message_to_chat_by_id_and_message_id(
                    metadata['chat_id'],
                    metadata['message_id'],
                    {
                        'selectedModelId': response_data['selected_model_id'],
                    },
                    touch=False,
                )

            choices = response_data.get('choices', [])
            response_output = response_data.get('output')
            content = choices[0].get('message', {}).get('content') if choices else ''

            if choices and (content or response_output):
                if content or response_output:
                    await event_emitter(
                        {
                            'type': 'chat:completion',
                            'data': response_data,
                        }
                    )

                    title = await Chats.get_chat_title_by_id(metadata['chat_id']) if save_to_chat else ''

                    # Use output from backend if provided (OR-compliant backends),
                    # otherwise generate from response content
                    if not response_output:
                        choice_message = choices[0].get('message', {})
                        reasoning_content = choice_message.get('reasoning_content') or choice_message.get('reasoning')
                        reasoning_details = get_reasoning_details(choice_message)
                        response_output = []
                        if reasoning_content or reasoning_details:
                            reasoning_item = {
                                'type': 'reasoning',
                                'id': output_id('r'),
                                'status': 'completed',
                                'start_tag': '<think>',
                                'end_tag': '</think>',
                                'attributes': {'type': 'reasoning_content'},
                                'content': (
                                    [{'type': 'output_text', 'text': reasoning_content}] if reasoning_content else []
                                ),
                                'summary': None,
                            }
                            if reasoning_details:
                                reasoning_item['reasoning_details'] = (
                                    reasoning_details if isinstance(reasoning_details, list) else [reasoning_details]
                                )
                            response_output.append(reasoning_item)
                        response_output.append(
                            {
                                'type': 'message',
                                'id': output_id('msg'),
                                'status': 'completed',
                                'role': 'assistant',
                                'content': [{'type': 'output_text', 'text': content}],
                            }
                        )

                    await event_emitter(
                        {
                            'type': 'chat:completion',
                            'data': {
                                'done': True,
                                'output': response_output,
                                'title': title,
                            },
                        }
                    )

                    # Save message in the database
                    usage = normalize_usage(response_data.get('usage', {}) or {})

                    if save_to_chat:
                        await Chats.upsert_message_to_chat_by_id_and_message_id(
                            metadata['chat_id'],
                            metadata['message_id'],
                            {
                                'done': True,
                                'role': 'assistant',
                                'output': response_output,
                                **({'usage': usage} if usage else {}),
                            },
                        )

                    await publish_chat_finished_event(request, user, metadata, title, content, response_output)

                    ctx['assistant_message'] = {
                        'content': content,
                        'output': response_output,
                        **({'usage': usage} if usage else {}),
                    }
                    await background_tasks_handler(ctx)

            response = build_response_object(response, merge_events_into_response(response_data, events))
        except Exception as e:
            log.debug('Error occurred while processing request: %s', e)
            chat_id = metadata.get('chat_id')
            if getattr(request.state, 'internal', False) is not True and chat_id and is_saved_chat_id(chat_id):
                webui_url = await Config.get('webui.url')
                await publish_event(
                    request,
                    EVENTS.CHAT_FAILED,
                    actor=user,
                    subject_id=chat_id,
                    subject_type='chat',
                    data={
                        'user_id': user.id,
                        'chat_id': chat_id,
                        'message_id': metadata.get('message_id'),
                        'model_id': metadata.get('model_id'),
                        'url': f'{webui_url}/c/{chat_id}' if webui_url else f'/c/{chat_id}',
                        'message': str(e),
                    },
                    message='Chat failed',
                )
            pass

        return response

    choices = response_data.get('choices', [])
    output = response_data.get('output')
    content = choices[0].get('message', {}).get('content') if choices else ''
    if isinstance(response, dict):
        response = merge_events_into_response(response_data, events)

    return response

async def streaming_chat_response_handler(response, ctx):
    request = ctx['request']

    form_data = ctx['form_data']

    user = ctx['user']
    model = ctx['model']

    metadata = ctx['metadata']
    events = ctx['events']

    event_emitter = ctx['event_emitter']
    event_caller = ctx['event_caller']
    chat_id = metadata.get('chat_id') or ''
    save_to_chat = is_saved_chat_id(chat_id)

    extra_params = {
        '__event_emitter__': event_emitter,
        '__event_call__': event_caller,
        '__user__': user.model_dump() if isinstance(user, UserModel) else {},
        '__metadata__': metadata,
        '__request__': request,
        '__model__': model,
        '__chat_id__': metadata.get('chat_id'),
        '__message_id__': metadata.get('message_id'),
    }

    # Standard streaming response handler
    # event_caller is optional — only needed for direct (client-side) tools
    # and pyodide code interpreter. Server-side tools work without it.
    if event_emitter:
        task_id = str(uuid4())  # Create a unique task ID.
        model_id = form_data.get('model', '')

        # Handle as a background task
        async def response_handler(response, events):
            tag_scan_positions = {}
            tag_boundary_positions = {}
            response_stream_task_id = metadata.get('task_id') or metadata.get('message_id')

            def tag_output_handler(content_type, tags, output):
                """
                Detect special tags (reasoning, solution) in streaming
                content and create corresponding OR-aligned output items directly.
                Operates on output items instead of content_blocks.

                Uses the text from the output items themselves for tag detection,
                eliminating state divergence between accumulated content and items.
                """
                end_flag = False

                def extract_attributes(tag_content):
                    """Extract attributes from a tag if they exist."""
                    attributes = {}
                    if not tag_content:
                        return attributes
                    matches = re.findall(r'(\w+)\s*=\s*"([^"]+)"', tag_content)
                    for key, value in matches:
                        attributes[key] = value
                    return attributes

                def get_last_text(out):
                    """Get text from last message item, or empty string."""
                    if out and out[-1].get('type') == 'message':
                        parts = out[-1].get('content', [])
                        if parts and parts[-1].get('type') == 'output_text':
                            return parts[-1].get('text', '')
                    return ''

                def set_last_text(out, text):
                    """Set text on last message item's output_text."""
                    if out and out[-1].get('type') == 'message':
                        parts = out[-1].get('content', [])
                        if parts and parts[-1].get('type') == 'output_text':
                            parts[-1]['text'] = text

                def get_scanned_length(item, text):
                    item_id = item.get('id')
                    if not item_id:
                        return 0

                    scanned_length = tag_scan_positions.get((item_id, content_type), 0)
                    return scanned_length if scanned_length <= len(text) else 0

                def save_scanned_length(item, text):
                    item_id = item.get('id')
                    if item_id:
                        tag_scan_positions[(item_id, content_type)] = len(text)

                def clear_scanned_length(item):
                    item_id = item.get('id')
                    if item_id:
                        tag_scan_positions.pop((item_id, content_type), None)
                        tag_boundary_positions.pop((item_id, content_type), None)

                def get_tag_boundaries(item, text, scanned_length):
                    """Index of the last '<', and of the last '>' or newline, before scanned_length."""
                    key = (item.get('id'), content_type)
                    scanned, last_open, last_boundary = tag_boundary_positions.get(key, (0, -1, -1))
                    if scanned > scanned_length:  # the item was rewritten, so the cached positions are stale
                        scanned, last_open, last_boundary = 0, -1, -1

                    if scanned < scanned_length:
                        # only text added since the last call can move either position
                        open_tag = text.rfind('<', scanned, scanned_length)
                        if open_tag != -1:
                            last_open = open_tag
                        boundary = max(
                            text.rfind('>', scanned, scanned_length),
                            text.rfind('\n', scanned, scanned_length),
                        )
                        if boundary != -1:
                            last_boundary = boundary
                        tag_boundary_positions[key] = (scanned_length, last_open, last_boundary)

                    return last_open, last_boundary

                # Map content_type to output item type
                output_type_map = {
                    'reasoning': 'reasoning',
                    'solution': 'message',  # solution tags just produce text
                }
                output_item_type = output_type_map.get(content_type, content_type)

                last_type = output[-1].get('type', '') if output else ''

                if last_type == 'message':
                    # Use the output item's own text for tag detection
                    item = output[-1]
                    item_text = get_last_text(output)
                    scanned_length = get_scanned_length(item, item_text)
                    max_start_tag_length = max((len(start_tag) for start_tag, _ in tags), default=1)
                    search_start = max(0, scanned_length - max_start_tag_length + 1)

                    if scanned_length and any(
                        start_tag.startswith('<') and start_tag.endswith('>') for start_tag, _ in tags
                    ):
                        open_tag_start, last_tag_boundary = get_tag_boundaries(item, item_text, scanned_length)
                        if open_tag_start > last_tag_boundary:
                            search_start = min(search_start, open_tag_start)

                    for start_tag, end_tag in tags:
                        match = re.compile(_start_tag_pattern(start_tag)).search(item_text, search_start)
                        if match:
                            clear_scanned_length(item)
                            try:
                                attr_content = match.group(1) if match.group(1) else ''
                            except Exception:
                                attr_content = ''

                            attributes = extract_attributes(attr_content)

                            before_tag = item_text[: match.start()]
                            after_tag = item_text[match.end() :]

                            # Keep only text before the tag in the message
                            set_last_text(output, before_tag)

                            if not before_tag.strip():
                                # Remove empty message item
                                if output and output[-1].get('type') == 'message':
                                    output.pop()

                            # Append the new output item
                            if output_item_type == 'reasoning':
                                output.append(
                                    {
                                        'type': 'reasoning',
                                        'id': output_id('r'),
                                        'status': 'in_progress',
                                        'start_tag': start_tag,
                                        'end_tag': end_tag,
                                        'attributes': attributes,
                                        'content': [],
                                        'summary': None,
                                        'started_at': time.time(),
                                    }
                                )
                            else:
                                # solution or other text-producing tag
                                output.append(
                                    {
                                        'type': 'message',
                                        'id': output_id('msg'),
                                        'status': 'in_progress',
                                        'role': 'assistant',
                                        'content': [{'type': 'output_text', 'text': ''}],
                                        '_tag_type': content_type,
                                        'start_tag': start_tag,
                                        'end_tag': end_tag,
                                        'attributes': attributes,
                                        'started_at': time.time(),
                                    }
                                )

                            if after_tag:
                                # Set the after_tag content on the new item
                                if output_item_type == 'reasoning':
                                    output[-1]['content'] = [{'type': 'output_text', 'text': after_tag}]
                                else:
                                    set_last_text(output, after_tag)

                                _, recursive_end = tag_output_handler(content_type, tags, output)
                                if recursive_end:
                                    end_flag = True

                            break
                    else:
                        save_scanned_length(item, item_text)

                elif (
                    (last_type == 'reasoning' and content_type == 'reasoning')
                    or (last_type == 'message' and output[-1].get('_tag_type') == content_type)
                ):
                    item = output[-1]
                    start_tag = item.get('start_tag', '')
                    end_tag = item.get('end_tag', '')

                    # Get the block content from the item itself
                    if last_type == 'reasoning':
                        parts = item.get('content', [])
                        block_content = ''
                        if parts and parts[-1].get('type') == 'output_text':
                            block_content = parts[-1].get('text', '')
                    else:
                        block_content = get_last_text(output)

                    scanned_length = get_scanned_length(item, block_content)
                    end_tag_search_start = max(0, scanned_length - max(len(end_tag), 1) + 1)

                    if block_content.find(end_tag, end_tag_search_start) != -1:
                        clear_scanned_length(item)
                        end_flag = True

                        # Strip start and end tags from content
                        start_tag_pattern = _start_tag_pattern(start_tag)
                        block_content = re.sub(start_tag_pattern, '', block_content).strip()

                        end_tag_pattern = rf'{re.escape(end_tag)}'
                        end_tag_regex = re.compile(end_tag_pattern, re.DOTALL)
                        split_content = end_tag_regex.split(block_content, maxsplit=1)

                        block_content = split_content[0].strip() if split_content else ''
                        leftover_content = split_content[1].strip() if len(split_content) > 1 else ''

                        if block_content:
                            # Update the item with final content
                            if last_type == 'reasoning':
                                item['content'] = [{'type': 'output_text', 'text': block_content}]
                                item['ended_at'] = time.time()
                                item['duration'] = int(item['ended_at'] - item['started_at'])
                                item['status'] = 'completed'
                            else:
                                set_last_text(output, block_content)
                                item['ended_at'] = time.time()

                            # Reset by appending a new message item for leftover
                            output.append(
                                {
                                    'type': 'message',
                                    'id': output_id('msg'),
                                    'status': 'in_progress',
                                    'role': 'assistant',
                                    'content': [
                                        {
                                            'type': 'output_text',
                                            'text': leftover_content,
                                        }
                                    ],
                                }
                            )
                        else:
                            # Remove the block if content is empty
                            output.pop()
                            output.append(
                                {
                                    'type': 'message',
                                    'id': output_id('msg'),
                                    'status': 'in_progress',
                                    'role': 'assistant',
                                    'content': [
                                        {
                                            'type': 'output_text',
                                            'text': leftover_content,
                                        }
                                    ],
                                }
                            )
                    else:
                        save_scanned_length(item, block_content)

                return output, end_flag

            message = (
                await Chats.get_message_by_id_and_message_id(metadata['chat_id'], metadata['message_id'])
                if save_to_chat
                else None
            )

            last_assistant_message = None
            try:
                if form_data['messages'][-1]['role'] == 'assistant':
                    last_assistant_message = get_last_assistant_message(form_data['messages'])
            except Exception as e:
                pass

            initial_content = (
                message.get('content', '') if message else last_assistant_message if last_assistant_message else ''
            )
            content_parts = [initial_content] if initial_content else []

            # Initialize output: use existing from message if continuing, else create new
            existing_output = message.get('output') if message else None
            prior_output = []
            if existing_output and metadata.get('assistant_message_id'):
                prior_output = list(existing_output)
                if (
                    prior_output
                    and prior_output[-1].get('type') == 'message'
                    and prior_output[-1].get('status') == 'in_progress'
                ):
                    msg_parts = prior_output[-1].get('content', [])
                    if not msg_parts or (len(msg_parts) == 1 and not msg_parts[0].get('text', '').strip()):
                        prior_output.pop()
                output = []
                content_parts = []
            elif existing_output:
                output = existing_output
            else:
                # Only create an initial message item if there is content to initialize with
                if initial_content:
                    output = [
                        {
                            'type': 'message',
                            'id': output_id('msg'),
                            'status': 'in_progress',
                            'role': 'assistant',
                            'content': [{'type': 'output_text', 'text': initial_content}],
                        }
                    ]
                else:
                    output = []

            usage = None
            last_response_id = None

            def full_output():
                return prior_output + output if prior_output else output

            def get_message_error_content(error):
                if isinstance(error, HTTPException):
                    error = error.detail
                elif isinstance(error, dict):
                    error = error.get('detail', error)
                else:
                    error = str(error)

                return error if isinstance(error, (str, dict)) else str(error)

            async def emit_message_error(error_content):
                if save_to_chat:
                    await Chats.upsert_message_to_chat_by_id_and_message_id(
                        metadata['chat_id'],
                        metadata['message_id'],
                        {'error': {'content': error_content}},
                    )
                await event_emitter(
                    {
                        'type': 'chat:message:error',
                        'data': {'error': {'content': error_content}},
                    }
                )

            reasoning_tags_param = metadata.get('params', {}).get('reasoning_tags')
            DETECT_REASONING_TAGS = reasoning_tags_param is not False

            reasoning_tags = []
            if DETECT_REASONING_TAGS:
                if isinstance(reasoning_tags_param, list) and len(reasoning_tags_param) == 2:
                    reasoning_tags = [(reasoning_tags_param[0], reasoning_tags_param[1])]
                else:
                    reasoning_tags = DEFAULT_REASONING_TAGS

            try:
                for event in events:
                    await event_emitter(
                        {
                            'type': 'chat:completion',
                            'data': event,
                        }
                    )

                    # Save message in the database
                    if save_to_chat:
                        await Chats.upsert_message_to_chat_by_id_and_message_id(
                            metadata['chat_id'],
                            metadata['message_id'],
                            {
                                **event,
                            },
                        )

                async def stream_body_handler(response, form_data):
                    nonlocal usage
                    nonlocal output
                    nonlocal prior_output
                    nonlocal last_response_id

                    delta_count = 0
                    delta_chunk_size = max(
                        CHAT_RESPONSE_STREAM_DELTA_CHUNK_SIZE,
                        int(metadata.get('params', {}).get('stream_delta_chunk_size') or 1),
                    )
                    last_delta_data = None
                    last_delta_type = None
                    last_delta_key = None

                    joined_content = ''
                    joined_part_count = 0

                    async def save_current_response_stream(stream_output: list | None = None):
                        nonlocal joined_content
                        nonlocal joined_part_count

                        if not chat_id or not metadata.get('message_id'):
                            return

                        # content_parts is append-only, so its length tells us when the join is stale
                        if joined_part_count != len(content_parts):
                            joined_content = ''.join(content_parts)
                            joined_part_count = len(content_parts)

                        current_stream_output = stream_output if stream_output is not None else full_output()
                        await save_response_stream(
                            request.app.state.redis,
                            response_stream_task_id,
                            chat_id,
                            metadata.get('message_id'),
                            joined_content or get_output_text(current_stream_output),
                            current_stream_output,
                        )

                    def get_response_delta_key(delta_data: dict):
                        event_type = delta_data.get('type', '')
                        if not event_type.startswith('response.') or not event_type.endswith('.delta'):
                            return None
                        return (
                            event_type,
                            delta_data.get('item_id'),
                            delta_data.get('output_index'),
                            delta_data.get('content_index'),
                            delta_data.get('summary_index'),
                        )

                    def get_response_data_with_full_output_index(response_data: dict):
                        if prior_output and isinstance(response_data.get('output_index'), int):
                            return {
                                **response_data,
                                'output_index': response_data['output_index'] + len(prior_output),
                            }
                        return response_data

                    async def flush_pending_delta_data(threshold: int = 0):
                        nonlocal delta_count
                        nonlocal last_delta_data
                        nonlocal last_delta_type
                        nonlocal last_delta_key

                        if delta_count >= threshold and last_delta_data:
                            await event_emitter(
                                {
                                    'type': 'response:completion',
                                    'data': last_delta_data,
                                }
                            )
                            await save_current_response_stream()
                            delta_count = 0
                            last_delta_data = None
                            last_delta_type = None
                            last_delta_key = None

                    async def queue_pending_delta_data(delta_data: dict, delta_type: str):
                        nonlocal delta_count
                        nonlocal last_delta_data
                        nonlocal last_delta_type
                        nonlocal last_delta_key

                        delta_data = get_response_data_with_full_output_index(delta_data)
                        delta_key = get_response_delta_key(delta_data)
                        if (
                            last_delta_data
                            and last_delta_key == delta_key
                            and isinstance(last_delta_data.get('delta'), str)
                            and isinstance(delta_data.get('delta'), str)
                        ):
                            last_delta_data['delta'] += delta_data['delta']
                            delta_count += 1
                        else:
                            if last_delta_data and (last_delta_type != delta_type or last_delta_key != delta_key):
                                await flush_pending_delta_data()

                            delta_count += 1
                            last_delta_data = delta_data
                            last_delta_type = delta_type
                            last_delta_key = delta_key

                        if delta_count >= delta_chunk_size:
                            await flush_pending_delta_data(delta_chunk_size)

                    async def emit_response_completion_event(response_data: dict, stream_output: list | None = None):
                        if response_data.get('type', '').endswith('.delta'):
                            await queue_pending_delta_data(
                                response_data,
                                response_data.get('type', 'response.delta'),
                            )
                            return

                        response_data = get_response_data_with_full_output_index(response_data)
                        await flush_pending_delta_data()
                        await event_emitter(
                            {
                                'type': 'response:completion',
                                'data': get_response_completion_event_data(response_data),
                            }
                        )
                        await save_current_response_stream(stream_output)

                    async for line in response.body_iterator:
                        line = line.decode('utf-8', 'replace') if isinstance(line, bytes) else line
                        data = line

                        # Skip empty lines
                        if not data or data.isspace():
                            continue

                        # "data:" is the prefix for each event
                        if not data.startswith('data:'):
                            # Some upstreams return plain JSON error lines in a streaming response
                            # (without SSE `data:` prefix). Try to normalize these into standard
                            # error events so frontend and DB paths still receive them.
                            try:
                                raw_obj = JSONCodec.loads(data)
                                raw_error = raw_obj.get('error') if isinstance(raw_obj, dict) else None
                                if raw_error:
                                    if save_to_chat:
                                        try:
                                            await Chats.upsert_message_to_chat_by_id_and_message_id(
                                                metadata['chat_id'],
                                                metadata['message_id'],
                                                {
                                                    'error': {'content': raw_error},
                                                },
                                            )
                                        except Exception:
                                            pass
                                    await event_emitter({'type': 'chat:completion', 'data': {'error': raw_error}})
                            except Exception:
                                pass
                            continue

                        # Remove the "data:" prefix
                        data = data[5:].strip()

                        try:
                            data = JSONCodec.loads(data)

                            if data:
                                if 'event' in data and not getattr(request.state, 'direct', False):
                                    await event_emitter(data.get('event', {}))

                                if 'selected_model_id' in data:
                                    model_id = data['selected_model_id']
                                    if save_to_chat:
                                        await Chats.upsert_message_to_chat_by_id_and_message_id(
                                            metadata['chat_id'],
                                            metadata['message_id'],
                                            {
                                                'selectedModelId': model_id,
                                            },
                                            touch=False,
                                        )
                                    await event_emitter(
                                        {
                                            'type': 'chat:completion',
                                            'data': data,
                                        }
                                    )
                                # Check for Responses API events (type field starts with "response.")
                                elif data.get('type', '').startswith('response.'):
                                    response_data_type = data.get('type', '')
                                    response_data_is_delta = response_data_type.endswith('.delta')
                                    output, response_metadata = handle_responses_streaming_event(data, output)

                                    if not response_data_is_delta:
                                        await flush_pending_delta_data()

                                    # Emit citation sources from finalized output items
                                    # (mirrors Chat Completions annotation handling at delta level)
                                    if response_data_type == 'response.output_item.done':
                                        item = data.get('item', {})
                                        if item.get('type') == 'message':
                                            for part in item.get('content', []):
                                                for annotation in part.get('annotations', []):
                                                    if annotation.get('type') == 'url_citation':
                                                        # Handle both flat (Responses API) and nested (Chat Completions) formats
                                                        url_citation = annotation.get('url_citation', annotation)

                                                        url = url_citation.get('url', '')
                                                        title = url_citation.get('title', url)

                                                        if url:
                                                            await event_emitter(
                                                                {
                                                                    'type': 'source',
                                                                    'data': {
                                                                        'source': {
                                                                            'name': title,
                                                                            'url': url,
                                                                        },
                                                                        'document': [title],
                                                                        'metadata': [
                                                                            {
                                                                                'source': url,
                                                                                'name': title,
                                                                            }
                                                                        ],
                                                                    },
                                                                }
                                                            )

                                    # Merge any metadata (usage, etc.)
                                    # Strip 'done' — response.completed emits
                                    # it but we may still need to execute tool
                                    # calls. The outer middleware manages the
                                    # actual completion signal.
                                    if response_metadata:
                                        if ENABLE_RESPONSES_API_STATEFUL:
                                            response_id = response_metadata.pop('response_id', None)
                                            if response_id:
                                                last_response_id = response_id

                                        # Normalize and capture usage for DB persistence
                                        if response_metadata.get('usage'):
                                            usage = merge_usage(usage, response_metadata['usage'])
                                            response_metadata['usage'] = usage

                                        if response_metadata.get('error'):
                                            await event_emitter(
                                                {
                                                    'type': 'chat:completion',
                                                    'data': {'error': response_metadata['error']},
                                                }
                                            )

                                    await emit_response_completion_event(data)

                                    if response_metadata and response_metadata.get('usage'):
                                        await event_emitter(
                                            {
                                                'type': 'chat:completion',
                                                'data': {'usage': usage},
                                            }
                                        )
                                    continue
                                else:
                                    choices = data.get('choices', [])

                                    # Normalize usage data to standard format
                                    raw_usage = data.get('usage', {}) or {}
                                    raw_usage.update(data.get('timings', {}))  # llama.cpp
                                    if raw_usage:
                                        usage = merge_usage(usage, raw_usage)
                                        await event_emitter(
                                            {
                                                'type': 'chat:completion',
                                                'data': {
                                                    'usage': usage,
                                                },
                                            }
                                        )

                                    if not choices:
                                        error = data.get('error', {})
                                        if error:
                                            log.error('Provider returned error (streaming): %s', error)
                                            if save_to_chat:
                                                try:
                                                    await Chats.upsert_message_to_chat_by_id_and_message_id(
                                                        metadata['chat_id'],
                                                        metadata['message_id'],
                                                        {
                                                            'error': {'content': error},
                                                        },
                                                    )
                                                except Exception:
                                                    pass
                                            await event_emitter(
                                                {
                                                    'type': 'chat:completion',
                                                    'data': {
                                                        'error': error,
                                                    },
                                                }
                                            )
                                        continue

                                    delta = choices[0].get('delta', {})
                                    delta_type = 'content'

                                    # Handle delta annotations
                                    annotations = delta.get('annotations')
                                    if annotations:
                                        for annotation in annotations:
                                            if (
                                                annotation.get('type') == 'url_citation'
                                                and 'url_citation' in annotation
                                            ):
                                                url_citation = annotation['url_citation']

                                                url = url_citation.get('url', '')
                                                title = url_citation.get('title', url)

                                                await event_emitter(
                                                    {
                                                        'type': 'source',
                                                        'data': {
                                                            'source': {
                                                                'name': title,
                                                                'url': url,
                                                            },
                                                            'document': [title],
                                                            'metadata': [
                                                                {
                                                                    'source': url,
                                                                    'name': title,
                                                                }
                                                            ],
                                                        },
                                                    }
                                                )

                                    delta_images = delta.get('images')
                                    image_urls = (
                                        await get_image_urls(delta_images, request, metadata, user)
                                        if delta_images
                                        else []
                                    )
                                    if image_urls:
                                        image_file_list = [{'type': 'image', 'url': url} for url in image_urls]
                                        message_files = image_file_list
                                        if save_to_chat:
                                            message_files = await Chats.add_message_files_by_id_and_message_id(
                                                metadata['chat_id'],
                                                metadata['message_id'],
                                                image_file_list,
                                            )
                                            if message_files is None:
                                                message_files = image_file_list

                                        await event_emitter(
                                            {
                                                'type': 'files',
                                                'data': {'files': message_files},
                                            }
                                        )

                                    # content and reasoning deltas are raw JSON: a stream filter can make them any type
                                    value = delta.get('content')
                                    if value and not isinstance(value, str):
                                        value = f'{value}'

                                    reasoning_content = (
                                        delta.get('reasoning_content')
                                        or delta.get('reasoning')
                                        or delta.get('thinking')
                                    )
                                    if reasoning_content and not isinstance(reasoning_content, str):
                                        reasoning_content = f'{reasoning_content}'
                                    reasoning_details = get_reasoning_details(delta)
                                    reasoning_detail_items = (
                                        [item for item in reasoning_details if isinstance(item, dict)]
                                        if isinstance(reasoning_details, list)
                                        else [reasoning_details]
                                        if isinstance(reasoning_details, dict)
                                        else []
                                    )
                                    existing_reasoning_item = next(
                                        (item for item in reversed(output) if item.get('type') == 'reasoning'),
                                        None,
                                    )
                                    message_index = next(
                                        (i for i, item in enumerate(output) if item.get('type') == 'message'),
                                        None,
                                    )
                                    if reasoning_content or (
                                        reasoning_detail_items
                                        and (
                                            existing_reasoning_item
                                            or any(
                                                item.get('text') or item.get('summary') or item.get('data')
                                                for item in reasoning_detail_items
                                            )
                                        )
                                    ):
                                        reasoning_item = (
                                            existing_reasoning_item
                                            if (reasoning_detail_items and not reasoning_content)
                                            or message_index is not None
                                            else None
                                        )

                                        if reasoning_item is None:
                                            if not output or output[-1].get('type') != 'reasoning':
                                                reasoning_item = {
                                                    'type': 'reasoning',
                                                    'id': output_id('r'),
                                                    'status': 'in_progress',
                                                    'start_tag': '<think>',
                                                    'end_tag': '</think>',
                                                    'attributes': {'type': 'reasoning_content'},
                                                    'content': [],
                                                    'summary': None,
                                                    'started_at': time.time(),
                                                }
                                                if message_index is not None:
                                                    reasoning_item['ended_at'] = time.time()
                                                    reasoning_item['duration'] = 0
                                                    reasoning_item['status'] = 'completed'
                                                    output.insert(message_index, reasoning_item)
                                                else:
                                                    output.append(reasoning_item)
                                            else:
                                                reasoning_item = output[-1]

                                        if reasoning_content:
                                            # Append to reasoning content
                                            parts = reasoning_item.get('content', [])
                                            if parts and parts[-1].get('type') == 'output_text':
                                                parts[-1]['text'] += reasoning_content
                                            else:
                                                reasoning_item['content'] = [
                                                    {
                                                        'type': 'output_text',
                                                        'text': reasoning_content,
                                                    }
                                                ]

                                            reasoning_index = output.index(reasoning_item)
                                            data = {
                                                'type': 'response.reasoning_text.delta',
                                                'item_id': reasoning_item.get('id'),
                                                'output_index': reasoning_index,
                                                'content_index': max(
                                                    len(reasoning_item.get('content', [])) - 1,
                                                    0,
                                                ),
                                                'delta': reasoning_content,
                                            }
                                            delta_type = 'response.reasoning_text.delta'

                                        if reasoning_detail_items:
                                            merge_streamed_reasoning_details(
                                                reasoning_item.setdefault('reasoning_details', []),
                                                reasoning_detail_items,
                                            )
                                            await save_current_response_stream()
                                            # Providers such as OpenRouter send reasoning_details
                                            # alongside the reasoning text: only drop the event when
                                            # the details were all there was to report, otherwise the
                                            # reasoning delta never reaches the client.
                                            if not reasoning_content:
                                                data = None

                                    if value:
                                        if (
                                            output
                                            and output[-1].get('type') == 'reasoning'
                                            and output[-1].get('attributes', {}).get('type') == 'reasoning_content'
                                        ):
                                            reasoning_item = output[-1]
                                            reasoning_item['ended_at'] = time.time()
                                            reasoning_item['duration'] = int(
                                                reasoning_item['ended_at'] - reasoning_item['started_at']
                                            )
                                            reasoning_item['status'] = 'completed'

                                            output.append(
                                                {
                                                    'type': 'message',
                                                    'id': output_id('msg'),
                                                    'status': 'in_progress',
                                                    'role': 'assistant',
                                                    'content': [
                                                        {
                                                            'type': 'output_text',
                                                            'text': '',
                                                        }
                                                    ],
                                                }
                                            )

                                        if ENABLE_CHAT_RESPONSE_BASE64_IMAGE_URL_CONVERSION:
                                            value = await convert_markdown_base64_images(
                                                request,
                                                value,
                                                {
                                                    'chat_id': metadata.get('chat_id', None),
                                                    'message_id': metadata.get('message_id', None),
                                                },
                                                user,
                                            )

                                        # closure-cell str += recopies per chunk; append + join once at read is O(n)
                                        content_parts.append(value)

                                        # Check if we're inside a tag-based block
                                        # (reasoning or solution).
                                        # If so, append to the existing in-progress
                                        # item instead of creating a new message —
                                        # otherwise tag_output_handler re-detects the
                                        # start tag on every chunk and fragments the
                                        # output.
                                        last_item = output[-1] if output else None
                                        last_item_type = last_item.get('type', '') if last_item else ''
                                        inside_tag_block = (
                                            last_item is not None
                                            and last_item.get('status') == 'in_progress'
                                            and last_item.get('attributes', {}).get('type') != 'reasoning_content'
                                            and (
                                                last_item_type == 'reasoning'
                                                or (
                                                    last_item_type == 'message'
                                                    and last_item.get('_tag_type') is not None
                                                )
                                            )
                                        )

                                        if inside_tag_block:
                                            # Append to the existing tag-based item
                                            if last_item_type == 'reasoning':
                                                parts = last_item.get('content', [])
                                                if parts and parts[-1].get('type') == 'output_text':
                                                    parts[-1]['text'] += value
                                                else:
                                                    last_item['content'] = [
                                                        {
                                                            'type': 'output_text',
                                                            'text': value,
                                                        }
                                                    ]
                                            else:
                                                # solution or other _tag_type message
                                                msg_parts = last_item.get('content', [])
                                                if msg_parts and msg_parts[-1].get('type') == 'output_text':
                                                    msg_parts[-1]['text'] += value
                                                else:
                                                    last_item['content'] = [
                                                        {
                                                            'type': 'output_text',
                                                            'text': value,
                                                        }
                                                    ]
                                        else:
                                            if not output or output[-1].get('type') != 'message':
                                                output.append(
                                                    {
                                                        'type': 'message',
                                                        'id': output_id('msg'),
                                                        'status': 'in_progress',
                                                        'role': 'assistant',
                                                        'content': [
                                                            {
                                                                'type': 'output_text',
                                                                'text': '',
                                                            }
                                                        ],
                                                    }
                                                )

                                            # Append value to last message item's text
                                            msg_parts = output[-1].get('content', [])
                                            if msg_parts and msg_parts[-1].get('type') == 'output_text':
                                                msg_parts[-1]['text'] += value
                                            else:
                                                output[-1]['content'] = [
                                                    {
                                                        'type': 'output_text',
                                                        'text': value,
                                                    }
                                                ]

                                        if DETECT_REASONING_TAGS:
                                            output, _ = tag_output_handler(
                                                'reasoning',
                                                reasoning_tags,
                                                output,
                                            )

                                            output, _ = tag_output_handler(
                                                'solution',
                                                DEFAULT_SOLUTION_TAGS,
                                                output,
                                            )

                                        target_index = len(output) - 1
                                        target_item = output[target_index] if target_index >= 0 else {}
                                        target_content = target_item.get('content', [])
                                        content_index = max(len(target_content) - 1, 0)
                                        delta_event_type = (
                                            'response.reasoning_text.delta'
                                            if target_item.get('type') == 'reasoning'
                                            else 'response.output_text.delta'
                                        )
                                        data = {
                                            'type': delta_event_type,
                                            'item_id': target_item.get('id'),
                                            'output_index': target_index,
                                            'content_index': content_index,
                                            'delta': value,
                                        }
                                        delta_type = delta_event_type

                                if delta and data:
                                    await queue_pending_delta_data(data, delta_type)
                                elif data:
                                    await event_emitter(
                                        {
                                            'type': 'chat:completion',
                                            'data': data,
                                        }
                                    )
                        except (asyncio.CancelledError, KeyboardInterrupt):
                            raise
                        except Exception as e:
                            done = 'data: [DONE]' in line
                            if done:
                                pass
                            else:
                                log.debug('Error: %s', e)
                                continue
                    await flush_pending_delta_data()

                    if output:
                        # Clean up the last message item
                        if output[-1].get('type') == 'message':
                            parts = output[-1].get('content', [])
                            if parts and parts[-1].get('type') == 'output_text':
                                parts[-1]['text'] = parts[-1]['text'].strip()

                                if not parts[-1]['text']:
                                    output.pop()

                                    if not output:
                                        output.append(
                                            {
                                                'type': 'message',
                                                'id': output_id('msg'),
                                                'status': 'in_progress',
                                                'role': 'assistant',
                                                'content': [{'type': 'output_text', 'text': ''}],
                                            }
                                        )

                        if output[-1].get('type') == 'reasoning':
                            reasoning_item = output[-1]
                            if reasoning_item.get('ended_at') is None:
                                reasoning_item['ended_at'] = time.time()
                                if reasoning_item.get('started_at') is not None:
                                    reasoning_item['duration'] = int(
                                        reasoning_item['ended_at'] - reasoning_item['started_at']
                                    )
                                reasoning_item['status'] = 'completed'

                try:
                    await stream_body_handler(response, form_data)
                finally:
                    if response.background:
                        await response.background()

                # Mark all in-progress items as completed
                for item in output:
                    if item.get('status') == 'in_progress':
                        item['status'] = 'completed'

                current_output = full_output()
                title = await Chats.get_chat_title_by_id(metadata['chat_id']) if save_to_chat else ''
                data = {
                    'done': True,
                    'output': current_output,
                    'title': title,
                    **({'usage': usage} if usage else {}),
                }

                if save_to_chat:
                    # Save final output once. The delta path keeps in-progress
                    # state in response_streams instead of writing tokens to DB.
                    await Chats.upsert_message_to_chat_by_id_and_message_id(
                        metadata['chat_id'],
                        metadata['message_id'],
                        {
                            'done': True,
                            'output': current_output,
                            **({'usage': usage} if usage else {}),
                        },
                    )

                await clear_response_stream(request.app.state.redis, response_stream_task_id)
                await publish_chat_finished_event(
                    request, user, metadata, title, ''.join(content_parts), current_output
                )

                await event_emitter(
                    {
                        'type': 'chat:completion',
                        'data': data,
                    }
                )

                ctx['assistant_message'] = {
                    'content': ''.join(content_parts) or get_output_text(current_output),
                    'output': current_output,
                    **({'usage': usage} if usage else {}),
                }
                await background_tasks_handler(ctx)
            except asyncio.CancelledError:
                log.warning('Task was cancelled!')

                # Close the response body iterator to trigger cleanup
                # in stream_wrapper's finally block and release the
                # upstream connection.  Without this, the async
                # generator is orphaned and may spin in anyio internals.
                if hasattr(response, 'body_iterator') and hasattr(response.body_iterator, 'aclose'):
                    try:
                        await asyncio.shield(response.body_iterator.aclose())
                    except (asyncio.CancelledError, Exception):
                        pass

                async def save_cancelled_state():
                    await event_emitter({'type': 'chat:tasks:cancel'})
                    if save_to_chat:
                        await Chats.upsert_message_to_chat_by_id_and_message_id(
                            metadata['chat_id'],
                            metadata['message_id'],
                            {
                                'done': True,
                                'output': full_output(),
                            },
                        )
                    await clear_response_stream(request.app.state.redis, response_stream_task_id)

                try:
                    await asyncio.shield(save_cancelled_state())
                except (asyncio.CancelledError, Exception):
                    pass
                raise  # re-raise CancelledError for proper propagation

            if response.background is not None:
                await response.background()

        return await response_handler(response, events)

    else:
        # Fallback: no event emitter (e.g. API/background contexts) — pass the
        # provider stream through untouched.
        async def stream_wrapper(original_generator, events):
            def wrap_item(item):
                return f'data: {item}\n\n'

            for event in events:
                if event:
                    yield wrap_item(JSONCodec.dumps(event))

            async for data in original_generator:
                if data:
                    yield data

        return StreamingResponse(
            stream_wrapper(response.body_iterator, events),
            headers=dict(response.headers),
            background=response.background,
        )


async def process_chat_response(response, ctx):
    # Non-streaming response
    if not isinstance(response, StreamingResponse):
        return await non_streaming_chat_response_handler(response, ctx)

    # Non standard response
    if not any(
        content_type in response.headers['Content-Type']
        for content_type in ['text/event-stream', 'application/x-ndjson']
    ):
        return response

    # Streaming response
    return await streaming_chat_response_handler(response, ctx)


async def process_chat_payload(request, form_data, user, metadata, model):
    # Ensure chat_id is always a string — external API clients may omit it.
    if not isinstance(metadata.get('chat_id'), str):
        metadata['chat_id'] = ''

    # Captured before apply_params_to_form_data pops 'params'; populates
    # metadata['system_prompt'] below.
    model_system_prompt = (form_data.get('params') or {}).get('system')

    form_data = apply_params_to_form_data(form_data, model)
    log.debug('form_data: %s', form_data)

    # Guided regeneration: extract before it reaches the LLM provider
    regeneration_prompt = form_data.pop('regeneration_prompt', None)

    # Load messages from DB when available — the DB preserves structured
    # 'output' items which the frontend strips, causing reasoning to be merged
    # into content.
    chat_id = metadata.get('chat_id')
    user_message_id = metadata.get('user_message_id')

    if is_saved_chat_id(chat_id) and user_message_id:
        db_messages = await load_messages_from_db(chat_id, user_message_id)
        if db_messages:
            # Continue: the frontend sends assistant_message_id when continuing
            # an existing response. Load its content so the LLM sees prior output.
            assistant_message_id = metadata.get('assistant_message_id')
            if assistant_message_id:
                assistant_message = await Chats.get_message_by_id_and_message_id(chat_id, assistant_message_id)
                if assistant_message and (assistant_message.get('content') or assistant_message.get('output')):
                    db_messages.append({k: v for k, v in assistant_message.items() if k in MESSAGE_REPLAY_KEYS})

            system_message = get_system_message(form_data.get('messages', []))
            form_data['messages'] = [system_message, *db_messages] if system_message else db_messages

            # Inject image files into content as image_url parts (mirrors frontend logic)
            for message in form_data['messages']:
                image_files = [
                    f
                    for f in message.get('files', [])
                    if f.get('type') == 'image' or (f.get('content_type') or '').startswith('image/')
                ]
                if message.get('role') == 'user' and image_files:
                    text_content = message.get('content', '')
                    if isinstance(text_content, str):
                        message['content'] = [
                            {'type': 'text', 'text': text_content},
                            *[
                                {
                                    'type': 'image_url',
                                    'image_url': {'url': f['url']},
                                }
                                for f in image_files
                                if f.get('url')
                            ],
                        ]
                # Strip files field — it's been incorporated into content
                message.pop('files', None)

    if regeneration_prompt:
        form_data['messages'].append({'role': 'user', 'content': regeneration_prompt})

    if is_saved_chat_id(chat_id) and user_message_id:
        if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
            compaction_models = {
                **dict(request.app.state.MODELS.items()),
                request.state.model['id']: request.state.model,
            }
        else:
            compaction_models = request.app.state.MODELS

        system_message = get_system_message(form_data.get('messages', []))
        system_prompt = get_content_from_message(system_message) if system_message else ''

        try:
            form_data['messages'], context_summary, _ = await compact_messages_for_request(
                request,
                user,
                form_data.get('messages', []),
                metadata,
                form_data.get('model'),
                compaction_models,
                system_prompt,
            )
            if context_summary:
                form_data['messages'] = add_or_update_system_message(
                    f'[CONVERSATION SUMMARY]\n{context_summary}',
                    form_data['messages'],
                    append=True,
                )
        except Exception:
            log.exception('Context compaction failed; continuing with full chat history')

    # Process messages with structured output items into clean LLM messages
    for message in form_data.get('messages', []):
        output = message.get('output')
        # reasoning_details can be model/provider-bound, so only replay them
        # for output produced by the same model.
        if message.get('role') == 'assistant' and message.get('model') != model['id'] and isinstance(output, list):
            message['output'] = strip_reasoning_details(output)

    form_data['messages'] = process_messages_with_output(
        form_data.get('messages', []),
        reasoning_format=get_reasoning_format(model),
    )

    # Chat Controls/User Settings system prompt
    system_message = get_system_message(form_data.get('messages', []))
    if system_message:
        try:
            form_data = await apply_system_prompt_to_body(
                system_message.get('content'), form_data, metadata, user, replace=True
            )  # Required to handle system prompt variables
        except Exception:
            pass

    form_data = await convert_url_images_to_base64(form_data, user=user)

    event_emitter = await get_event_emitter(metadata)

    extra_params = {
        '__event_emitter__': event_emitter,
        '__user__': user.model_dump() if isinstance(user, UserModel) else {},
        '__metadata__': metadata,
        '__request__': request,
        '__model__': model,
        '__chat_id__': metadata.get('chat_id'),
        '__message_id__': metadata.get('message_id'),
    }

    # Folder "Project" handling: chats inside a folder inherit its system prompt.
    chat_id = metadata.get('chat_id', None)
    folder_id = None
    if user and is_saved_chat_id(chat_id):
        folder_id = await Chats.get_chat_folder_id(chat_id, user.id)

    # Fallback: use folder_id from metadata (temporary chats have no DB record)
    if not folder_id:
        folder_id = metadata.get('folder_id', None)

    if folder_id and user:
        folder = await Folders.get_folder_by_id(folder_id)
        if folder and user.role != 'admin' and not await has_folder_access(user.id, folder, 'read', db=None):
            folder = None

        if folder and folder.data and 'system_prompt' in folder.data:
            form_data = await apply_system_prompt_to_body(folder.data['system_prompt'], form_data, metadata, user)

    variables = form_data.pop('variables', None)

    features = form_data.pop('features', None) or {}
    if features:
        if 'image_generation' in features and features['image_generation']:
            # features is client-supplied; re-check the permission the direct
            # /images routes enforce.
            if getattr(user, 'role', None) == 'admin' or await has_permission(
                getattr(user, 'id', ''),
                'features.image_generation',
                await Config.get('user.permissions'),
            ):
                form_data = await chat_image_generation_handler(request, form_data, extra_params, user)

    files = form_data.pop('files', None)
    form_data.pop('folder_id', None)
    if files:
        # Remove duplicate files based on their content
        files = list({json.dumps(f, sort_keys=True): f for f in files}.values())

    metadata.update(
        {
            'model_id': form_data.get('model'),
            'files': files,
            'features': features,
        }
    )
    form_data['metadata'] = metadata

    system_message = get_system_message(form_data['messages'])
    system_content = get_content_from_message(system_message) if system_message else ''
    resolved_model_system_prompt = await resolve_system_prompt(
        model_system_prompt,
        metadata,
        user,
    )
    if resolved_model_system_prompt:
        system_content = (
            f'{resolved_model_system_prompt}\n{system_content}' if system_content else resolved_model_system_prompt
        )
    metadata['system_prompt'] = system_content or None
    metadata['user_prompt'] = get_last_user_message(form_data['messages'])
    metadata['sources'] = []

    form_data = normalize_messages_for_model(form_data)
    return form_data, metadata, []



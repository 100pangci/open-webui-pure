from __future__ import annotations

import collections.abc
import hashlib
import logging
import re
import threading
import time
from datetime import timedelta

import aiohttp
from open_webui.env import CHAT_STREAM_RESPONSE_CHUNK_MAX_BUFFER_SIZE
from open_webui.utils.json_codec import JSONCodec

log = logging.getLogger(__name__)
SURROGATE_RE = re.compile('[\ud800-\udfff]')


def deep_update(d, u):
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = deep_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def merge_model_params(base: dict, override: dict) -> dict:
    params = {**base, **override}
    base_custom = base.get('custom_params')
    override_custom = override.get('custom_params')
    if isinstance(base_custom, dict) and (override_custom is None or isinstance(override_custom, dict)):
        params['custom_params'] = {**base_custom, **(override_custom or {})}
    return params


def get_response_error_detail(response: object) -> str:
    status_code = getattr(response, 'status_code', None)
    fallback = f'Provider returned HTTP {status_code}' if status_code else 'Provider returned an error'

    try:
        body = response.body
        if not isinstance(body, str):
            body = body.decode('utf-8', 'replace')
        detail = JSONCodec.loads(body)
    except Exception:
        return fallback

    while isinstance(detail, dict):
        next_detail = None
        for key in ('error', 'message', 'detail'):
            if key in detail:
                next_detail = detail[key]
                break
        if next_detail is None:
            return str(detail)
        detail = next_detail

    return detail if isinstance(detail, str) else str(detail)


def get_message_list(messages_map, message_id):
    """
    Reconstructs a list of messages in order up to the specified message_id.

    :param message_id: ID of the message to reconstruct the chain
    :param messages: Message history dict containing all messages
    :return: List of ordered messages starting from the root to the given message
    """

    # Handle case where messages is None
    if not messages_map:
        return []  # Return empty list instead of None to prevent iteration errors

    # Find the message by its id
    current_message = messages_map.get(message_id)

    if not current_message:
        return []  # Return empty list instead of None to prevent iteration errors

    # Reconstruct the chain by following the parentId links
    message_list = []
    visited_message_ids = set()

    # Track the map keys, not the messages' own 'id' field: a message may omit it
    while current_message and message_id not in visited_message_ids:
        visited_message_ids.add(message_id)
        message_list.append(current_message)

        message_id = current_message.get('parentId')
        current_message = messages_map.get(message_id) if message_id else None

    message_list.reverse()
    return message_list


def get_messages_content(messages: list[dict]) -> str:
    return '\n'.join([f'{message["role"].upper()}: {get_content_from_message(message)}' for message in messages])


def get_last_user_message_item(messages: list[dict]) -> dict | None:
    for message in reversed(messages):
        if message['role'] == 'user':
            return message
    return None


def get_content_from_message(message: dict) -> str | None:
    content = message.get('content')
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'text':
                return item.get('text')
    elif content:
        return content

    output_text = get_output_text(message.get('output'))
    return output_text or (content if isinstance(content, str) else None)


def get_output_text(output: list | None) -> str:
    if not isinstance(output, list):
        return ''

    texts = []
    for item in output:
        if not isinstance(item, dict) or item.get('type') != 'message':
            continue

        parts = item.get('content') or []
        if not isinstance(parts, list):
            continue

        text = ''.join(
            str(part.get('text')) for part in parts if isinstance(part, dict) and part.get('text') is not None
        )
        # isspace() avoids the full-string copy strip() would make
        if text and not text.isspace():
            texts.append(text)

    return '\n'.join(texts)


def get_reasoning_details(payload: dict):
    if not isinstance(payload, dict):
        return None

    provider_fields = payload.get('provider_specific_fields') or {}
    provider_details = provider_fields.get('reasoning_details') if isinstance(provider_fields, dict) else None
    return payload.get('reasoning_details') or provider_details


def convert_output_to_messages(
    output: list,
    raw: bool = False,
    reasoning_format: str | None = None,
) -> list[dict]:
    """
    Convert OR-aligned output items to OpenAI Chat Completion-format messages.

    Args:
        output: List of OR-aligned output items (Responses API format).
        raw: If True, include reasoning details for LLM re-processing follow-ups.
        reasoning_format: How to include reasoning blocks in the output:
            - None: skip reasoning (default, safe for strict providers).
            - 'thinking': set as ``thinking`` top-level field.
            - 'think_tags': wrap in ``<think>`` tags inside content.
            - 'reasoning_content': set as ``reasoning_content`` top-level field
              (for llama.cpp, which routes it via the chat template).
    """
    if not output or not isinstance(output, list):
        return []

    messages = []
    pending_content = []
    pending_reasoning = []  # Only populated for top-level structured reasoning fields.
    pending_reasoning_details = []

    def flush_pending():
        nonlocal pending_content, pending_reasoning, pending_reasoning_details
        if not pending_content and not pending_reasoning and not pending_reasoning_details:
            return

        message = {
            'role': 'assistant',
            'content': '\n'.join(pending_content) if pending_content else '',
        }

        if pending_reasoning:
            if reasoning_format == 'thinking':
                message['thinking'] = '\n'.join(pending_reasoning)
            else:
                message['reasoning_content'] = '\n'.join(pending_reasoning)

        if pending_reasoning_details:
            message['reasoning_details'] = pending_reasoning_details

        messages.append(message)
        pending_content = []
        pending_reasoning = []
        pending_reasoning_details = []

    for item in output:
        item_type = item.get('type', '')

        if item_type == 'message':
            # Extract text from output_text content parts
            text = ''
            for part in item.get('content', []):
                if part.get('type') == 'output_text':
                    text += part.get('text', '')
            if text:
                pending_content.append(text)

        elif item_type == 'reasoning':
            reasoning_details = item.get('reasoning_details') if raw else None
            if reasoning_details:
                reasoning_details = reasoning_details if isinstance(reasoning_details, list) else [reasoning_details]
                reasoning_details = [
                    detail
                    for detail in reasoning_details
                    if isinstance(detail, dict)
                    and (detail.get('format') != 'anthropic-claude-v1' or detail.get('signature'))
                ]
            if not reasoning_format and not reasoning_details:
                continue

            reasoning_text = ''
            source_list = item.get('summary', []) or item.get('content', [])
            for part in source_list:
                if part.get('type') == 'output_text':
                    reasoning_text += part.get('text', '')
                elif 'text' in part:
                    reasoning_text += part.get('text', '')

            if reasoning_text:
                if reasoning_format == 'think_tags':
                    start_tag = item.get('start_tag', '<think>')
                    end_tag = item.get('end_tag', '</think>')
                    pending_content.append(f'{start_tag}{reasoning_text}{end_tag}')
                elif reasoning_format in {'thinking', 'reasoning_content'}:
                    pending_reasoning.append(reasoning_text)

            if reasoning_details:
                pending_reasoning_details.extend(reasoning_details)

        elif item_type.startswith('open_webui:'):
            # Skip extension types that are no longer supported.
            pass

    flush_pending()
    return messages


def get_last_user_message(messages: list[dict]) -> str | None:
    message = get_last_user_message_item(messages)
    if message is None:
        return None
    return get_content_from_message(message)


def get_last_assistant_message(messages: list[dict]) -> str | None:
    for message in reversed(messages):
        if message['role'] == 'assistant':
            return get_content_from_message(message)
    return None


def get_system_message(messages: list[dict]) -> dict | None:
    for message in messages:
        if message['role'] == 'system':
            return message
    return None


def merge_system_messages(messages: list[dict]) -> list[dict]:
    """
    Merge all system messages into one at position 0.

    Some chat templates (e.g. Qwen) require exactly one system
    message at the start.  Multiple pipeline stages may each
    insert their own system message; this function consolidates
    them.
    """
    system_contents: list[str] = []
    other_messages: list[dict] = []

    for message in messages:
        if message.get('role') == 'system':
            content = get_content_from_message(message)
            if content:
                system_contents.append(content)
        else:
            other_messages.append(message)

    if not system_contents:
        return other_messages

    merged = {'role': 'system', 'content': '\n'.join(system_contents)}
    return [merged, *other_messages]


def update_message_content(message: dict, content: str, append: bool = True) -> dict:
    if isinstance(message['content'], list):
        for item in message['content']:
            if item['type'] == 'text':
                if append:
                    item['text'] = f'{item["text"]}\n{content}'
                else:
                    item['text'] = f'{content}\n{item["text"]}'
    else:
        if append:
            message['content'] = f'{message["content"]}\n{content}'
        else:
            message['content'] = f'{content}\n{message["content"]}'
    return message


def replace_system_message_content(content: str, messages: list[dict]) -> dict:
    for message in messages:
        if message['role'] == 'system':
            message['content'] = content
            break
    return messages


def add_or_update_system_message(content: str, messages: list[dict], append: bool = False):
    """
    Adds a new system message at the beginning of the messages list
    or updates the existing system message at the beginning.

    :param msg: The message to be added or appended.
    :param messages: The list of message dictionaries.
    :return: The updated list of message dictionaries.
    """

    if messages and messages[0].get('role') == 'system':
        messages[0] = update_message_content(messages[0], content, append)
    else:
        # Insert at the beginning
        messages.insert(0, {'role': 'system', 'content': content})

    return messages


def strip_empty_content_blocks(messages: list[dict]) -> list[dict]:
    """
    Remove empty text content blocks from multimodal message content arrays.

    Providers like Gemini and Claude reject messages where a text block has
    an empty string.  This can happen when a user sends only file/image
    attachments without typing any text.
    """
    for message in messages:
        content = message.get('content')
        if isinstance(content, list):
            cleaned = [
                block
                for block in content
                if not (isinstance(block, dict) and block.get('type') == 'text' and not block.get('text', '').strip())
            ]
            if cleaned:
                message['content'] = cleaned
    return messages


def get_gravatar_url(email):
    # Trim leading and trailing whitespace from
    # an email address and force all characters
    # to lower case
    address = str(email).strip().lower()

    # Create a SHA256 hash of the final string
    hash_object = hashlib.sha256(address.encode())
    hash_hex = hash_object.hexdigest()

    # Grab the actual image URL
    return f'https://www.gravatar.com/avatar/{hash_hex}?d=mp'


# Give us each day the data we require, and forgive us our
# technical debts as we forgive those who commit upstream.
# Lead the bits not into corruption but deliver them from
# entropy, for the checksum and the glory are forever.
def validate_email_format(email: str) -> bool:
    if email.endswith('@localhost'):
        return True

    return bool(re.match(r'[^@]+@[^@]+\.[^@]+', email))


def json_text_variants(value: str) -> list[str]:
    """Both spellings ``value`` can take inside a serialized JSON column, unquoted.

    Encoders disagree on non-ASCII — stdlib escapes it to ``\\uXXXX``, orjson writes it
    raw — so a LIKE against the stored text has to accept either. ASCII collapses to one.
    """
    raw = JSONCodec.dumps(value, ensure_ascii=False)[1:-1]
    escaped = JSONCodec.dumps(value, ensure_ascii=True)[1:-1]
    return [raw] if raw == escaped else [raw, escaped]


def sanitize_text_for_db(text: str) -> str:
    """Remove null bytes and invalid UTF-8 surrogates from text for PostgreSQL storage."""
    if not isinstance(text, str):
        return text
    # Fast path: skip work when there are no null bytes or surrogate code points.
    if '\x00' not in text and not SURROGATE_RE.search(text):
        return text
    return SURROGATE_RE.sub('', text.replace('\x00', ''))


def _strip_null_bytes_deep(obj):
    """Inner recursive walk — only called when null bytes are known to be present."""
    if isinstance(obj, str):
        return sanitize_text_for_db(obj)
    elif isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            cleaned[sanitize_text_for_db(k) if isinstance(k, str) else k] = _strip_null_bytes_deep(v)
        return cleaned
    elif isinstance(obj, list):
        return [_strip_null_bytes_deep(v) for v in obj]
    return obj


def sanitize_data_for_db(obj):
    """Recursively sanitize all strings in a data structure for database storage.

    Performs a fast pre-check: serializes the structure once and scans for
    null bytes or invalid UTF-8 surrogates. If none are found, the
    original object is returned immediately, skipping the expensive
    recursive walk.
    """
    if isinstance(obj, str):
        return sanitize_text_for_db(obj)
    # Fast path: check for null bytes and surrogate code points in the serialized form.
    # json.dumps is implemented in C and much faster than a Python-level
    # recursive walk over every leaf string.
    try:
        serialized = JSONCodec.dumps(obj, ensure_ascii=False)
        if '\\u0000' not in serialized:
            serialized.encode('utf-8')
            return obj
    except (TypeError, ValueError, UnicodeEncodeError):
        pass
    return _strip_null_bytes_deep(obj)


def sanitize_metadata(metadata: dict) -> dict:
    """
    Return a JSON-safe copy of a metadata dict for database storage.

    The middleware metadata accumulates non-serializable Python objects
    (e.g. callable tool functions, MCP client instances) that cause
    PostgreSQL JSON inserts to fail.  This helper strips those out while
    preserving the primitive data needed for file-to-chat linking.
    """
    if not isinstance(metadata, dict):
        return metadata

    def _sanitize(obj):
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items() if not callable(v) and _is_serializable(v)}
        if isinstance(obj, list):
            return [_sanitize(v) for v in obj if not callable(v) and _is_serializable(v)]
        if callable(obj):
            return None
        # Last resort: try to see if it's serializable
        try:
            JSONCodec.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return None

    def _is_serializable(obj):
        """Quick check whether a value can survive JSON serialization."""
        if isinstance(obj, (str, int, float, bool, type(None), dict, list)):
            return True
        try:
            JSONCodec.dumps(obj)
            return True
        except (TypeError, ValueError):
            return False

    return _sanitize(metadata)


def parse_duration(duration: str) -> timedelta | None:
    if duration == '-1' or duration == '0':
        return None

    # Regular expression to find number and unit pairs
    pattern = r'(-?\d+(\.\d+)?)(ms|s|m|h|d|w)'
    matches = re.findall(pattern, duration)

    if not matches:
        raise ValueError('Invalid duration string')

    total_duration = timedelta()

    for number, _, unit in matches:
        number = float(number)
        if unit == 'ms':
            total_duration += timedelta(milliseconds=number)
        elif unit == 's':
            total_duration += timedelta(seconds=number)
        elif unit == 'm':
            total_duration += timedelta(minutes=number)
        elif unit == 'h':
            total_duration += timedelta(hours=number)
        elif unit == 'd':
            total_duration += timedelta(days=number)
        elif unit == 'w':
            total_duration += timedelta(weeks=number)

    return total_duration


def convert_logit_bias_input_to_json(logit_bias_input) -> str | None:
    if not logit_bias_input:
        return None

    if isinstance(logit_bias_input, dict):
        return JSONCodec.dumps(logit_bias_input)

    logit_bias_pairs = logit_bias_input.split(',')
    logit_bias_json = {}
    for pair in logit_bias_pairs:
        token, bias = pair.split(':')
        token = str(token.strip())
        bias = int(bias.strip())
        bias = 100 if bias > 100 else -100 if bias < -100 else bias
        logit_bias_json[token] = bias
    return JSONCodec.dumps(logit_bias_json)


def freeze(value):
    """
    Freeze a value to make it hashable.
    """
    if isinstance(value, dict):
        return frozenset((k, freeze(v)) for k, v in value.items())
    elif isinstance(value, list):
        return tuple(freeze(v) for v in value)
    return value


def throttle(interval: float = 10.0):
    """
    Decorator to prevent a function from being called more than once within a specified duration.
    If the function is called again within the duration, it returns None. To avoid returning
    different types, the return type of the function should be T | None.

    :param interval: Duration in seconds to wait before allowing the function to be called again.
                     Zero or negative disables throttling.
    """

    def decorator(func):
        if interval <= 0:
            return func

        last_calls = {}
        lock = threading.Lock()

        async def wrapper(*args, **kwargs):
            key = (args, freeze(kwargs))
            now = time.time()
            if now - last_calls.get(key, 0) < interval:
                return None
            with lock:
                if now - last_calls.get(key, 0) < interval:
                    return None
                last_calls[key] = now
            return await func(*args, **kwargs)

        return wrapper

    return decorator


async def cleanup_response(
    response: aiohttp.ClientResponse | None,
    session: aiohttp.ClientSession | None,
):
    if response:
        if not response.closed:
            # aiohttp 3.9+ made ClientResponse.close() synchronous (returns None).
            # Older versions returned a coroutine.  Handle both gracefully.
            result = response.close()
            if result is not None:
                await result
    if session:
        if not session.closed:
            result = session.close()
            if result is not None:
                await result


async def stream_wrapper(response, session, content_handler=None):
    """
    Wrap a stream to ensure cleanup happens even if streaming is interrupted.
    This is more reliable than BackgroundTask which may not run if client disconnects.
    """
    try:
        stream = content_handler(response.content) if content_handler else response.content
        async for chunk in stream:
            yield chunk
    finally:
        await cleanup_response(response, session)


def stream_chunks_handler(stream: aiohttp.StreamReader):
    """
    Assemble lines from raw chunks, so a line over aiohttp's reader limit no longer aborts the stream.
    When CHAT_STREAM_RESPONSE_CHUNK_MAX_BUFFER_SIZE is set, a line exceeding it is dropped.

    :param stream: The stream reader to handle.
    :return: An async generator that yields the stream one line at a time.
    """

    max_buffer_size = CHAT_STREAM_RESPONSE_CHUNK_MAX_BUFFER_SIZE
    if max_buffer_size is None or max_buffer_size <= 0:
        max_buffer_size = float('inf')  # unset: no line is too long

    async def yield_safe_stream_chunks():
        buffer = bytearray()  # bytearray, not bytes: `+=` on bytes reallocates, quadratic on long lines
        dropping_line_tail = False

        async for data, _ in stream.iter_chunks():
            if not data:
                continue

            buffer += data

            # Only split once a line completed: splitting every chunk re-copies the buffer, quadratic
            if b'\n' in data:
                *lines, rest = bytes(buffer).split(b'\n')
                buffer = bytearray(rest)

                for line in lines:
                    if dropping_line_tail:
                        dropping_line_tail = False
                    elif len(line) > max_buffer_size:
                        log.info('Dropped line over max buffer size: %s bytes', len(line))
                    else:
                        yield line + b'\n'

            # Oversized line still arriving: drop it instead of buffering the rest
            if len(buffer) > max_buffer_size:
                if not dropping_line_tail:
                    log.info('Dropping line over max buffer size, buffered so far: %s bytes', len(buffer))
                dropping_line_tail = True
                buffer.clear()

        if buffer and not dropping_line_tail:
            yield bytes(buffer)

    return yield_safe_stream_chunks()

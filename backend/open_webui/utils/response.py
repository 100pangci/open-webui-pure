import time
from numbers import Number
from uuid import uuid4

from open_webui.utils.json_codec import JSONCodec

USAGE_TOKEN_KEYS = {'input_tokens', 'output_tokens', 'total_tokens'}
USAGE_COST_KEYS = {'cost', 'total_cost', 'input_cost', 'output_cost', 'prompt_cost', 'completion_cost'}
USAGE_SUMMABLE_KEYS = USAGE_TOKEN_KEYS | USAGE_COST_KEYS
USAGE_DETAIL_KEYS = {
    'prompt_tokens_details',
    'completion_tokens_details',
    'input_tokens_details',
    'output_tokens_details',
}


def normalize_usage(usage: dict | None) -> dict:
    if not usage:
        return {}

    input_tokens = usage.get('input_tokens') or usage.get('prompt_tokens') or 0
    output_tokens = usage.get('output_tokens') or usage.get('completion_tokens') or 0
    total_tokens = usage.get('total_tokens') or input_tokens + output_tokens

    result = dict(usage)
    result['input_tokens'] = int(input_tokens)
    result['output_tokens'] = int(output_tokens)
    result['total_tokens'] = int(total_tokens)
    return result


def _is_numeric_usage_value(value) -> bool:
    return isinstance(value, Number) and not isinstance(value, bool)


def _merge_numeric_usage_map(current: dict | None, incoming: dict | None) -> dict:
    current = current or {}
    incoming = incoming or {}
    result = {**current, **incoming}

    for key in set(current) | set(incoming):
        current_value = current.get(key, 0)
        incoming_value = incoming.get(key, 0)
        if isinstance(current_value, dict) or isinstance(incoming_value, dict):
            result[key] = _merge_numeric_usage_map(
                current_value if isinstance(current_value, dict) else {},
                incoming_value if isinstance(incoming_value, dict) else {},
            )
        elif _is_numeric_usage_value(current_value) or _is_numeric_usage_value(incoming_value):
            result[key] = (current_value if _is_numeric_usage_value(current_value) else 0) + (
                incoming_value if _is_numeric_usage_value(incoming_value) else 0
            )

    return result


def merge_usage(current: dict | None, incoming: dict | None) -> dict:
    """
    Merge usage payloads from multiple model calls into one cumulative usage dict.

    Canonical token fields are additive; provider aliases keep the latest value.
    """
    current_usage = normalize_usage(current or {}) if current else {}
    incoming_usage = normalize_usage(incoming or {}) if incoming else {}

    if not incoming_usage:
        return current_usage
    if not current_usage:
        return incoming_usage

    result = {**current_usage, **incoming_usage}

    for key in USAGE_SUMMABLE_KEYS:
        if key in current_usage or key in incoming_usage:
            current_value = current_usage.get(key, 0)
            incoming_value = incoming_usage.get(key, 0)
            if _is_numeric_usage_value(current_value) or _is_numeric_usage_value(incoming_value):
                result[key] = (current_value if _is_numeric_usage_value(current_value) else 0) + (
                    incoming_value if _is_numeric_usage_value(incoming_value) else 0
                )

    for key in USAGE_DETAIL_KEYS:
        if isinstance(current_usage.get(key), dict) or isinstance(incoming_usage.get(key), dict):
            result[key] = _merge_numeric_usage_map(
                current_usage.get(key) if isinstance(current_usage.get(key), dict) else {},
                incoming_usage.get(key) if isinstance(incoming_usage.get(key), dict) else {},
            )

    # Aliases keep the latest call's size, which context compaction reads.
    for alias, canonical in (('prompt_tokens', 'input_tokens'), ('completion_tokens', 'output_tokens')):
        if canonical in incoming_usage:
            result[alias] = incoming_usage[canonical]

    return result


def convert_responses_usage_to_chat_completions(usage: dict | None) -> dict:
    result = normalize_usage(usage)
    for source, target in (('input_tokens', 'prompt_tokens'), ('output_tokens', 'completion_tokens')):
        for suffix in ('', '_details'):
            if source + suffix in result:
                result[target + suffix] = result[source + suffix]
    return result


def get_responses_finish_reason(response: dict, has_tool_calls: bool = False) -> str:
    if response.get('status') == 'incomplete':
        reason = (response.get('incomplete_details') or {}).get('reason')
        return 'content_filter' if reason == 'content_filter' else 'length'
    return 'tool_calls' if has_tool_calls else 'stop'


def _chat_completion_chunk_template(model: str, message_id: str | None = None) -> dict:
    return {
        'id': message_id if message_id else f'{model}-{str(uuid4())}',
        'object': 'chat.completion.chunk',
        'created': int(time.time()),
        'model': model,
        'choices': [{'index': 0, 'logprobs': None, 'finish_reason': None}],
    }


async def convert_responses_stream_to_chat_completions(body_iterator):
    """Convert line-framed Responses SSE after internal filters; pass other streams through."""
    completion_id = f'chatcmpl-{uuid4()}'
    created = int(time.time())
    model = ''
    tool_call_indexes = {}
    first = True
    is_responses_stream = False
    done = False
    async for line in body_iterator:
        text = line.decode('utf-8', 'replace') if isinstance(line, bytes) else line
        if text.startswith('event:') and (
            is_responses_stream or text.removeprefix('event:').strip().startswith('response.')
        ):
            continue
        if done and text.strip() == 'data: [DONE]':
            continue
        try:
            data = JSONCodec.loads(text.removeprefix('data:').strip()) if text.startswith('data:') else None
        except JSONCodec.JSONDecodeError:
            data = None
        event_type = data.get('type', '') if isinstance(data, dict) else ''
        if not event_type.startswith('response.') and not (event_type == 'error' and is_responses_stream):
            yield line
            continue

        is_responses_stream = True
        if event_type in ('response.failed', 'error'):
            error = data.get('response', {}).get('error') if event_type == 'response.failed' else data
            yield f'data: {JSONCodec.dumps({"error": error})}\n\n'
            done = True
            continue
        if event_type == 'response.created':
            response = data.get('response', {})
            completion_id = response.get('id') or completion_id
            created = response.get('created_at') or created
            model = response.get('model', '')
            continue

        delta = {}
        output_index = data.get('output_index')
        is_final = event_type in ('response.completed', 'response.incomplete')
        if event_type == 'response.output_text.delta':
            delta['content'] = data['delta']
        elif event_type in ('response.reasoning_text.delta', 'response.reasoning_summary_text.delta'):
            delta['reasoning_content'] = data['delta']
        elif event_type == 'response.refusal.delta':
            delta['refusal'] = data['delta']
        elif event_type == 'response.output_item.added' and data.get('item', {}).get('type') == 'function_call':
            item = data['item']
            tool_call_indexes[output_index] = len(tool_call_indexes)
            delta['tool_calls'] = [
                {
                    'index': tool_call_indexes[output_index],
                    'id': item.get('call_id', ''),
                    'type': 'function',
                    'function': {'name': item.get('name', ''), 'arguments': item.get('arguments', '')},
                }
            ]
        elif event_type == 'response.function_call_arguments.delta':
            delta['tool_calls'] = [
                {
                    'index': tool_call_indexes[output_index],
                    'function': {'arguments': data['delta']},
                }
            ]
        elif not is_final:
            continue

        chunk = _chat_completion_chunk_template(model, message_id=completion_id)
        chunk['created'] = created
        chunk['choices'][0].update(delta=delta, finish_reason=None)
        if first:
            delta['role'] = 'assistant'
            first = False
        if is_final:
            response = data.get('response', {})
            chunk['choices'][0]['finish_reason'] = get_responses_finish_reason(
                {**response, 'status': event_type.removeprefix('response.')}, bool(tool_call_indexes)
            )
            usage = convert_responses_usage_to_chat_completions(response.get('usage'))
            if usage:
                chunk['usage'] = usage
            done = True
        yield f'data: {JSONCodec.dumps(chunk)}\n\n'

    # Let the wrapped stream finish outlet filters and usage logging before clients disconnect.
    if done:
        yield 'data: [DONE]\n\n'

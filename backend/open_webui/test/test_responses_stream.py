import json

from open_webui.routers.openai import convert_responses_result, convert_to_responses_payload
from open_webui.utils.response import (
    convert_responses_stream_to_chat_completions,
    convert_responses_usage_to_chat_completions,
    get_responses_finish_reason,
)


async def stream(lines):
    for line in lines:
        yield line


def data(payload):
    return f'data: {json.dumps(payload)}\n\n'


async def collect(lines):
    return [chunk async for chunk in convert_responses_stream_to_chat_completions(stream(lines))]


def parse_chunks(chunks):
    return [json.loads(chunk.removeprefix('data:').strip()) for chunk in chunks if chunk.startswith('data: {')]


async def test_non_responses_stream_is_passed_through_unchanged():
    lines = [
        data({'id': 'chatcmpl-1', 'choices': [{'delta': {'content': 'hi'}}]}),
        'data: [DONE]\n\n',
    ]

    assert await collect(lines) == lines


async def test_error_before_responses_stream_is_passed_through_unchanged():
    lines = [data({'error': {'message': 'bad request'}})]

    assert await collect(lines) == lines


async def test_responses_stream_is_converted_to_chat_completion_chunks():
    chunks = await collect(
        [
            'event: response.created\n\n',
            data(
                {
                    'type': 'response.created',
                    'response': {'id': 'resp_1', 'created_at': 1700000000, 'model': 'gpt-x'},
                }
            ),
            data({'type': 'response.output_text.delta', 'output_index': 0, 'delta': 'Hello'}),
            data({'type': 'response.reasoning_text.delta', 'output_index': 0, 'delta': 'think'}),
            'event: response.output_item.added\n\n',
            data(
                {
                    'type': 'response.output_item.added',
                    'output_index': 1,
                    'item': {'type': 'function_call', 'call_id': 'call_1', 'name': 'f', 'arguments': ''},
                }
            ),
            data({'type': 'response.function_call_arguments.delta', 'output_index': 1, 'delta': '{"a":1}'}),
            data(
                {
                    'type': 'response.completed',
                    'response': {
                        'id': 'resp_1',
                        'model': 'gpt-x',
                        'status': 'completed',
                        'usage': {'input_tokens': 5, 'output_tokens': 3, 'total_tokens': 8},
                    },
                }
            ),
            'data: [DONE]\n\n',
        ]
    )

    assert chunks[-1] == 'data: [DONE]\n\n'
    parsed = parse_chunks(chunks)
    assert len(parsed) == 5

    assert parsed[0]['id'] == 'resp_1'
    assert parsed[0]['created'] == 1700000000
    assert parsed[0]['model'] == 'gpt-x'
    assert parsed[0]['choices'][0]['index'] == 0
    assert parsed[0]['choices'][0]['delta'] == {'content': 'Hello', 'role': 'assistant'}
    assert parsed[1]['choices'][0]['delta'] == {'reasoning_content': 'think'}
    assert parsed[2]['choices'][0]['delta']['tool_calls'] == [
        {
            'index': 0,
            'id': 'call_1',
            'type': 'function',
            'function': {'name': 'f', 'arguments': ''},
        }
    ]
    assert parsed[3]['choices'][0]['delta']['tool_calls'] == [{'index': 0, 'function': {'arguments': '{"a":1}'}}]
    assert parsed[4]['choices'][0]['finish_reason'] == 'tool_calls'
    assert parsed[4]['usage'] == {
        'input_tokens': 5,
        'output_tokens': 3,
        'total_tokens': 8,
        'prompt_tokens': 5,
        'completion_tokens': 3,
    }


async def test_incomplete_stream_keeps_usage_and_maps_finish_reason():
    chunks = parse_chunks(
        await collect(
            [
                data(
                    {
                        'type': 'response.incomplete',
                        'response': {
                            'status': 'incomplete',
                            'incomplete_details': {'reason': 'max_output_tokens'},
                            'usage': {'input_tokens': 2, 'output_tokens': 1},
                        },
                    }
                ),
            ]
        )
    )

    assert chunks[0]['choices'][0]['finish_reason'] == 'length'
    assert chunks[0]['usage']['prompt_tokens'] == 2
    assert chunks[0]['usage']['completion_tokens'] == 1


async def test_incomplete_content_filter_maps_to_content_filter():
    chunks = parse_chunks(
        await collect(
            [
                data(
                    {
                        'type': 'response.incomplete',
                        'response': {
                            'status': 'incomplete',
                            'incomplete_details': {'reason': 'content_filter'},
                        },
                    }
                ),
            ]
        )
    )

    assert chunks[0]['choices'][0]['finish_reason'] == 'content_filter'


async def test_failed_stream_yields_error_and_done():
    chunks = await collect(
        [
            data({'type': 'response.created', 'response': {'id': 'resp_1', 'model': 'gpt-x'}}),
            data({'type': 'response.failed', 'response': {'error': {'message': 'boom'}}}),
        ]
    )

    assert chunks == ['data: {"error": {"message": "boom"}}\n\n', 'data: [DONE]\n\n']


async def test_error_event_after_responses_stream_yields_error():
    chunks = await collect(
        [
            data({'type': 'response.created', 'response': {'id': 'resp_1', 'model': 'gpt-x'}}),
            data({'type': 'error', 'message': 'stream broke'}),
        ]
    )

    assert chunks[0] == 'data: {"error": {"type": "error", "message": "stream broke"}}\n\n'


def test_usage_conversion_aliases_token_counts():
    assert convert_responses_usage_to_chat_completions(
        {
            'input_tokens': 7,
            'output_tokens': 4,
            'total_tokens': 11,
            'input_tokens_details': {'cached_tokens': 2},
        }
    ) == {
        'input_tokens': 7,
        'output_tokens': 4,
        'total_tokens': 11,
        'input_tokens_details': {'cached_tokens': 2},
        'prompt_tokens': 7,
        'completion_tokens': 4,
        'prompt_tokens_details': {'cached_tokens': 2},
    }


def test_finish_reason_for_non_streaming_results():
    assert get_responses_finish_reason({}) == 'stop'
    assert get_responses_finish_reason({'status': 'completed'}) == 'stop'
    assert (
        get_responses_finish_reason({'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'}})
        == 'length'
    )
    assert (
        get_responses_finish_reason({'status': 'incomplete', 'incomplete_details': {'reason': 'content_filter'}})
        == 'content_filter'
    )


def test_convert_responses_result_keeps_refusal_created_and_usage():
    result = convert_responses_result(
        {
            'id': 'resp_1',
            'created_at': 1700000000,
            'model': 'gpt-x',
            'status': 'incomplete',
            'incomplete_details': {'reason': 'max_output_tokens'},
            'output': [
                {
                    'type': 'message',
                    'content': [
                        {'type': 'output_text', 'text': 'partial'},
                        {'type': 'refusal', 'refusal': 'cannot'},
                    ],
                }
            ],
            'usage': {'input_tokens': 5, 'output_tokens': 2, 'total_tokens': 7},
        }
    )

    assert result['id'] == 'resp_1'
    assert result['created'] == 1700000000
    assert result['object'] == 'chat.completion'
    assert result['choices'][0]['message'] == {
        'role': 'assistant',
        'content': 'partial',
        'refusal': 'cannot',
    }
    assert result['choices'][0]['finish_reason'] == 'length'
    assert result['usage'] == {
        'input_tokens': 5,
        'output_tokens': 2,
        'total_tokens': 7,
        'prompt_tokens': 5,
        'completion_tokens': 2,
    }


def test_convert_responses_result_without_usage():
    result = convert_responses_result({'id': 'resp_2', 'model': 'gpt-x', 'output': []})

    assert result['choices'][0]['finish_reason'] == 'stop'
    assert result['usage'] is None
    assert 'refusal' not in result['choices'][0]['message']


def test_system_message_becomes_a_developer_input_item():
    payload = convert_to_responses_payload(
        {
            'model': 'gpt-5',
            'messages': [
                {'role': 'system', 'content': 'Be brief'},
                {'role': 'user', 'content': 'Hello'},
            ],
        }
    )

    # Newer OpenAI models never prompt-cache top-level instructions, so the
    # system prompt ships as a developer message instead.
    assert 'instructions' not in payload
    assert payload['input'][0] == {
        'type': 'message',
        'role': 'developer',
        'content': [{'type': 'input_text', 'text': 'Be brief'}],
    }
    assert payload['input'][1]['role'] == 'user'


def test_system_message_with_text_parts_becomes_a_developer_input_item():
    payload = convert_to_responses_payload(
        {
            'model': 'gpt-5',
            'messages': [
                {'role': 'system', 'content': [{'type': 'text', 'text': 'Be brief'}]},
                {'role': 'user', 'content': 'Hello'},
            ],
        }
    )

    assert 'instructions' not in payload
    assert payload['input'][0]['role'] == 'developer'
    assert payload['input'][0]['content'] == [{'type': 'input_text', 'text': 'Be brief'}]


def test_encrypted_reasoning_is_replayed_as_reasoning_items():
    from open_webui.utils.misc import convert_output_to_messages

    output = [
        {
            'type': 'reasoning',
            'id': 'rs_1',
            'summary': [{'type': 'output_text', 'text': 'thinking'}],
            'encrypted_content': 'gAAAA',
        },
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Answer'}]},
    ]

    messages = convert_output_to_messages(output, raw=True, reasoning_format='reasoning')

    assert messages[0]['content'] == 'Answer'
    assert messages[0]['reasoning'] == 'thinking'
    # The encrypted item goes back whole; providers reject a stripped one.
    assert messages[0]['reasoning_items'] == [output[0]]


def test_reasoning_items_are_dropped_when_not_raw():
    from open_webui.utils.misc import convert_output_to_messages

    output = [{'type': 'reasoning', 'summary': [], 'encrypted_content': 'gAAAA'}]

    assert convert_output_to_messages(output, raw=False, reasoning_format='reasoning') == []


def test_reasoning_items_go_back_before_the_assistant_message():
    payload = convert_to_responses_payload(
        {
            'model': 'gpt-5',
            'messages': [
                {'role': 'user', 'content': 'Hi'},
                {
                    'role': 'assistant',
                    'content': 'Answer',
                    'reasoning_items': [
                        {
                            'type': 'reasoning',
                            'id': 'rs_1',
                            'summary': [],
                            'encrypted_content': 'gAAAA',
                            'status': 'completed',
                        }
                    ],
                },
            ],
        }
    )

    assert payload['input'][1] == {'type': 'reasoning', 'id': 'rs_1', 'summary': [], 'encrypted_content': 'gAAAA'}
    assert payload['input'][2]['role'] == 'assistant'


def test_stripped_reasoning_loses_encrypted_content():
    from open_webui.utils.middleware import strip_reasoning_details

    output = [
        {'type': 'reasoning', 'id': 'rs_1', 'encrypted_content': 'gAAAA', 'reasoning_details': [{'text': 'x'}]},
        'not-a-dict',
    ]

    assert strip_reasoning_details(output) == [{'type': 'reasoning', 'id': 'rs_1'}, 'not-a-dict']

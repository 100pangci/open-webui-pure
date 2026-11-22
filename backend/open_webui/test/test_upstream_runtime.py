from types import SimpleNamespace
from uuid import uuid4

import pytest

from open_webui.utils import audit, chat_variables, context_compaction, middleware, misc
from open_webui.utils import chat as chat_utils


def test_sanitize_data_for_db_does_not_serialize_clean_chat_payload(monkeypatch):
    payload = {'history': {'messages': {str(index): {'content': 'ascii' * 100} for index in range(20)}}}

    def fail_if_serialized(*args, **kwargs):
        pytest.fail('clean chat payload should not be serialized during sanitization')

    monkeypatch.setattr(misc.JSONCodec, 'dumps', fail_if_serialized)
    assert misc.sanitize_data_for_db(payload) is payload

    unsafe = {'history': {'messages': {'1': {'content': 'bad\x00text\ud800'}}}}
    assert misc.sanitize_data_for_db(unsafe) == {'history': {'messages': {'1': {'content': 'badtext'}}}}


def test_audit_redacts_api_secrets_and_truncated_values():
    body = '{"api_key":"sk-secret","access_token":["Bearer token","refresh"],"password":"pw","visible":"ok"}'
    redacted = audit.redact_secrets(body)

    # The key and its value separator are preserved; only the value is masked.
    assert '"api_key":"********"' in redacted
    assert '"access_token":"********"' in redacted
    assert '"password":"********"' in redacted
    assert '"visible":"ok"' in redacted
    for secret in ('sk-secret', 'Bearer token', 'refresh', '"pw"'):
        assert secret not in redacted

    # A value cut off by the size limit has no closing quote and is masked to the end.
    assert audit.redact_secrets('{"client_secret":"cut off') == '{"client_secret":"********"'


async def test_context_compaction_does_not_add_a_1000_token_summary_limit(monkeypatch):
    captured = {}

    async def fake_get_many(*keys):
        return {'task.model.params': {}, 'chat.context_compaction.model': None}

    async def fake_prompt_template(prompt, user):
        return prompt

    def fake_apply_params(payload, model, params):
        captured['params'] = params
        return payload

    async def fake_generate_chat_completion(request, form_data, user):
        return {'choices': [{'message': {'content': 'summary'}}]}

    monkeypatch.setattr(context_compaction.Config, 'get_many', fake_get_many)
    monkeypatch.setattr(context_compaction, 'prompt_template', fake_prompt_template)
    monkeypatch.setattr(context_compaction, 'apply_params_to_form_data', fake_apply_params)
    monkeypatch.setattr(chat_utils, 'generate_chat_completion', fake_generate_chat_completion)

    request = SimpleNamespace(state=SimpleNamespace(metadata={}))
    summary = await context_compaction._generate_summary(
        request,
        SimpleNamespace(),
        'model',
        {'model': {'info': {'params': {'max_tokens': 1000}}}},
        [],
        [],
        None,
        '',
    )

    assert summary == 'summary'
    assert captured['params'] == {}


async def test_background_tasks_stop_when_user_is_no_longer_verified(monkeypatch):
    async def user_is_missing(user_id):
        assert user_id == 'deleted-user'
        return None

    async def fail_if_chat_is_loaded(*args, **kwargs):
        pytest.fail('background work must stop before loading chat history')

    monkeypatch.setattr(middleware, 'get_verified_user_by_id', user_is_missing)
    monkeypatch.setattr(middleware.Chats, 'get_messages_map_by_chat_id', fail_if_chat_is_loaded)

    await middleware.background_tasks_handler(
        {
            'request': SimpleNamespace(),
            'form_data': {},
            'user': SimpleNamespace(id='deleted-user'),
            'metadata': {'chat_id': str(uuid4()), 'message_id': str(uuid4())},
            'tasks': {},
            'event_emitter': None,
        }
    )


def test_model_settings_depth_validation_walks_dict_values():
    nested = {}
    current = nested
    for _ in range(chat_variables.MAX_JSON_VALUE_DEPTH):
        child = {}
        current['nested'] = child
        current = child

    assert chat_variables.is_nested_too_deep(nested)
    assert not chat_variables.is_nested_too_deep({'nested': [{'value': 1}]})


async def test_manual_compaction_skips_empty_assistant_placeholder(monkeypatch):
    messages = {
        'user-1': {'id': 'user-1', 'role': 'user', 'content': 'First question'},
        'assistant-1': {
            'id': 'assistant-1',
            'role': 'assistant',
            'content': 'First answer',
            'parentId': 'user-1',
        },
        'user-2': {
            'id': 'user-2',
            'role': 'user',
            'content': 'Second question',
            'parentId': 'assistant-1',
        },
        'assistant-empty': {
            'id': 'assistant-empty',
            'role': 'assistant',
            'content': '',
            'output': [],
            'parentId': 'user-2',
        },
    }
    saved = {}

    async def fake_load_config():
        return {'enable': True, 'prompt_template': ''}

    async def fake_get_messages_map(*args, **kwargs):
        return messages

    async def fake_generate_summary(*args, **kwargs):
        return 'summary'

    async def fake_save_summary(chat_id, message_id, data, **kwargs):
        saved['chat_id'] = chat_id
        saved['message_id'] = message_id
        saved['data'] = data

    monkeypatch.setattr(context_compaction, '_load_config', fake_load_config)
    monkeypatch.setattr(context_compaction.Chats, 'get_messages_map_by_chat_id', fake_get_messages_map)
    monkeypatch.setattr(context_compaction, '_generate_summary', fake_generate_summary)
    monkeypatch.setattr(context_compaction.Chats, 'upsert_message_to_chat_by_id_and_message_id', fake_save_summary)

    result = await context_compaction.compact_chat_branch(
        SimpleNamespace(),
        SimpleNamespace(id='user'),
        SimpleNamespace(id='chat', chat={'history': {'currentId': 'assistant-empty'}}),
        'model',
        {},
    )

    assert result['compacted'] is True
    assert saved['chat_id'] == 'chat'
    assert saved['message_id'] == 'user-2'
    assert saved['data'] == {'contextSummary': 'summary'}

import re
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event, select

from open_webui.internal.db import (
    Base,
    JSONCodec,
    JSONField,
    async_engine,
    dumps_json_for_db,
    engine,
    get_async_db,
    strip_unstorable_json,
)
from open_webui.models.access_grants import AccessGrant
from open_webui.models.chat_messages import ChatMessage, ChatMessages
from open_webui.models.chats import Chat, Chats
from open_webui.models.config import Config
from open_webui.models.groups import GroupForm
from open_webui.models.models import ModelForm
from open_webui.models.prompt_history import PromptHistories, PromptHistory
from open_webui.models.tags import Tag, Tags
from open_webui.models.users import User, Users
from open_webui.utils.chat_variables import MAX_JSON_VALUE_DEPTH


@pytest.fixture(scope='module', autouse=True)
def create_test_tables():
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Chat.__table__,
            ChatMessage.__table__,
            AccessGrant.__table__,
            User.__table__,
            Tag.__table__,
            Config.__table__,
            PromptHistory.__table__,
        ],
    )


def _unique(prefix: str) -> str:
    return f'{prefix}-{uuid.uuid4().hex}'


async def _add_chat(**overrides) -> Chat:
    values = {
        'id': _unique('chat'),
        'user_id': _unique('user'),
        'title': 'Test chat',
        'chat': {},
        'created_at': 10,
        'updated_at': 20,
        'last_read_at': 10,
    }
    values.update(overrides)
    async with get_async_db() as db:
        row = Chat(**values)
        db.add(row)
        await db.commit()
        return row


@pytest.mark.asyncio
async def test_stale_history_merge_repairs_current_id():
    chat_id = _unique('chat')
    user_id = _unique('user')
    existing_history = {
        'currentId': 'assistant-latest',
        'messages': {
            'user-root': {
                'id': 'user-root',
                'role': 'user',
                'parentId': None,
                'childrenIds': ['assistant-root'],
                'timestamp': 1,
            },
            'assistant-root': {
                'id': 'assistant-root',
                'role': 'assistant',
                'parentId': 'user-root',
                'childrenIds': ['user-latest'],
                'timestamp': 2,
            },
            'user-latest': {
                'id': 'user-latest',
                'role': 'user',
                'parentId': 'assistant-root',
                'childrenIds': ['assistant-latest'],
                'timestamp': 3,
            },
            'assistant-latest': {
                'id': 'assistant-latest',
                'role': 'assistant',
                'parentId': 'user-latest',
                'childrenIds': [],
                'timestamp': 4,
            },
        },
    }
    stale_history = {
        'currentId': 'assistant-root',
        'messages': {
            'user-root': {
                'id': 'user-root',
                'role': 'user',
                'parentId': None,
                'childrenIds': ['assistant-root'],
                'timestamp': 1,
            },
            'assistant-root': {
                'id': 'assistant-root',
                'role': 'assistant',
                'parentId': 'user-root',
                'childrenIds': [],
                'timestamp': 2,
            },
        },
    }
    await _add_chat(
        id=chat_id,
        user_id=user_id,
        chat={'title': 'History', 'history': existing_history},
        current_message_id='assistant-latest',
    )

    async with get_async_db() as db:
        updated = await Chats.update_chat_by_id(
            chat_id,
            {'history': stale_history},
            db=db,
            touch=False,
        )

    assert updated is not None
    assert updated.chat['history']['currentId'] == 'assistant-latest'
    assert updated.current_message_id == 'assistant-latest'


@pytest.mark.asyncio
async def test_chat_access_and_read_state_use_narrow_columns():
    owner_id = _unique('user')
    row = await _add_chat(user_id=owner_id)
    statements = []

    def capture_sql(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(async_engine.sync_engine, 'before_cursor_execute', capture_sql)
    try:
        assert await Chats.has_chat_access(
            row.id,
            SimpleNamespace(id=owner_id, role='user'),
        )
        read_result = await Chats.update_chat_last_read_at_by_id(row.id, owner_id)
        unread_row = await Chats.mark_chat_unread_by_id(row.id, owner_id)
    finally:
        event.remove(async_engine.sync_engine, 'before_cursor_execute', capture_sql)

    assert read_result is not None and read_result[1]
    assert unread_row is not None and unread_row.last_read_at == 0
    chat_selects = [statement for statement in statements if 'from chat' in statement]
    assert chat_selects
    assert all('chat.chat' not in statement for statement in chat_selects)
    assert any('chat.user_id' in statement and 'chat.folder_id' in statement for statement in chat_selects)


@pytest.mark.asyncio
async def test_unchanged_touch_false_chat_and_variables_skip_updates():
    row = await _add_chat(
        title='Stable',
        chat={
            'title': 'Stable',
            'history': {
                'currentId': 'user-1',
                'messages': {
                    'user-1': {
                        'id': 'user-1',
                        'role': 'user',
                        'parentId': None,
                        'childrenIds': [],
                        'timestamp': 1,
                    }
                },
            },
        },
        current_message_id='user-1',
        variables={'kept': True},
    )
    statements = []

    def capture_sql(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(async_engine.sync_engine, 'before_cursor_execute', capture_sql)
    try:
        async with get_async_db() as db:
            unchanged_chat = await Chats.update_chat_by_id(row.id, {'title': 'Stable'}, db=db, touch=False)
            unchanged_variables = await Chats.update_chat_variables_by_id(
                row.id,
                {'kept': True},
                db=db,
                touch=False,
            )
    finally:
        event.remove(async_engine.sync_engine, 'before_cursor_execute', capture_sql)

    assert unchanged_chat is not None
    assert unchanged_variables is not None
    updates = [statement for statement in statements if re.match(r'\s*update\s+["`]?chat\b', statement, re.I)]
    assert updates == []


@pytest.mark.asyncio
async def test_concurrent_tag_insert_ignores_duplicate_conflict():
    user_id = _unique('user')
    async with get_async_db() as db:
        await Tags.ensure_tags_exist(['Shared label', 'Shared label'], user_id, db=db)
        result = await db.execute(select(Tag).where(Tag.user_id == user_id))
        tags = result.scalars().all()

    assert len(tags) == 1
    assert tags[0].id == 'shared_label'


@pytest.mark.asyncio
async def test_user_delete_cleans_user_access_grants(monkeypatch):
    from open_webui.models import chats as chats_module
    from open_webui.models import groups as groups_module

    user_id = _unique('user')
    grant_id = _unique('grant')
    async with get_async_db() as db:
        db.add(
            User(
                id=user_id,
                email=f'{user_id}@example.test',
                role='user',
                name='Test user',
                last_active_at=1,
                updated_at=1,
                created_at=1,
            )
        )
        db.add(
            AccessGrant(
                id=grant_id,
                resource_type='model',
                resource_id='test-model',
                principal_type='user',
                principal_id=user_id,
                permission='read',
                created_at=1,
            )
        )
        await db.commit()

    async def skip_group_cleanup(user_id):
        return True

    async def skip_chat_cleanup(user_id, db=None):
        return True

    monkeypatch.setattr(groups_module.Groups, 'remove_user_from_all_groups', skip_group_cleanup)
    monkeypatch.setattr(chats_module.Chats, 'delete_chats_by_user_id', skip_chat_cleanup)

    async with get_async_db() as db:
        assert await Users.delete_user_by_id(user_id, db=db)

    async with get_async_db() as db:
        assert await db.get(User, user_id) is None
        assert await db.get(AccessGrant, grant_id) is None


@pytest.mark.asyncio
async def test_config_reads_reuse_explicit_async_session(monkeypatch):
    monkeypatch.setattr('open_webui.internal.db.DATABASE_ENABLE_SESSION_SHARING', True)
    key = _unique('test.config')
    value = {'nested': ['visible before commit']}
    async with get_async_db() as db:
        db.add(Config(key=key, value=value, updated_at=1))
        await db.flush()

        assert await Config.get(key, db=db) == value
        assert await Config.get_many(key, db=db) == {key: value}
        await db.rollback()


@pytest.mark.asyncio
async def test_group_name_is_trimmed_and_blank_name_rejected():
    assert GroupForm(name='  Support team  ', description='').name == 'Support team'
    with pytest.raises(ValidationError):
        GroupForm(name=' \t\n ', description='')


def test_model_settings_reject_excessive_json_depth():
    value = 'leaf'
    for _ in range(MAX_JSON_VALUE_DEPTH + 1):
        value = {'nested': value}

    with pytest.raises(ValidationError):
        ModelForm(id='test-model', name='Test model', meta={'settings': value}, params={})

    accepted = ModelForm(id='shallow-model', name='Shallow model', meta={}, params={'temperature': 0.2})
    assert accepted.id == 'shallow-model'


@pytest.mark.asyncio
async def test_prompt_history_diff_rejects_more_than_limit_lines():
    prompt_id = _unique('prompt')
    from_id = _unique('history')
    to_id = _unique('history')
    async with get_async_db() as db:
        db.add_all(
            [
                PromptHistory(
                    id=from_id,
                    prompt_id=prompt_id,
                    parent_id=None,
                    snapshot={'content': 'old\n' * 5001},
                    user_id=_unique('user'),
                    created_at=1,
                ),
                PromptHistory(
                    id=to_id,
                    prompt_id=prompt_id,
                    parent_id=from_id,
                    snapshot={'content': 'new\n'},
                    user_id=_unique('user'),
                    created_at=2,
                ),
            ]
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await PromptHistories.compute_diff(from_id, to_id, prompt_id, db=db)

    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_user_top_models_includes_stored_display_name():
    user_id = _unique('user')
    chat = await _add_chat(user_id=user_id)
    async with get_async_db() as db:
        db.add(
            ChatMessage(
                id=_unique('message'),
                chat_id=chat.id,
                user_id=user_id,
                role='assistant',
                model_id='stored-model-id',
                meta={'model_name': 'Friendly model name'},
                usage={'input_tokens': 5, 'output_tokens': 7},
                created_at=100,
                updated_at=100,
            )
        )
        await db.commit()

        models = await ChatMessages.get_user_top_models(user_id, 0, 200, db=db)

    assert models == [
        {
            'model_id': 'stored-model-id',
            'name': 'Friendly model name',
            'messages': 1,
            'input_tokens': 5,
            'output_tokens': 7,
            'total_tokens': 12,
        }
    ]


def test_postgres_json_serializer_removes_nul_and_lone_surrogates():
    valid_pair = chr(0xD83D) + chr(0xDE00)
    value = {'bad\x00key': 'a\x00b' + chr(0xD800) + valid_pair + chr(0xDFFF)}
    cleaned = strip_unstorable_json(value)

    assert cleaned == {'badkey': 'ab\U0001f600'}
    assert JSONCodec.loads(dumps_json_for_db(value)) == cleaned


@pytest.mark.parametrize('dialect_name', ['sqlite', 'postgresql'])
def test_text_json_fields_preserve_escaped_nul(dialect_name):
    field = JSONField()
    dialect = SimpleNamespace(name=dialect_name)
    value = {'key\x00': 'before\x00after'}
    stored = field.process_bind_param(value, dialect)

    assert '\x00' not in stored
    assert field.process_result_value(stored, dialect) == value


@pytest.mark.parametrize('invalid', ['\x00', chr(0xD800), chr(0xDFFF)])
def test_postgres_json_rejects_colliding_cleaned_keys(invalid):
    with pytest.raises(ValueError, match='keys collide'):
        dumps_json_for_db({'key' + invalid: 'first', 'key': 'second'})


def test_postgres_json_cleans_strings_inside_tuples():
    value = {'nested': ('before\x00after' + chr(0xD800), {'kept': ('valid',)})}

    assert JSONCodec.loads(dumps_json_for_db(value)) == {'nested': ['beforeafter', {'kept': ['valid']}]}


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['chat', 'variables'])
async def test_noop_chat_update_preserves_shared_session_commit(monkeypatch, method):
    monkeypatch.setattr('open_webui.internal.db.DATABASE_ENABLE_SESSION_SHARING', True)
    row = await _add_chat(title='Stable', chat={'title': 'Stable'}, variables={'kept': True})
    config_key = _unique('test.pending')

    async with get_async_db() as db:
        db.add(Config(key=config_key, value={'saved': True}, updated_at=1))
        await db.flush()
        if method == 'chat':
            result = await Chats.update_chat_by_id(row.id, {'title': 'Stable'}, db=db, touch=False)
        else:
            result = await Chats.update_chat_variables_by_id(row.id, {'kept': True}, db=db, touch=False)
        assert result is not None

    async with get_async_db() as db:
        persisted = await db.get(Config, config_key)
        assert persisted is not None
        assert persisted.value == {'saved': True}

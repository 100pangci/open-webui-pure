import time
from uuid import uuid4

import pytest

from open_webui.utils import temporary_chat


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.eval_result = 1

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def eval(self, script, numkeys, key, expected, encoded, ttl):
        if not self.eval_result:
            return 0
        if self.values.get(key) != expected:
            return 0
        self.values[key] = encoded
        return self.eval_result


@pytest.fixture(autouse=True)
def clear_registry():
    temporary_chat._temporary_chat_owners.clear()
    yield temporary_chat._temporary_chat_owners.clear()


def temporary_chat_id(session_id='session-a'):
    return f'temporary:{session_id}:{uuid4()}'


async def test_memory_create_and_get():
    chat_id = temporary_chat_id()

    assert await temporary_chat.register_temporary_chat_session(
        None, chat_id, 'user-1', 'session-a', 'user-1', create=True
    )
    assert await temporary_chat.get_temporary_chat(None, chat_id) == {
        'user_id': 'user-1',
        'session_id': 'session-a',
    }


async def test_memory_reattach_updates_session():
    chat_id = temporary_chat_id()
    await temporary_chat.register_temporary_chat_session(None, chat_id, 'user-1', 'session-a', 'user-1', create=True)

    assert await temporary_chat.register_temporary_chat_session(None, chat_id, 'user-1', 'session-b', 'user-1')
    assert (await temporary_chat.get_temporary_chat(None, chat_id))['session_id'] == 'session-b'


async def test_memory_requires_live_session_owned_by_user():
    chat_id = temporary_chat_id()
    assert not await temporary_chat.register_temporary_chat_session(
        None, chat_id, 'user-1', 'session-a', 'user-2', create=True
    )
    assert await temporary_chat.get_temporary_chat(None, chat_id) is None


async def test_memory_other_user_cannot_take_over():
    chat_id = temporary_chat_id()
    await temporary_chat.register_temporary_chat_session(None, chat_id, 'user-1', 'session-a', 'user-1', create=True)

    assert not await temporary_chat.register_temporary_chat_session(None, chat_id, 'user-2', 'session-b', 'user-2')
    assert await temporary_chat.get_temporary_chat(None, chat_id) == {
        'user_id': 'user-1',
        'session_id': 'session-a',
    }


async def test_memory_create_requires_origin_session():
    chat_id = temporary_chat_id(session_id='session-a')
    assert not await temporary_chat.register_temporary_chat_session(
        None, chat_id, 'user-1', 'session-b', 'user-1', create=True
    )


async def test_memory_no_create_without_owner():
    chat_id = temporary_chat_id()
    assert not await temporary_chat.register_temporary_chat_session(None, chat_id, 'user-1', 'session-a', 'user-1')


async def test_memory_expired_entry_is_removed():
    chat_id = temporary_chat_id()
    temporary_chat._temporary_chat_owners[chat_id] = (
        time.monotonic() - 1,
        {'user_id': 'user-1', 'session_id': 'session-a'},
    )

    assert await temporary_chat.get_temporary_chat(None, chat_id) is None
    assert chat_id not in temporary_chat._temporary_chat_owners


async def test_redis_create_and_reattach():
    redis = FakeRedis()
    chat_id = temporary_chat_id()

    assert await temporary_chat.register_temporary_chat_session(
        redis, chat_id, 'user-1', 'session-a', 'user-1', create=True
    )
    assert await temporary_chat.get_temporary_chat(redis, chat_id) == {
        'user_id': 'user-1',
        'session_id': 'session-a',
    }
    assert await temporary_chat.register_temporary_chat_session(redis, chat_id, 'user-1', 'session-b', 'user-1')
    assert (await temporary_chat.get_temporary_chat(redis, chat_id))['session_id'] == 'session-b'


async def test_redis_cas_conflict_does_not_overwrite():
    redis = FakeRedis()
    chat_id = temporary_chat_id()
    await temporary_chat.register_temporary_chat_session(redis, chat_id, 'user-1', 'session-a', 'user-1', create=True)
    redis.eval_result = 0

    assert not await temporary_chat.register_temporary_chat_session(redis, chat_id, 'user-1', 'session-b', 'user-1')
    assert (await temporary_chat.get_temporary_chat(redis, chat_id))['session_id'] == 'session-a'


async def test_redis_other_user_cannot_take_over():
    redis = FakeRedis()
    chat_id = temporary_chat_id()
    await temporary_chat.register_temporary_chat_session(redis, chat_id, 'user-1', 'session-a', 'user-1', create=True)

    assert not await temporary_chat.register_temporary_chat_session(redis, chat_id, 'user-2', 'session-b', 'user-2')

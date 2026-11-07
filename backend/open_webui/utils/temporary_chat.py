import json
import time

from open_webui.env import REDIS_KEY_PREFIX
from open_webui.utils.chat_id import get_temporary_chat_session_id

TEMPORARY_CHAT_TTL = 24 * 60 * 60
_temporary_chat_owners: dict[str, tuple[float, dict]] = {}


def _temporary_chat_key(chat_id):
    return f'{REDIS_KEY_PREFIX}:chat:{chat_id}:session'


async def get_temporary_chat(redis, chat_id):
    if redis is not None:
        value = await redis.get(_temporary_chat_key(chat_id))
        return json.loads(value) if value else None
    expiry, owner = _temporary_chat_owners.get(chat_id, (0, None))
    if expiry <= time.monotonic():
        _temporary_chat_owners.pop(chat_id, None)
        return None
    return owner


async def register_temporary_chat_session(redis, chat_id, user_id, session_id, session_owner, *, create=False):
    """Only an authenticated live socket can create or reattach its user's chat."""
    origin = get_temporary_chat_session_id(chat_id)
    if not origin or not session_id or session_owner != user_id:
        return False
    owner = await get_temporary_chat(redis, chat_id)
    if owner is None:
        if not create or origin != session_id:
            return False
    elif owner['user_id'] != user_id:
        return False

    value = {'user_id': user_id, 'session_id': session_id}
    if redis is not None:
        encoded = json.dumps(value, sort_keys=True)
        if owner is None:
            return bool(
                await redis.set(_temporary_chat_key(chat_id), encoded, nx=True, ex=TEMPORARY_CHAT_TTL)
            ) or await register_temporary_chat_session(redis, chat_id, user_id, session_id, session_owner)
        # An expired/replaced record must not be overwritten after the ownership check.
        return bool(
            await redis.eval(
                "if redis.call('get', KEYS[1]) ~= ARGV[1] then return 0 end "
                "redis.call('set', KEYS[1], ARGV[2], 'EX', ARGV[3]); return 1",
                1,
                _temporary_chat_key(chat_id),
                json.dumps(owner, sort_keys=True),
                encoded,
                TEMPORARY_CHAT_TTL,
            )
        )
    now = time.monotonic()
    for key, (expiry, _) in list(_temporary_chat_owners.items()):
        if expiry <= now:
            _temporary_chat_owners.pop(key, None)
    _temporary_chat_owners[chat_id] = (now + TEMPORARY_CHAT_TTL, value)
    return True

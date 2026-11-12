import pytest

from open_webui.socket.utils import RedisDict


class FakeRedis:
    """Minimal hash client that records decoded value fetches."""

    def __init__(self):
        self.hashes = {}
        self.signatures = {}
        self.hvals_calls = 0

    def hset(self, name, mapping=None):
        self.hashes.setdefault(name, {}).update(mapping or {})

    def hvals(self, name):
        self.hvals_calls += 1
        return list(self.hashes.get(name, {}).values())

    def hgetall(self, name):
        return dict(self.hashes.get(name, {}))

    def hkeys(self, name):
        return list(self.hashes.get(name, {}).keys())

    def hdel(self, name, *keys):
        for key in keys:
            self.hashes.get(name, {}).pop(key, None)

    def hlen(self, name):
        return len(self.hashes.get(name, {}))

    def hexists(self, name, key):
        return key in self.hashes.get(name, {})

    def hget(self, name, key):
        return self.hashes.get(name, {}).get(key)

    def get(self, key):
        return self.signatures.get(key)

    def set(self, key, value):
        self.signatures[key] = value

    def delete(self, *keys):
        for key in keys:
            self.signatures.pop(key, None)
            self.hashes.pop(key, None)


@pytest.fixture(autouse=True)
def fake_connection(monkeypatch):
    """Skip the real Redis client: ``redis`` is an optional dependency.

    ``RedisDict.__init__`` would otherwise import the ``redis`` package,
    which the default install does not ship.
    """
    monkeypatch.setattr('open_webui.socket.utils.get_redis_connection', lambda *args, **kwargs: FakeRedis())


def make_dict(cache_set_signature):
    redis_dict = RedisDict('models', 'redis://unused', cache_set_signature=cache_set_signature)
    redis_dict.redis = FakeRedis()
    return redis_dict


def test_values_are_decoded_once_per_signature():
    redis_dict = make_dict(cache_set_signature=True)
    redis_dict.set({'a': {'v': 1}, 'b': {'v': 2}})

    assert sorted(redis_dict.values(), key=lambda value: value['v']) == [{'v': 1}, {'v': 2}]
    redis_dict.values()
    assert redis_dict.redis.hvals_calls == 1

    redis_dict.set({'a': {'v': 3}, 'b': {'v': 2}})
    assert sorted(redis_dict.values(), key=lambda value: value['v']) == [{'v': 2}, {'v': 3}]
    assert redis_dict.redis.hvals_calls == 2


def test_values_are_not_cached_without_signature():
    redis_dict = make_dict(cache_set_signature=False)
    redis_dict.set({'a': {'v': 1}})

    redis_dict.values()
    redis_dict.values()
    assert redis_dict.redis.hvals_calls == 2


def test_delete_many_invalidates_the_cache():
    redis_dict = make_dict(cache_set_signature=True)
    redis_dict.set({'a': {'v': 1}, 'b': {'v': 2}})
    redis_dict.values()

    redis_dict.delete_many('b')

    assert redis_dict.values() == [{'v': 1}]


def test_set_after_delete_many_writes_again():
    redis_dict = make_dict(cache_set_signature=True)
    redis_dict.set({'a': {'v': 1}})
    redis_dict.delete_many('a')

    redis_dict.set({'a': {'v': 1}})

    assert redis_dict.values() == [{'v': 1}]

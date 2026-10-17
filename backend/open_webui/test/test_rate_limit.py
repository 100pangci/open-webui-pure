import pytest

from open_webui.utils import rate_limit
from open_webui.utils.rate_limit import RateLimiter


@pytest.mark.asyncio
async def test_memory_limit_and_expiry(monkeypatch):
    now = [0]
    monkeypatch.setattr(rate_limit.time, 'time', lambda: now[0])
    limiter = RateLimiter(limit=2, window=120)
    assert not await limiter.is_limited(None, 'USER@example.com')
    assert not await limiter.is_limited(None, 'user@example.com')
    assert await limiter.is_limited(None, 'user@example.com')
    now[0] = 240
    assert not await limiter.is_limited(None, 'other@example.com')
    assert await limiter.get_count(None, 'user@example.com') == 0
    assert all('user@example.com' not in bucket for bucket in limiter._memory_store.values())


@pytest.mark.asyncio
async def test_limiter_instances_do_not_share_buckets():
    first = RateLimiter(limit=0, window=60)
    second = RateLimiter(limit=1, window=60)
    assert await first.is_limited(None, 'user')
    assert await second.get_count(None, 'user') == 0
    assert not await second.is_limited(None, 'user')


@pytest.mark.asyncio
async def test_async_redis_failure_falls_back_to_memory():
    class BrokenRedis:
        async def incr(self, key):
            raise ConnectionError('Redis is restarting')

        async def mget(self, keys):
            raise ConnectionError('Redis is restarting')

    limiter = RateLimiter(limit=1, window=60)
    redis = BrokenRedis()
    assert not await limiter.is_limited(redis, 'user')
    assert await limiter.is_limited(redis, 'user')
    assert await limiter.remaining(redis, 'user') == 0


@pytest.mark.asyncio
async def test_redis_commands_are_awaited():
    class Redis:
        def __init__(self):
            self.counts = {}
            self.expired = []

        async def incr(self, key):
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        async def expire(self, key, seconds):
            self.expired.append((key, seconds))

        async def mget(self, keys):
            return [self.counts.get(key) for key in keys]

    redis = Redis()
    limiter = RateLimiter(limit=1, window=60)
    assert not await limiter.is_limited(redis, 'user')
    assert await limiter.is_limited(redis, 'user')
    assert len(redis.expired) == 1


@pytest.mark.asyncio
async def test_disabled_limiter_does_not_count():
    limiter = RateLimiter(limit=0, window=60, enabled=False)
    assert not await limiter.is_limited(None, 'user')
    assert await limiter.get_count(None, 'user') == 0

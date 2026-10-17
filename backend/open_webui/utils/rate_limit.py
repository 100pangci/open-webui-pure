import time
from typing import Any

from open_webui.env import REDIS_KEY_PREFIX


class RateLimiter:
    """Rolling-window throttle with optional async Redis and bounded-age fallback buckets."""

    def __init__(self, limit: int, window: int, bucket_size: int = 60, enabled: bool = True):
        if window <= 0 or bucket_size <= 0:
            raise ValueError('Rate-limit window and bucket size must be positive')
        self.limit = limit
        self.window = window
        self.bucket_size = bucket_size
        self.num_buckets = window // bucket_size
        self.enabled = enabled
        # Per instance, keyed by time first: inactive identities disappear too.
        self._memory_store: dict[int, dict[str, int]] = {}

    def _bucket_key(self, key: str, bucket_index: int) -> str:
        return f'{REDIS_KEY_PREFIX}:ratelimit:{key.lower()}:{bucket_index}'

    def _current_bucket(self) -> int:
        return int(time.time()) // self.bucket_size

    def _prune_memory_store(self, now_bucket: int) -> None:
        min_bucket = now_bucket - self.num_buckets
        for bucket_index in list(self._memory_store):
            if bucket_index < min_bucket:
                del self._memory_store[bucket_index]

    async def is_limited(self, redis: Any, key: str) -> bool:
        if not self.enabled:
            return False
        key = key.lower()
        if redis is not None:
            try:
                return await self._is_limited_redis(redis, key)
            except Exception:
                pass
        return self._is_limited_memory(key)

    async def get_count(self, redis: Any, key: str) -> int:
        if not self.enabled:
            return 0
        key = key.lower()
        if redis is not None:
            try:
                return await self._get_count_redis(redis, key)
            except Exception:
                pass
        return self._get_count_memory(key)

    async def remaining(self, redis: Any, key: str) -> int:
        return max(0, self.limit - await self.get_count(redis, key))

    async def _is_limited_redis(self, redis: Any, key: str) -> bool:
        now_bucket = self._current_bucket()
        bucket_key = self._bucket_key(key, now_bucket)
        attempts = await redis.incr(bucket_key)
        if attempts == 1:
            await redis.expire(bucket_key, self.window + self.bucket_size)
        return await self._get_count_redis(redis, key) > self.limit

    async def _get_count_redis(self, redis: Any, key: str) -> int:
        now_bucket = self._current_bucket()
        buckets = [self._bucket_key(key, now_bucket - i) for i in range(self.num_buckets + 1)]
        counts = await redis.mget(buckets)
        return sum(int(count) for count in counts if count)

    def _is_limited_memory(self, key: str) -> bool:
        now_bucket = self._current_bucket()
        self._prune_memory_store(now_bucket)
        counts = self._memory_store.setdefault(now_bucket, {})
        counts[key] = counts.get(key, 0) + 1
        return sum(bucket.get(key, 0) for bucket in self._memory_store.values()) > self.limit

    def _get_count_memory(self, key: str) -> int:
        self._prune_memory_store(self._current_bucket())
        return sum(bucket.get(key, 0) for bucket in self._memory_store.values())

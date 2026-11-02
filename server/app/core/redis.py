from functools import lru_cache

from redis import Redis

from app.core.config import get_settings


@lru_cache
def get_redis() -> Redis:
    url = get_settings().redis_url
    if url.startswith("memory://"):
        import fakeredis  # 仅开发和测试依赖

        return fakeredis.FakeRedis(decode_responses=True)
    return Redis.from_url(url, decode_responses=True)

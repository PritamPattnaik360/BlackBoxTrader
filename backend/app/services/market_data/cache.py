import time
from typing import Any
from app.config import settings

_memory_cache: dict[str, tuple[Any, float]] = {}
_redis_client = None


def _get_redis():
    global _redis_client
    if not settings.use_redis:
        return None
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
            _redis_client.ping()
        except Exception:
            _redis_client = None
    return _redis_client


def set_quote(ticker: str, data: dict, ttl: int = 30) -> None:
    import json
    key = f"quote:{ticker}"
    r = _get_redis()
    if r:
        try:
            r.setex(key, ttl, json.dumps(data))
            return
        except Exception:
            pass
    _memory_cache[key] = (data, time.time() + ttl)


def get_quote(ticker: str) -> dict | None:
    import json
    key = f"quote:{ticker}"
    r = _get_redis()
    if r:
        try:
            val = r.get(key)
            if val:
                return json.loads(val)
        except Exception:
            pass
    entry = _memory_cache.get(key)
    if entry and entry[1] > time.time():
        return entry[0]
    return None


def publish_quote(ticker: str, data: dict) -> None:
    import json
    r = _get_redis()
    if r:
        try:
            r.publish(f"quotes:{ticker}", json.dumps(data))
        except Exception:
            pass


def subscribe_quotes(tickers: list[str]):
    r = _get_redis()
    if not r:
        return None
    try:
        pubsub = r.pubsub()
        pubsub.subscribe(*[f"quotes:{t}" for t in tickers])
        return pubsub
    except Exception:
        return None

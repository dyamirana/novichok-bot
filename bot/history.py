from redis.asyncio import Redis

from .config import REDIS_URL


redis: Redis


async def init_history() -> None:
    global redis
    redis = Redis.from_url(REDIS_URL, decode_responses=True)


async def add_message(chat_id: int, text: str) -> None:
    key = f"chat:{chat_id}:history"
    await redis.rpush(key, text)
    await redis.ltrim(key, -100, -1)


async def get_history(chat_id: int, limit: int = 10) -> list[str]:
    key = f"chat:{chat_id}:history"
    return await redis.lrange(key, -limit, -1)


async def increment_count(chat_id: int) -> bool:
    key = f"chat:{chat_id}:count"
    val = await redis.incr(key)
    if val >= 10:
        await redis.set(key, 0)
        return True
    return False


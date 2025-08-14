import json
from redis.asyncio import Redis

from .config import REDIS_URL


redis: Redis
redis = Redis.from_url(REDIS_URL, decode_responses=True)


async def init_history() -> None:
    ...


async def add_message(
    chat_id: int, msg_id: int, text: str, reply_to: int | None = None
) -> None:
    hist_key = f"chat:{chat_id}:history"
    await redis.rpush(hist_key, text)
    await redis.ltrim(hist_key, -100, -1)
    msg_key = f"chat:{chat_id}:messages"
    data = {"text": text, "reply": reply_to or 0}
    await redis.hset(msg_key, msg_id, json.dumps(data))


async def get_history(chat_id: int, limit: int = 10) -> list[str]:
    key = f"chat:{chat_id}:history"
    return await redis.lrange(key, -limit, -1)


async def get_thread(chat_id: int, msg_id: int) -> list[str]:
    msg_key = f"chat:{chat_id}:messages"
    texts: list[str] = []
    current = msg_id
    while current:
        raw = await redis.hget(msg_key, current)
        if not raw:
            break
        data = json.loads(raw)
        texts.append(data.get("text", ""))
        current = data.get("reply") or 0
    return list(reversed(texts))


async def increment_count(chat_id: int, msg_id: int) -> bool:
    last_key = f"chat:{chat_id}:last_msg"
    if not await redis.set(last_key, msg_id, nx=True, ex=60):
        return False
    key = f"chat:{chat_id}:count"
    val = await redis.incr(key)
    if val >= 10:
        await redis.set(key, 0)
        return True
    return False


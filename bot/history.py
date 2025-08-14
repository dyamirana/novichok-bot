import json
from redis.asyncio import Redis

from .config import REDIS_URL


redis: Redis
redis = Redis.from_url(REDIS_URL, decode_responses=True)


async def init_history() -> None:
    ...


async def add_message(
    chat_id: int,
    msg_id: int,
    text: str,
    reply_to: int | None = None,
    *,
    role: str = "user",
    name: str | None = None,
) -> None:
    """Store a message in Redis with role-based metadata.

    Messages are stored twice:
    - in a list for quick retrieval of the last messages
    - in a hash with reply mapping for building threads
    """

    hist_key = f"chat:{chat_id}:history"
    msg_data: dict[str, str | int] = {"role": role, "content": text}
    if name:
        msg_data["name"] = name
    await redis.rpush(hist_key, json.dumps(msg_data))
    await redis.ltrim(hist_key, -100, -1)

    msg_key = f"chat:{chat_id}:messages"
    data = {"role": role, "content": text, "reply": reply_to or 0}
    if name:
        data["name"] = name
    await redis.hset(msg_key, msg_id, json.dumps(data))


async def get_history(chat_id: int, limit: int = 10) -> list[dict]:
    """Return the last messages for a chat as role-based dicts."""

    key = f"chat:{chat_id}:history"
    raw_messages = await redis.lrange(key, -limit, -1)
    messages: list[dict] = []
    for raw in raw_messages:
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError
        except Exception:
            # Fall back to treating the raw string as a user message
            data = {"role": "user", "content": raw}
        msg: dict[str, str] = {
            "role": data.get("role", "user"),
            "content": data.get("content", ""),
        }
        name = data.get("name")
        if name:
            msg["name"] = name
        messages.append(msg)
    return messages


async def get_thread(chat_id: int, msg_id: int) -> list[dict]:
    """Return a message thread starting at ``msg_id`` as role-based dicts."""

    msg_key = f"chat:{chat_id}:messages"
    msgs: list[dict] = []
    current = msg_id
    while current:
        raw = await redis.hget(msg_key, current)
        if not raw:
            break
        data = json.loads(raw)
        msg: dict[str, str] = {
            "role": data.get("role", "user"),
            "content": data.get("content", ""),
        }
        name = data.get("name")
        if name:
            msg["name"] = name
        msgs.append(msg)
        current = data.get("reply") or 0
    return list(reversed(msgs))


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


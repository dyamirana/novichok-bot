import json
from aiogram import Bot

from .config import logger

CHANNEL = "auto_reply"


async def listen_auto_replies(bot: Bot, personality: str) -> None:
    from .history import redis
    from .handlers.common import respond_with_personality_to_chat

    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL)
    async for msg in pubsub.listen():
        if msg.get("type") != "message":
            continue
        raw = msg.get("data")
        try:
            data = json.loads(raw)
        except Exception:
            logger.error(f"[AUTO_REPLY_BAD_PAYLOAD] data={raw}")
            continue
        if data.get("personality") != personality:
            continue
        chat_id = data.get("chat_id")
        user_id = data.get("user_id")
        thread_id = data.get("thread_id")
        msg_id = data.get("msg_id")
        text = data.get("text", "")
        if not isinstance(thread_id, int):
            thread_id = 0
        if not isinstance(chat_id, int) or not isinstance(msg_id, int):
            continue
        try:
            await respond_with_personality_to_chat(
                bot,
                chat_id,
                int(user_id or 0),
                thread_id,
                personality,
                text,
                reply_to_message_id=msg_id,
                delay_range=(60, 180),
            )
        except Exception as e:
            logger.error(f"[AUTO_REPLY_FAIL] chat_id={chat_id} err={e}")


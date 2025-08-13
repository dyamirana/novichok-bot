import asyncio

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_TOKENS, BOT_TOKEN, PERSONALITY, setup_logging, logger
from bot.db import init_db
from bot.history import init_history
from bot.handlers import register_handlers
from bot.auto_reply import listen_auto_replies


async def _start_single_bot(token: str, personality: str) -> None:
    bot = Bot(token=token, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())
    register_handlers(dp, personality)
    tasks = [dp.start_polling(bot), listen_auto_replies(bot, personality)]
    logger.info(f"bot {personality} started")
    await asyncio.gather(*tasks)


async def main() -> None:
    await init_db()
    await init_history()
    setup_logging()
    if PERSONALITY:
        token = BOT_TOKENS.get(PERSONALITY, BOT_TOKEN)
        if not token:
            logger.error("No token provided for personality %s", PERSONALITY)
            return
        await _start_single_bot(token, PERSONALITY)
        return
    tasks = [
        asyncio.create_task(_start_single_bot(token, personality))
        for personality, token in BOT_TOKENS.items()
    ]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())

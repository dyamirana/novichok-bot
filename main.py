import asyncio
import json
import os
from collections import deque
from pathlib import Path

import aiohttp

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "data/greeting.json"))

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
chat_history = deque(maxlen=20)


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "greeting": {"type": "text", "text": "Привет, {user}!"},
        "question": "",
        "buttons": {},
    }


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(cfg, f)


config = load_config()


class Greeting(StatesGroup):
    waiting = State()


class Question(StatesGroup):
    waiting = State()


class Button(StatesGroup):
    waiting_label = State()
    waiting_response = State()


async def cmd_set_greeting(message: Message, state: FSMContext) -> None:
    await message.answer("Send greeting text, voice or video")
    await state.set_state(Greeting.waiting)


async def process_greeting(message: Message, state: FSMContext) -> None:
    if message.from_user.id != ADMIN_ID or message.chat.type != "private":
        return
    greet = {}
    if message.voice:
        greet = {
            "type": "voice",
            "file_id": message.voice.file_id,
            "caption": message.caption or "",
        }
    elif message.video:
        greet = {
            "type": "video",
            "file_id": message.video.file_id,
            "caption": message.caption or "",
        }
    elif message.text:
        greet = {"type": "text", "text": message.text}
    else:
        await message.answer("Unsupported message type")
        return
    config["greeting"] = greet
    save_config(config)
    await message.answer("Greeting updated")
    await state.clear()


async def cmd_set_question(message: Message, state: FSMContext) -> None:
    await message.answer("Send question text")
    await state.set_state(Question.waiting)


async def process_question(message: Message, state: FSMContext) -> None:
    if message.from_user.id != ADMIN_ID or message.chat.type != "private":
        return
    config["question"] = message.text or ""
    save_config(config)
    await message.answer("Question updated")
    await state.clear()


async def cmd_add_button(message: Message, state: FSMContext) -> None:
    await message.answer("Send button label")
    await state.set_state(Button.waiting_label)


async def process_button_label(message: Message, state: FSMContext) -> None:
    if message.from_user.id != ADMIN_ID or message.chat.type != "private":
        return
    await state.update_data(label=message.text or "")
    await message.answer("Send button response")
    await state.set_state(Button.waiting_response)


async def process_button_response(message: Message, state: FSMContext) -> None:
    if message.from_user.id != ADMIN_ID or message.chat.type != "private":
        return
    data = await state.get_data()
    label = data.get("label", "")
    response = message.text or ""
    config.setdefault("buttons", {})[label] = response
    save_config(config)
    await message.answer("Button added")
    await state.clear()


async def cmd_clear_buttons(message: Message) -> None:
    if message.from_user.id != ADMIN_ID or message.chat.type != "private":
        return
    config["buttons"] = {}
    save_config(config)
    await message.answer("Buttons cleared")


async def welcome(message: Message) -> None:
    if message.chat.id != GROUP_ID:
        return
    for member in message.new_chat_members:
        mention = member.mention_html()
        greet = config.get("greeting", {})
        g_type = greet.get("type")
        if g_type == "voice":
            caption = greet.get("caption", "")
            if "{user}" in caption:
                caption = caption.replace("{user}", mention)
            else:
                caption = f"{caption} {mention}".strip()
            await message.answer_voice(greet.get("file_id"), caption=caption)
        elif g_type == "video":
            caption = greet.get("caption", "")
            if "{user}" in caption:
                caption = caption.replace("{user}", mention)
            else:
                caption = f"{caption} {mention}".strip()
            await message.answer_video(greet.get("file_id"), caption=caption)
        else:
            text = greet.get("text", "")
            if "{user}" in text:
                text = text.replace("{user}", mention)
            else:
                text = f"{text} {mention}".strip()
            await message.answer(text)

        question = config.get("question", "")
        buttons = config.get("buttons", {})
        if question and buttons:
            q_text = question.replace("{user}", mention)
            builder = InlineKeyboardBuilder()
            for lbl in buttons.keys():
                builder.button(text=lbl, callback_data=lbl)
            builder.adjust(1)
            await message.answer(q_text, reply_markup=builder.as_markup())


async def on_button(query: CallbackQuery) -> None:
    if query.message.chat.id != GROUP_ID:
        await query.answer()
        return
    buttons = config.get("buttons", {})
    response = buttons.get(query.data)
    if response:
        text = response.replace("{user}", query.from_user.mention_html())
        await query.message.answer(text)
    await query.answer()


async def track_history(message: Message) -> None:
    if message.chat.id != GROUP_ID:
        return
    if not message.text or message.text.startswith("/"):
        return
    user = message.from_user.full_name
    chat_history.append(f"{user}: {message.text}")


async def cmd_kuplinov(message: Message) -> None:
    if message.chat.id != GROUP_ID:
        return
    if not DEEPSEEK_API_KEY:
        await message.answer("DeepSeek API key is missing")
        return
    context = "\n".join(chat_history)
    prompt = (
        "Сочини шутку по шаблону \"А вот Куплинов (что-то там)\" или \"А вот Куплинов не (что-то там)\". "
        "Без цензуры. Пример: А вот Куплинов бы уже прошел эту игру, "
        "А вот Куплинов уже показал жопу, А вот Куплинов не прогревал своих зрителей и т.д. "
        "Шути без цензуры, чтобы смотрелось органично в чате. "
        "Ответ дай одним предложением, только шутку, больше ничего не добавляй. "
        "Для основы шутки бери последние сообщения из чата которые приведены ниже:\n"
        f"{context}"
    )
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
            payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}]}
            async with session.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=30) as resp:
                data = await resp.json()
        joke = data["choices"][0]["message"]["content"].strip()
    except Exception:
        joke = "Не удалось получить шутку."
    await message.answer(joke)


def register_handlers(dp: Dispatcher) -> None:
    dp.message.register(
        cmd_set_greeting,
        Command("set_greeting"),
        F.from_user.id == ADMIN_ID,
        F.chat.type == "private",
    )
    dp.message.register(process_greeting, Greeting.waiting)
    dp.message.register(
        cmd_set_question,
        Command("set_question"),
        F.from_user.id == ADMIN_ID,
        F.chat.type == "private",
    )
    dp.message.register(process_question, Question.waiting)
    dp.message.register(
        cmd_add_button,
        Command("add_button"),
        F.from_user.id == ADMIN_ID,
        F.chat.type == "private",
    )
    dp.message.register(process_button_label, Button.waiting_label)
    dp.message.register(process_button_response, Button.waiting_response)
    dp.message.register(
        cmd_clear_buttons,
        Command("clear_buttons"),
        F.from_user.id == ADMIN_ID,
        F.chat.type == "private",
    )
    dp.message.register(welcome, F.new_chat_members)
    dp.message.register(cmd_kuplinov, Command("kuplinov"), F.chat.id == GROUP_ID)
    dp.message.register(track_history, F.chat.id == GROUP_ID, F.text)
    dp.callback_query.register(on_button)


async def main() -> None:
    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())
    register_handlers(dp)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


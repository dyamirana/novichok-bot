import asyncio
import json
import os
import time
from collections import deque
from pathlib import Path
import hashlib
import re

import sys

try:
    from loguru import logger
    _LOGURU = True
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger("bot")
    _LOGURU = False

import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
_GROUP_IDS_RAW = os.getenv("GROUP_IDS", "").strip()
_GROUP_ID_SINGLE = os.getenv("GROUP_ID", "0").strip()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DB_PATH = Path(os.getenv("DB_PATH", "data/bot.db"))

# Logging setup helper
def setup_logging():
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    if '_LOGURU' in globals() and _LOGURU:
        logger.remove()
        logger.add(
            sys.stdout,
            level=level,
            backtrace=False,
            diagnose=False,
            enqueue=True,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        )

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
chat_history = deque(maxlen=10)
db: aiosqlite.Connection

def _parse_group_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    if not raw:
        return ids
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return ids

ALLOWED_CHAT_IDS: set[int] = _parse_group_ids(_GROUP_IDS_RAW)
if not ALLOWED_CHAT_IDS and _GROUP_ID_SINGLE and _GROUP_ID_SINGLE != "0":
    try:
        ALLOWED_CHAT_IDS = {int(_GROUP_ID_SINGLE)}
    except ValueError:
        ALLOWED_CHAT_IDS = set()

def is_group_allowed(chat_id: int) -> bool:
    return chat_id in ALLOWED_CHAT_IDS

class GreetingState(StatesGroup):
    waiting = State()


class QuestionState(StatesGroup):
    waiting = State()


class ButtonAddState(StatesGroup):
    waiting_label = State()
    waiting_response = State()


class ButtonEditState(StatesGroup):
    waiting_response = State()


class KuplinovAddState(StatesGroup):
    waiting_id = State()


class KuplinovDelState(StatesGroup):
    waiting_id = State()


async def init_db() -> aiosqlite.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(DB_PATH)
    await conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS config
        (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS buttons
        (
            label    TEXT PRIMARY KEY,
            response TEXT
        );
        CREATE TABLE IF NOT EXISTS allowed_users
        (
            user_id INTEGER PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS rate_limit
        (
            user_id INTEGER PRIMARY KEY,
            last_ts INTEGER
        );
        """
    )
    await conn.commit()
    return conn


async def get_config(key: str, default=None):
    async with db.execute("SELECT value FROM config WHERE key=?", (key,)) as cur:
        row = await cur.fetchone()
    return row[0] if row else default


async def set_config(key: str, value: str) -> None:
    await db.execute("REPLACE INTO config(key,value) VALUES(?,?)", (key, value))
    await db.commit()


async def get_greeting() -> dict:
    data = await get_config("greeting")
    if data:
        return json.loads(data)
    return {"type": "text", "text": "Привет, {user}!"}


async def set_greeting(greet: dict) -> None:
    await set_config("greeting", json.dumps(greet))


async def get_question() -> str:
    return await get_config("question", "")


async def set_question(question: str) -> None:
    await set_config("question", question)


async def get_buttons() -> dict:
    buttons: dict[str, dict] = {}
    async with db.execute("SELECT label,response FROM buttons") as cur:
        async for label, response in cur:
            try:
                payload = json.loads(response)
                if isinstance(payload, dict) and "type" in payload:
                    buttons[label] = payload
                else:
                    # Fallback: plain text stored inside JSON or unexpected structure
                    buttons[label] = {"type": "text", "text": str(payload)}
            except Exception:
                # Legacy plain text response
                buttons[label] = {"type": "text", "text": response}
    return buttons


async def add_button(label: str, response: str) -> None:
    await db.execute("REPLACE INTO buttons(label,response) VALUES(?,?)", (label, response))
    await db.commit()


async def remove_button(label: str) -> None:
    await db.execute("DELETE FROM buttons WHERE label=?", (label,))
    await db.commit()



# Helper to generate a short hash for button labels
def _btn_id(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()[:10]

# Helper to extract and strip spoiler markers from captions
def _extract_spoiler_from_caption(caption: str) -> tuple[str, bool]:
    if not caption:
        return "", False
    text = caption
    has = False
    markers = ["#spoiler", "[spoiler]", "(spoiler)", "#спойлер", "[спойлер]", "(спойлер)"]
    for m in markers:
        if m.lower() in text.lower():
            has = True
            text = re.sub(re.escape(m), "", text, flags=re.IGNORECASE)
    return text.strip(), has


async def get_allowed_users() -> list:
    users = []
    async with db.execute("SELECT user_id FROM allowed_users") as cur:
        async for (uid,) in cur:
            users.append(uid)
    return users


async def add_allowed_user(uid: int) -> None:
    await db.execute("INSERT OR IGNORE INTO allowed_users(user_id) VALUES(?)", (uid,))
    await db.commit()


async def remove_allowed_user(uid: int) -> None:
    await db.execute("DELETE FROM allowed_users WHERE user_id=?", (uid,))
    await db.commit()


async def is_allowed(uid: int) -> bool:
    if uid == ADMIN_ID:
        return True
    async with db.execute("SELECT 1 FROM allowed_users WHERE user_id=?", (uid,)) as cur:
        return await cur.fetchone() is not None


async def check_rate(uid: int) -> tuple:
    # Admin и разрешённые пользователи не лимитируются
    if uid == ADMIN_ID or await is_allowed(uid):
        return True, 0
    now = int(time.time())
    async with db.execute("SELECT last_ts FROM rate_limit WHERE user_id=?", (uid,)) as cur:
        row = await cur.fetchone()
    if row and now - row[0] < 60:
        return False, 60 - (now - row[0])
    await db.execute("REPLACE INTO rate_limit(user_id,last_ts) VALUES(?,?)", (uid, now))
    await db.commit()
    return True, 0


def main_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="Приветствие", callback_data="menu_greeting")
    builder.button(text="Вопрос", callback_data="menu_question")
    builder.button(text="Кнопки", callback_data="menu_buttons")
    builder.button(text="/kuplinov", callback_data="menu_kuplinov")
    builder.button(text="Предпросмотр", callback_data="menu_preview")
    builder.adjust(1)
    return builder.as_markup()


def buttons_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить", callback_data="btn_add")
    builder.button(text="Удалить", callback_data="btn_del")
    builder.button(text="Редактировать", callback_data="btn_edit")
    builder.button(text="Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def kuplinov_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить пользователя", callback_data="kp_add")
    builder.button(text="Удалить пользователя", callback_data="kp_del")
    builder.button(text="Список", callback_data="kp_list")
    builder.button(text="Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()



async def cmd_start(message: Message) -> None:
    if message.from_user.id != ADMIN_ID or message.chat.type != "private":
        return
    await message.answer("Выберите действие:", reply_markup=main_menu())


# Handler for /chatid command: sends chat_id to admin in private
async def cmd_chatid(message: Message) -> None:
    """Send current chat_id to admin in private."""
    chat = message.chat
    title = chat.title or getattr(chat, "full_name", "") or ""
    info = (
        "Запрос chat_id"
        f"\nНазвание: {title}"
        f"\nТип: {chat.type}"
        f"\nchat_id: <code>{chat.id}</code>"
    )
    try:
        await message.bot.send_message(ADMIN_ID, info)
        if chat.type != "private":
            await message.answer("chat_id отправлен админу в личку")
    except Exception as e:
        # Админ не писал боту в личку или другой сбой
        logger.warning(f"[CHAT_ID_NOTIFY_FAIL] chat_id={chat.id} err={e}")
        await message.answer("Не удалось отправить админу. Пусть админ напишет боту /start в личку.")


async def cmd_set_greeting(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Отправьте текст, голос или видео для приветствия")
    await state.set_state(GreetingState.waiting)
    await callback.answer()


async def process_greeting(message: Message, state: FSMContext) -> None:
    if message.from_user.id != ADMIN_ID or message.chat.type != "private":
        return
    greet = {}
    if message.voice:
        greet = {"type": "voice", "file_id": message.voice.file_id, "caption": message.caption or ""}
    elif message.video:
        greet = {"type": "video", "file_id": message.video.file_id, "caption": message.caption or ""}
    elif message.text:
        greet = {"type": "text", "text": message.text}
    else:
        await message.answer("Неподдерживаемый тип сообщения")
        return
    await set_greeting(greet)
    await message.answer("Приветствие обновлено", reply_markup=main_menu())
    await state.clear()


async def cmd_set_question(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Отправьте текст вопроса")
    await state.set_state(QuestionState.waiting)
    await callback.answer()


async def process_question(message: Message, state: FSMContext) -> None:
    if message.from_user.id != ADMIN_ID or message.chat.type != "private":
        return
    await set_question(message.text or "")
    await message.answer("Вопрос обновлён", reply_markup=main_menu())
    await state.clear()


async def cmd_buttons(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Управление кнопками", reply_markup=buttons_menu())
    await callback.answer()


async def send_buttons_list(message: Message, action: str) -> None:
    buttons = await get_buttons()
    if not buttons:
        await message.edit_text("Нет кнопок", reply_markup=buttons_menu())
        return
    builder = InlineKeyboardBuilder()
    for label in buttons.keys():
        builder.button(text=label, callback_data=f"{action}:{label}")
    builder.button(text="Назад", callback_data="menu_buttons")
    builder.adjust(1)
    await message.edit_text("Выберите кнопку:", reply_markup=builder.as_markup())


async def show_buttons_for_delete(callback: CallbackQuery) -> None:
    await send_buttons_list(callback.message, "delbtn")
    await callback.answer()


async def show_buttons_for_edit(callback: CallbackQuery) -> None:
    await send_buttons_list(callback.message, "editbtn")
    await callback.answer()


async def process_button_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Введите текст кнопки")
    await state.set_state(ButtonAddState.waiting_label)
    await callback.answer()


async def process_button_label(message: Message, state: FSMContext) -> None:
    await state.update_data(label=message.text or "")
    await message.answer("Введите ответ для кнопки")
    await state.set_state(ButtonAddState.waiting_response)


async def process_button_response(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    label = data.get("label", "")

    # Determine payload type
    if message.voice:
        payload = {
            "type": "voice",
            "file_id": message.voice.file_id,
            "caption": message.caption or "",
        }
    elif message.video:
        cap = message.caption or ""
        cap, cap_flag = _extract_spoiler_from_caption(cap)
        msg_flag = bool(getattr(message, "has_media_spoiler", False))
        payload = {
            "type": "video",
            "file_id": message.video.file_id,
            "caption": cap,
            "spoiler": True if (cap_flag or msg_flag) else False,
        }
    elif message.text:
        payload = {"type": "text", "text": message.text}
    else:
        await message.answer("Неподдерживаемый тип ответа. Отправьте текст, голос или видео")
        return

    await add_button(label, json.dumps(payload))
    await message.answer("Кнопка добавлена", reply_markup=buttons_menu())
    await state.clear()


async def process_button_delete(callback: CallbackQuery) -> None:
    label = callback.data.split(":", 1)[1]
    await remove_button(label)
    await callback.message.edit_text("Кнопка удалена", reply_markup=buttons_menu())
    await callback.answer()


async def process_button_edit_select(callback: CallbackQuery, state: FSMContext) -> None:
    label = callback.data.split(":", 1)[1]
    await state.update_data(label=label)
    await callback.message.edit_text("Введите новый ответ для кнопки")
    await state.set_state(ButtonEditState.waiting_response)
    await callback.answer()


async def process_button_edit_response(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    label = data.get("label", "")

    if message.voice:
        payload = {
            "type": "voice",
            "file_id": message.voice.file_id,
            "caption": message.caption or "",
        }
    elif message.video:
        cap = message.caption or ""
        cap, cap_flag = _extract_spoiler_from_caption(cap)
        msg_flag = bool(getattr(message, "has_media_spoiler", False))
        payload = {
            "type": "video",
            "file_id": message.video.file_id,
            "caption": cap,
            "spoiler": True if (cap_flag or msg_flag) else False,
        }
    elif message.text:
        payload = {"type": "text", "text": message.text}
    else:
        await message.answer("Неподдерживаемый тип ответа. Отправьте текст, голос или видео")
        return

    await add_button(label, json.dumps(payload))
    await message.answer("Кнопка обновлена", reply_markup=buttons_menu())
    await state.clear()


async def cmd_kuplinov_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Настройка доступа к /kuplinov", reply_markup=kuplinov_menu())
    await callback.answer()


async def process_kp_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Введите ID пользователя")
    await state.set_state(KuplinovAddState.waiting_id)
    await callback.answer()


async def process_kp_add_id(message: Message, state: FSMContext) -> None:
    try:
        uid = int(message.text)
        await add_allowed_user(uid)
        await message.answer("Пользователь добавлен", reply_markup=kuplinov_menu())
    except ValueError:
        await message.answer("Неверный ID", reply_markup=kuplinov_menu())
    await state.clear()


async def process_kp_del(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Введите ID для удаления")
    await state.set_state(KuplinovDelState.waiting_id)
    await callback.answer()


async def process_kp_del_id(message: Message, state: FSMContext) -> None:
    try:
        uid = int(message.text)
        await remove_allowed_user(uid)
        await message.answer("Пользователь удалён", reply_markup=kuplinov_menu())
    except ValueError:
        await message.answer("Неверный ID", reply_markup=kuplinov_menu())
    await state.clear()


async def process_kp_list(callback: CallbackQuery) -> None:
    users = await get_allowed_users()
    text = "Разрешённые пользователи:\n" + "\n".join(map(str, users)) if users else "Список пуст"
    await callback.message.edit_text(text, reply_markup=kuplinov_menu())
    await callback.answer()


async def back_main(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Выберите действие:", reply_markup=main_menu())
    await callback.answer()


async def send_preview(callback: CallbackQuery) -> None:
    greet = await get_greeting()
    question = await get_question()
    buttons = await get_buttons()
    markup = None
    if question and buttons:
        builder = InlineKeyboardBuilder()
        target_uid = callback.from_user.id  # preview is for admin
        for lbl in buttons.keys():
            builder.button(text=lbl, callback_data=f"btn:{target_uid}:{_btn_id(lbl)}")
        builder.adjust(1)
        markup = builder.as_markup()
    mention = callback.from_user.mention_html()
    if greet["type"] == "voice":
        caption = greet.get("caption", "").replace("{user}", mention)
        if question:
            q_text = question.replace("{user}", mention)
            caption = f"{caption}\n\n{q_text}" if caption else q_text
        await callback.message.answer_voice(greet["file_id"], caption=caption, reply_markup=markup)
    elif greet["type"] == "video":
        caption = greet.get("caption", "").replace("{user}", mention)
        if question:
            q_text = question.replace("{user}", mention)
            caption = f"{caption}\n\n{q_text}" if caption else q_text
        await callback.message.answer_video(greet["file_id"], caption=caption, reply_markup=markup)
    else:
        text = greet.get("text", "").replace("{user}", mention)
        if question:
            q_text = question.replace("{user}", mention)
            text = f"{text}\n\n{q_text}" if text else q_text
        await callback.message.answer(text, reply_markup=markup)
    await callback.answer()


async def welcome(message: Message) -> None:
    if not is_group_allowed(message.chat.id):
        return
    greet = await get_greeting()
    question = await get_question()
    buttons = await get_buttons()
    # Ignore bots (including the bot itself) when users are added
    bot_id = getattr(message.bot, "id", None)
    for member in message.new_chat_members:
        if member.is_bot or (bot_id and member.id == bot_id):
            continue
        mention = member.mention_html()
        markup = None
        q_text = question.replace("{user}", mention) if question and buttons else ""
        if question and buttons:
            builder = InlineKeyboardBuilder()
            target_uid = member.id
            for lbl in buttons.keys():
                builder.button(text=lbl, callback_data=f"btn:{target_uid}:{_btn_id(lbl)}")
            builder.adjust(1)
            markup = builder.as_markup()
        g_type = greet.get("type")
        if g_type == "voice":
            caption = greet.get("caption", "")
            caption = caption.replace("{user}", mention) if "{user}" in caption else f"{caption} {mention}".strip()
            if q_text:
                caption = f"{caption}\n\n{q_text}" if caption else q_text
            await message.answer_voice(greet.get("file_id"), caption=caption, reply_markup=markup)
        elif g_type == "video":
            caption = greet.get("caption", "")
            caption = caption.replace("{user}", mention) if "{user}" in caption else f"{caption} {mention}".strip()
            if q_text:
                caption = f"{caption}\n\n{q_text}" if caption else q_text
            await message.answer_video(greet.get("file_id"), caption=caption, reply_markup=markup)
        else:
            text = greet.get("text", "")
            text = text.replace("{user}", mention) if "{user}" in text else f"{text} {mention}".strip()
            if q_text:
                text = f"{text}\n\n{q_text}" if text else q_text
            await message.answer(text, reply_markup=markup)


async def on_button(query: CallbackQuery) -> None:
    # Allow in group or admin preview
    in_group =  is_group_allowed(query.message.chat.id)
    in_admin_preview = (query.message.chat.type == "private" and query.from_user.id == ADMIN_ID)
    if not (in_group or in_admin_preview):
        await query.answer()
        return

    # Parse callback data: btn:<target_uid>:<hash>
    data = (query.data or "")
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "btn":
        await query.answer()
        return

    try:
        target_uid = int(parts[1])
    except ValueError:
        await query.answer()
        return
    hid = parts[2]

    # Only admin or intended user can press
    if query.from_user.id not in (ADMIN_ID, target_uid):
        await query.answer("Эта кнопка не для вас", show_alert=True)
        return

    buttons = await get_buttons()
    # find label by hash
    label = None
    for lbl in buttons.keys():
        if _btn_id(lbl) == hid:
            label = lbl
            break

    if not label:
        await query.answer("Кнопка устарела, обновите сообщение", show_alert=True)
        return

    resp = buttons.get(label)

    # delete/replace original message with the response
    try:
        await query.message.delete()
    except Exception:
        # ignore deletion errors
        pass

    # Mention: by default use the presser
    mention = query.from_user.mention_html()

    # Backward compatibility: plain text string
    if isinstance(resp, str):
        text = resp.replace("{user}", mention)
        await query.message.answer(text)
        await query.answer()
        return

    rtype = resp.get("type")
    if rtype == "video":
        caption = (resp.get("caption") or "").replace("{user}", mention)
        has_spoiler = bool(resp.get("spoiler"))
        await query.message.answer_video(resp.get("file_id"), caption=caption or None, has_spoiler=has_spoiler)
    elif rtype == "voice":
        caption = (resp.get("caption") or "").replace("{user}", mention)
        await query.message.answer_voice(resp.get("file_id"), caption=caption or None)
    else:
        text = (resp.get("text") or "").replace("{user}", mention)
        await query.message.answer(text)

    await query.answer()


async def track_history(message: Message) -> None:
    if not is_group_allowed(message.chat.id):
        return
    if not message.text or message.text.startswith("/"):
        return
    user = message.from_user.full_name
    chat_history.append(f"{user}: {message.text}")
    logger.info(f"[history] {user}: {message.text}")


async def cmd_kuplinov(message: Message) -> None:
    if not is_group_allowed(message.chat.id):
        title = message.chat.title or ""
        logger.warning(f"[UNALLOWED_CHAT] chat_id={message.chat.id} title='{title}' type={message.chat.type}")
        return
    ok, wait = await check_rate(message.from_user.id)
    if not ok:
        await message.answer(f"Подожди {wait} сек.")
        return
    if not DEEPSEEK_API_KEY:
        await message.answer("DeepSeek API key is missing")
        return
    context = "\n".join(chat_history)
    logger.info(f"Context for /kuplinov:\n{context}")
    prompt = (
        "Сочини шутку по шаблону \"А вот Куплинов (что-то там)\" или \"А вот Куплинов не (что-то там)\". "
        "Без цензуры. Пример: А вот Куплинов бы уже прошел эту игру, "
        "А вот Куплинов уже показал жопу, А вот Куплинов не прогревал своих зрителей и т.д. "
        "Старайся шутить постиронично и лаконично, как Мэддисон ака JoePeach"
        "Ответ дай одним предложением, только шутку, больше ничего не добавляй. "
        "Для основы шутки бери сообщения из чата которые приведены ниже:\n"
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
    dp.message.register(cmd_start, Command("start"), F.from_user.id == ADMIN_ID, F.chat.type == "private")
    dp.message.register(cmd_chatid, Command("chatid"))
    dp.callback_query.register(cmd_set_greeting, F.data == "menu_greeting", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(cmd_set_question, F.data == "menu_question", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(cmd_buttons, F.data == "menu_buttons", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(show_buttons_for_delete, F.data == "btn_del", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(show_buttons_for_edit, F.data == "btn_edit", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(process_button_add, F.data == "btn_add", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(process_button_delete, F.data.startswith("delbtn:"), F.from_user.id == ADMIN_ID)
    dp.callback_query.register(
        process_button_edit_select, F.data.startswith("editbtn:"), F.from_user.id == ADMIN_ID, StateFilter("*")
        )
    dp.callback_query.register(cmd_kuplinov_menu, F.data == "menu_kuplinov", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(process_kp_add, F.data == "kp_add", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(process_kp_del, F.data == "kp_del", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(process_kp_list, F.data == "kp_list", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(send_preview, F.data == "menu_preview", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(back_main, F.data == "back_main", F.from_user.id == ADMIN_ID)
    dp.message.register(process_greeting, GreetingState.waiting)
    dp.message.register(process_question, QuestionState.waiting)
    dp.message.register(process_button_label, ButtonAddState.waiting_label)
    dp.message.register(process_button_response, ButtonAddState.waiting_response)
    dp.message.register(process_button_edit_response, ButtonEditState.waiting_response)
    dp.message.register(process_kp_add_id, KuplinovAddState.waiting_id)
    dp.message.register(process_kp_del_id, KuplinovDelState.waiting_id)
    dp.message.register(welcome, F.new_chat_members)
    dp.message.register(cmd_kuplinov, Command("kuplinov"))
    dp.callback_query.register(on_button, F.data.startswith("btn:"))
    dp.message.register(track_history, F.text)


async def main() -> None:
    global db
    db = await init_db()
    setup_logging()
    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())
    register_handlers(dp)
    logger.info("bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

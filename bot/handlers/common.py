import asyncio
import random

import aiohttp
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import (
    ADMIN_ID,
    DEEPSEEK_API_KEY,
    DEEPSEEK_URL,
    is_group_allowed,
    logger,
)
from ..db import check_rate, get_buttons, get_greeting, get_question
from ..history import add_message, get_history, increment_count
from ..personalities import MAIN_PROMPT, PERSONALITIES, SLANG_DICT
from ..utils import btn_id


async def welcome(message: Message) -> None:
    if not is_group_allowed(message.chat.id):
        return
    greet = await get_greeting()
    question = await get_question()
    buttons = await get_buttons()
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
                builder.button(text=lbl, callback_data=f"btn:{target_uid}:{btn_id(lbl)}")
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
    in_group = is_group_allowed(query.message.chat.id)
    in_admin_preview = (query.message.chat.type == "private" and query.from_user.id == ADMIN_ID)
    if not (in_group or in_admin_preview):
        await query.answer()
        return
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
    if query.from_user.id not in (ADMIN_ID, target_uid):
        await query.answer("Эта кнопка не для вас", show_alert=True)
        return
    buttons = await get_buttons()
    label = None
    for lbl in buttons.keys():
        if btn_id(lbl) == hid:
            label = lbl
            break
    if not label:
        await query.answer("Кнопка устарела, обновите сообщение", show_alert=True)
        return
    resp = buttons.get(label)
    try:
        await query.message.delete()
    except Exception:
        pass
    mention = query.from_user.mention_html()
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


def _build_prompt(personality_key: str, context: str, priority_text: str) -> str:
    personality = PERSONALITIES.get(personality_key, {})
    slang = ", ".join(f"{k}={v}" for k, v in SLANG_DICT.items())
    return (
        MAIN_PROMPT
        + "\n"
        + (f"Словарь сленга: {slang}\n" if slang else "")
        + personality.get("prompt", "")
        + "\n"
        + (f"Приоритетное сообщение, на которое нужно ответить: {priority_text}\n" if priority_text else "")
        + "История чата (включая ответы бота; их нужно избегать повторять, не зацикливайся):\n"
        + context
    )


async def respond_with_personality(
    message: Message,
    personality_key: str,
    priority_text: str,
    error_message: str = "Не удалось получить ответ.",
) -> None:
    if not is_group_allowed(message.chat.id):
        title = message.chat.title or ""
        logger.warning(
            f"[UNALLOWED_CHAT] chat_id={message.chat.id} title='{title}' type={message.chat.type}"
        )
        return
    ok, wait = await check_rate(message.from_user.id)
    if not ok:
        await message.answer(f"Подожди {wait} сек.")
        return
    if not DEEPSEEK_API_KEY:
        await message.answer("DeepSeek API key is missing")
        return
    await message.bot.send_chat_action(message.chat.id, "typing")
    history = await get_history(message.chat.id, limit=10)
    context = "\n".join(history)
    prompt = _build_prompt(personality_key, context, priority_text)
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
            payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}]}
            async with session.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=30) as resp:
                data = await resp.json()
        reply = data["choices"][0]["message"]["content"].strip()
    except Exception as exp:
        logger.error(f"[ERROR] while accessing deepseek {exp}")
        reply = error_message
    personality_name = PERSONALITIES.get(personality_key, {}).get("name", personality_key)
    for mes_ in reply.split("</br>"):
        text = mes_.strip()
        if text:
            await message.answer(f"{personality_name}:\n{text}")
            await add_message(message.chat.id, f"{personality_name}: {text}")
            await asyncio.sleep(0.7)


async def cmd_kuplinov(message: Message) -> None:
    await respond_with_personality(message, "Kuplinov", message.text)


async def cmd_joepeach(message: Message) -> None:
    await respond_with_personality(message, "JoePeach", message.text)


async def cmd_mrazota(message: Message) -> None:
    await respond_with_personality(message, "Mrazota", message.text)


def _personality_key_from_text(text: str) -> str | None:
    name = text.split(":", 1)[0].strip()
    for key, info in PERSONALITIES.items():
        if info.get("name") == name:
            return key
    return None


async def handle_message(message: Message) -> None:
    if not is_group_allowed(message.chat.id):
        return
    if not message.text or message.text.startswith("/"):
        return
    user = message.from_user.full_name
    await add_message(message.chat.id, f"{user}: {message.text}")
    bot_id = getattr(message.bot, "id", None)
    triggered = False
    if len(message.text) > 10:
        triggered = await increment_count(message.chat.id)
    if (
        message.reply_to_message
        and message.reply_to_message.from_user
        and bot_id
        and message.reply_to_message.from_user.id == bot_id
    ):
        key = _personality_key_from_text(message.reply_to_message.text or "")
        if key:
            await respond_with_personality(message, key, message.text)
            return
    if triggered:
        key = random.choice(list(PERSONALITIES.keys()))
        await respond_with_personality(message, key, message.text)


import asyncio
import json
import random

from httpx import AsyncClient, AsyncHTTPTransport

from aiogram import Bot
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..auto_reply import CHANNEL as AUTO_REPLY_CHANNEL
from ..config import (
    ADMIN_ID,
    DEEPSEEK_API_KEY,
    DEEPSEEK_URL,
    is_group_allowed,
    logger,
)
from ..db import check_rate, get_buttons, get_greeting, get_question
from ..history import add_message, get_history, get_thread, increment_count, redis
from ..personalities import MAIN_PROMPT, SLANG_DICT, get_mood_prompt, get_prompt
from ..utils import btn_id


transport = AsyncHTTPTransport(retries=3)


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


def _build_prompt(
    personality_key: str,
    context: str,
    priority_text: str,
    additional_context: str,
) -> tuple[str, str]:
    prompt = get_prompt(personality_key)
    mood = get_mood_prompt(personality_key)
    slang = ", ".join(f"{k}={v}" for k, v in SLANG_DICT.items())
    system_prompt = "\n".join(
        [
            MAIN_PROMPT,
            (
                f"Словарь сленга (ИСПОЛЬЗУЙ ТОЛЬКО ДЛЯ ПОНИМАНИЯ, НЕ ВСТАВЛЯЙ В ОТВЕТЫ): {slang}\n"
                if slang
                else ""
            ),
            prompt,
            mood,
            (additional_context if additional_context else ""),
            "Сначала идет сообщение пользователя (если есть), затем история чата:\n",
        ]
    )
    if priority_text:
        user_prompt = f"{priority_text}\n\n{context}" if context else priority_text
    else:
        user_prompt = context
    return system_prompt, user_prompt


async def _httpx_post_with_retries(url: str, json_payload: dict, headers: dict, max_attempts: int = 3, timeout: int = 30) -> dict:
    """POST with retries. Retries on network errors and 5xx/429 responses."""
    attempt = 0
    backoff = 1
    while attempt < max_attempts:
        attempt += 1
        try:
            async with AsyncClient(transport=transport, timeout=timeout) as client:
                resp = await client.post(url, json=json_payload, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning(f"[DEEPSEEK_FAIL] attempt={attempt} err={e}")
            if attempt >= max_attempts:
                raise
            await asyncio.sleep(backoff)
            backoff *= 2


async def respond_with_personality(
    message: Message,
    personality_key: str,
    priority_text: str,
    error_message: str = "Не удалось получить ответ.",
    reply_to: Message | None = None,
    additional_context: str | None = None,
) -> None:
    if not is_group_allowed(message.chat.id):
        title = message.chat.title or ""
        logger.warning(
            f"[UNALLOWED_CHAT] chat_id={message.chat.id} title='{title}' type={message.chat.type}"
        )
        return

    user = message.from_user or message.sender_chat
    if not user:
        return
    ok, wait = await check_rate(user.id)
    if not ok:
        await message.answer(f"Подожди {wait} сек.")
        return
    await message.bot.send_chat_action(message.chat.id, "typing")
    logger.info(f"[REQUEST] personality={personality_key} user={user.id}")
    if reply_to:
        history = await get_thread(message.chat.id, reply_to.message_id)
    else:
        history = await get_history(message.chat.id, limit=10)
    context = "\n".join(history)
    system_prompt, user_prompt = _build_prompt(personality_key, context, priority_text, additional_context)

    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    _msgs = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    payload = {"model": "deepseek-chat", "messages": _msgs}
    try:
        data = await _httpx_post_with_retries(DEEPSEEK_URL, payload, headers, max_attempts=3, timeout=30)
    except Exception as e:
        logger.error(f"[DEEPSEEK_ERROR] personality={personality_key} err={e}")
        if reply_to:
            await reply_to.reply(error_message)
        else:
            await message.answer(error_message)
        return
    reply = data["choices"][0]["message"]["content"].strip()

    for mes_ in reply.split("</br>"):
        text = mes_.strip()
        if text:
            if reply_to:
                sent = await reply_to.reply(text)
                await add_message(message.chat.id, sent.message_id, text, reply_to.message_id)
            else:
                sent = await message.answer(text)
                await add_message(message.chat.id, sent.message_id, text, message.message_id)
            await asyncio.sleep(0.7)


async def respond_with_personality_to_chat(
    bot: Bot,
    chat_id: int,
    personality_key: str,
    priority_text: str,
    error_message: str = "Не удалось получить ответ.",
    reply_to_message_id: int | None = None,
    additional_context: str | None = None,
) -> None:
    await bot.send_chat_action(chat_id, "typing")
    logger.info(f"[REQUEST] personality={personality_key} chat={chat_id}")
    if reply_to_message_id:
        history = await get_thread(chat_id, reply_to_message_id)
    else:
        history = await get_history(chat_id, limit=10)
    context = "\n".join(history)
    system_prompt, user_prompt = _build_prompt(
        personality_key, context, priority_text, additional_context
    )
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    _msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    payload = {"model": "deepseek-chat", "messages": _msgs}
    try:
        data = await _httpx_post_with_retries(
            DEEPSEEK_URL, payload, headers, max_attempts=3, timeout=30
        )
    except Exception as e:
        logger.error(f"[DEEPSEEK_ERROR] personality={personality_key} err={e}")
        await bot.send_message(chat_id, error_message, reply_to_message_id=reply_to_message_id)
        return
    reply = data["choices"][0]["message"]["content"].strip()
    for mes_ in reply.split("</br>"):
        text = mes_.strip()
        if text:
            sent = await bot.send_message(
                chat_id, text, reply_to_message_id=reply_to_message_id
            )
            await add_message(chat_id, sent.message_id, text, reply_to_message_id)
            await asyncio.sleep(0.7)


async def cmd_kuplinov(message: Message) -> None:
    priority = message.reply_to_message.text if message.reply_to_message else ""
    await respond_with_personality(message, "Kuplinov", priority)


async def cmd_joepeach(message: Message) -> None:
    priority = message.reply_to_message.text if message.reply_to_message else ""
    await respond_with_personality(message, "JoePeach", priority)


async def cmd_mrazota(message: Message) -> None:
    priority = message.reply_to_message.text if message.reply_to_message else ""
    await respond_with_personality(
        message,
        "Mrazota",
        priority,
        additional_context="Ты можешь разделить ответ на несколько строк на основе </br> в тексте ответа. Обязательно используй это. Не больше трех отдельных строк!!!!",
    )


def should_count_for_random(message: Message, personality_key: str) -> bool:
    """Return True if message should increment random reply counter."""
    return (
        message.chat.type in {"private", "group", "supergroup"}
        and len(message.text or "") > 10
        and personality_key == "JoePeach"
    )

async def handle_message(message: Message, personality_key: str) -> None:
    if not is_group_allowed(message.chat.id):
        return
    if (
        not message.text
        or message.text.startswith("/")
        or (message.from_user and message.from_user.is_bot)
    ):
        return
    user_obj = message.from_user or message.sender_chat
    if not user_obj:
        return
    user_name = getattr(user_obj, "full_name", getattr(user_obj, "title", ""))
    reply_id = message.reply_to_message.message_id if message.reply_to_message else None
    await add_message(message.chat.id, message.message_id, f"{user_name}: {message.text}", reply_id)
    bot_id = getattr(message.bot, "id", None)
    triggered = False
    if should_count_for_random(message, personality_key):
        logger.info("TRIGGERED LONG MESSAGE")
        triggered = await increment_count(message.chat.id, message.message_id)
    if (
        message.reply_to_message
        and bot_id
        and message.reply_to_message.from_user.id == bot_id
    ):
        await respond_with_personality(message, personality_key, message.text, reply_to=message)
        return
    if triggered and random.random() < 0.5:
        logger.info("TRIGGERED AUTO REPLY")
        names = ["Kuplinov", "JoePeach", "Mrazota"]
        personality = random.choice(names)
        payload = {
            "chat_id": message.chat.id,
            "msg_id": message.message_id,
            "text": message.text,
            "personality": personality,
        }
        await redis.publish(AUTO_REPLY_CHANNEL, json.dumps(payload))

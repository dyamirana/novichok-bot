import asyncio
import json
import random
from typing import Any

from httpx import AsyncClient, AsyncHTTPTransport

from aiogram import Bot
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..auto_reply import CHANNEL as AUTO_REPLY_CHANNEL
from ..config import (
    ADMIN_ID,
    DEEPSEEK_API_KEY,
    DEEPSEEK_PRESENCE_PENALTY,
    DEEPSEEK_TEMPERATURE,
    DEEPSEEK_URL,
    is_group_allowed,
    logger,
)
from ..db import check_rate, get_buttons, get_greeting, get_question
from ..history import add_message, get_history, get_thread, increment_count, redis
from ..personalities import MAIN_PROMPT, SLANG_DICT, get_mood_prompt, get_prompt
from ..utils import btn_id
from ..tarot import draw_cards


transport = AsyncHTTPTransport(retries=3)

COMMENT_MERGE_WINDOW = 10
_comment_buffers: dict[tuple[int, int], dict[str, Any]] = {}


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


def _build_system_prompt(personality_key: str, additional_context: str | None) -> str:
    """Construct the system prompt for a given personality."""

    prompt = get_prompt(personality_key)
    mood = get_mood_prompt(personality_key)
    slang = ", ".join(f"{k}={v}" for k, v in SLANG_DICT.items())
    parts = [
        MAIN_PROMPT,
        (
            f"Словарь сленга (ИСПОЛЬЗУЙ ТОЛЬКО ДЛЯ ПОНИМАНИЯ, НЕ ВСТАВЛЯЙ В ОТВЕТЫ): {slang}\n"
            if slang
            else ""
        ),
        prompt,
        mood,
        (additional_context if additional_context else ""),
    ]
    return "\n".join(parts)


def _history_to_messages(system_prompt: str, history: list[dict]) -> list[dict]:
    """Build the message list for the DeepSeek API, keeping names separate."""
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        item = {
            "role": msg.get("role", "user"),
            "content": msg.get("content", ""),
        }
        name = msg.get("name")
        if name:
            item["name"] = name
        messages.append(item)
    return messages


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
    reply_to_comment: Message | None = None,
    additional_context: str | None = None,
    model: str = "deepseek-chat",
    delay_range: tuple[int, int] | None = None,
) -> None:
    if not is_group_allowed(message.chat.id):
        title = message.chat.title or ""
        logger.warning(
            f"[UNALLOWED_CHAT] chat_id={message.chat.id} title='{title}' type={message.chat.type}"
        )
        return

    user = message.from_user or message.sender_chat
    if not user or not message.from_user:
        return
    thread_id = getattr(message, "message_thread_id", 0) or 0
    user_id = message.from_user.id
    if delay_range:
        await asyncio.sleep(random.uniform(*delay_range))
    await message.bot.send_chat_action(message.chat.id, "typing")
    logger.info(f"[REQUEST] personality={personality_key} user={user.id}")
    if reply_to and not reply_to_comment:
        history = await get_thread(
            message.chat.id, user_id, thread_id, reply_to.message_id
        )
        logger.info(f"[RESPONSE] history={history}")
    else:
        history = await get_history(message.chat.id, user_id, thread_id, limit=10)

    logger.info(f"[HISTORY] {history}")
    system_prompt = _build_system_prompt(personality_key, additional_context)
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}

    _msgs = _history_to_messages(system_prompt, history)
    if priority_text and (
        not history or history[-1].get("content") != priority_text
    ):
        _msgs.append({"role": "user", "content": priority_text})

    payload = {
        "model": model,
        "messages": _msgs,
        "temperature": DEEPSEEK_TEMPERATURE,
        "presence_penalty": DEEPSEEK_PRESENCE_PENALTY,
    }
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
    already_replied = False
    for mes_ in reply.split("</br>"):
        text = mes_.strip()

        if text:
            if reply_to and not already_replied:
                sent = await reply_to.reply(text)
                await add_message(
                    message.chat.id,
                    user_id,
                    thread_id,
                    sent.message_id,
                    text,
                    reply_to.message_id,
                    role="assistant",
                    name=personality_key,
                )
                already_replied = True
            else:
                if reply_to_comment:
                    parent = getattr(reply_to_comment, "reply_to_message", None)
                    while parent and getattr(parent, "reply_to_message", None):
                        parent = parent.reply_to_message
                    target = parent or reply_to_comment
                    sent = await target.reply(text)
                    reply_id = target.message_id
                else:
                    sent = await message.answer(text)
                    reply_id = message.message_id
                await add_message(
                    message.chat.id,
                    user_id,
                    thread_id,
                    sent.message_id,
                    text,
                    reply_id,
                    role="assistant",
                    name=personality_key,
                )
            await asyncio.sleep(0.7)


async def respond_with_personality_to_chat(
    bot: Bot,
    chat_id: int,
    user_id: int,
    thread_id: int | None,
    personality_key: str,
    priority_text: str,
    error_message: str = "Не удалось получить ответ.",
    reply_to_message_id: int | None = None,
    additional_context: str | None = None,
    model: str = "deepseek-chat",
    delay_range: tuple[int, int] | None = None,
) -> None:
    if delay_range:
        await asyncio.sleep(random.uniform(*delay_range))
    await bot.send_chat_action(chat_id, "typing")
    logger.info(f"[REQUEST] personality={personality_key} chat={chat_id}")
    if reply_to_message_id:
        history = await get_thread(chat_id, user_id, thread_id, reply_to_message_id)
    else:
        history = await get_history(chat_id, user_id, thread_id, limit=10)

    system_prompt = _build_system_prompt(personality_key, additional_context)
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    _msgs = _history_to_messages(system_prompt, history)
    if priority_text and (
        not history or history[-1].get("content") != priority_text
    ):
        _msgs.append({"role": "user", "content": priority_text})

    payload = {
        "model": model,
        "messages": _msgs,
        "temperature": DEEPSEEK_TEMPERATURE,
        "presence_penalty": DEEPSEEK_PRESENCE_PENALTY,
    }
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
            await add_message(
                chat_id,
                user_id,
                thread_id,
                sent.message_id,
                text,
                reply_to_message_id,
                role="assistant",
                name=personality_key,
            )
            await asyncio.sleep(0.7)


async def cmd_kuplinov(message: Message) -> None:
    priority = message.reply_to_message.text if message.reply_to_message else ""
    try:
        await message.delete()
    except Exception:
        pass
    await respond_with_personality(
        message,
        "Kuplinov",
        priority,
        reply_to=message.reply_to_message,
    )


async def cmd_joepeach(message: Message) -> None:
    priority = message.reply_to_message.text if message.reply_to_message else ""
    try:
        await message.delete()
    except Exception:
        pass
    await respond_with_personality(
        message,
        "JoePeach",
        priority,
        reply_to=message.reply_to_message,
    )


async def cmd_mrazota(message: Message) -> None:
    priority = message.reply_to_message.text if message.reply_to_message else ""
    try:
        await message.delete()
    except Exception:
        pass
    await respond_with_personality(
        message,
        "Mrazota",
        priority,
        reply_to=message.reply_to_message,
        additional_context="Ты можешь разделить ответ на несколько строк на основе </br> в тексте ответа. Обязательно используй это. Не больше трех отдельных строк!!!!",
    )


async def cmd_taro(message: Message) -> None:
    """Make a tarot spread and let Mrazota interpret it."""
    if not message.reply_to_message or not (message.reply_to_message.text or "").strip():
        await message.reply("Команда должна быть ответом на сообщение с вопросом")
        return
    question = message.reply_to_message.text.strip()
    cards = draw_cards(3)
    cards_text = ", ".join(cards)
    await message.reply_to_message.reply(f"Выпали карты: {cards_text}")
    additional = (
        "Сейчас ты гадаешь на таро. Отвечай только трактовкой выпавших карт "
        "в контексте вопроса пользователя и ничего более. "
        f"Вопрос пользователя: '{question}'. Выпали карты: {cards_text}. "
        "Сохраняй манеру речи Мразоты и объясняй значение каждой карты, "
        "например: 'у тебя получится потому что эта карта говорит...'."
    )
    await respond_with_personality(
        message,
        "Mrazota",
        question,
        reply_to=message.reply_to_message,
        additional_context=additional,
        model="deepseek-reasoner",
    )


def should_count_for_random(message: Message, personality_key: str) -> bool:
    """Return True if message should increment random reply counter."""
    return (
        message.chat.type in {"private", "group", "supergroup"}
        and len(message.text or "") > 10
        and personality_key == "JoePeach"
    )


async def _process_comment_buffer(key: tuple[int, int], personality_key: str) -> None:
    try:
        await asyncio.sleep(COMMENT_MERGE_WINDOW)
    except asyncio.CancelledError:
        return
    data = _comment_buffers.pop(key, None)
    if not data:
        return
    text = " ".join(data["texts"])
    message = data["last_message"]
    await respond_with_personality(
        message,
        personality_key,
        text,
        reply_to=message,
        reply_to_comment=message,
        delay_range=(15, 25),
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
    if not user_obj or not message.from_user:
        return
    thread_id = getattr(message, "message_thread_id", 0) or 0
    user_id = message.from_user.id
    user_name = getattr(user_obj, "full_name", getattr(user_obj, "title", ""))
    reply_id = message.reply_to_message.message_id if message.reply_to_message else None
    await add_message(
        message.chat.id,
        user_id,
        thread_id,
        message.message_id,
        message.text,
        reply_id,
        role="user",
        name=user_name,
    )
    bot_id = getattr(message.bot, "id", None)
    triggered = False
    if should_count_for_random(message, personality_key):
        logger.info("TRIGGERED LONG MESSAGE")
        triggered = await increment_count(message.chat.id, message.message_id)
    if (
        personality_key == "Mrazota"
        and message.reply_to_message
        and (
            getattr(message.reply_to_message, "is_automatic_forward", False)
            or (
                getattr(message.reply_to_message, "sender_chat", None)
                and getattr(message.reply_to_message.sender_chat, "type", "")
                == "channel"
            )
        )
    ):
        user_id = getattr(user_obj, "id", None)
        if user_id is None:
            return
        key = (message.chat.id, user_id)
        data = _comment_buffers.get(key)
        if data:
            data["texts"].append(message.text)
            data["last_message"] = message
            data["task"].cancel()
        else:
            data = {"texts": [message.text], "last_message": message}
            _comment_buffers[key] = data
        data["task"] = asyncio.create_task(_process_comment_buffer(key, personality_key))
        return
    if (
        message.reply_to_message
        and bot_id
        and message.reply_to_message.from_user.id == bot_id
    ):
        await respond_with_personality(
            message,
            personality_key,
            message.text,
            reply_to=message,
            delay_range=(15, 25),
        )
        return
    if triggered and random.random() < 0.5:
        logger.info("TRIGGERED AUTO REPLY")
        names = ["Kuplinov", "JoePeach", "Mrazota"]
        personality = random.choice(names)
        payload = {
            "chat_id": message.chat.id,
            "user_id": user_id,
            "thread_id": thread_id,
            "msg_id": message.message_id,
            "text": message.text,
            "personality": personality,
        }
        await redis.publish(AUTO_REPLY_CHANNEL, json.dumps(payload))

import aiohttp
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import (
    ADMIN_ID,
    DEEPSEEK_API_KEY,
    DEEPSEEK_URL,
    chat_history,
    is_group_allowed,
    logger,
)
from ..db import check_rate, get_buttons, get_greeting, get_question
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

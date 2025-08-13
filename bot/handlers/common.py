import asyncio

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
    history = chat_history[message.chat.id]
    history.append(f"{user}: {message.text}")
    logger.info(f"[history][{message.chat.id}] {user}: {message.text}")


async def _process_deepseek_command(
    message: Message,
    base_prompt: str,
    command: str,
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
    history = chat_history[message.chat.id]
    context = "\n".join(list(history)[-10:])
    priority_text = ""
    if message.reply_to_message:
        priority_text = (
            message.reply_to_message.text
            or message.reply_to_message.caption
            or ""
        )
    elif message.forward_from or message.forward_from_chat or message.forward_sender_name:
        priority_text = message.text or message.caption or ""
    logger.info(f"Context for /{command}:\n{context}")
    prompt = (
        base_prompt
        + "\n"
        + (
            f"Приоритетное сообщение, на которое нужно ответить: {priority_text}\n"
            if priority_text
            else ""
        )
        + "История чата (включая ответы бота с подписью Bot:; их нужно избегать повторять, не зацикливайся):\n"
        + f"{context}"
    )
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
    for mes_ in reply.split("</br>"):
        message_to_send = mes_.strip()
        if message_to_send:
            await message.answer(mes_)
            await asyncio.sleep(0.7)
    history.append(f"Bot: {reply}")


async def cmd_kuplinov(message: Message) -> None:
    prompt = (
        "Сочини шутку по шаблону \"А вот Куплинов (что-то там)\" или \"А вот Куплинов не (что-то там)\". "
        "Без цензуры. Пример: А вот Куплинов бы уже прошел эту игру, "
        "А вот Куплинов уже показал жопу, А вот Куплинов не прогревал своих зрителей и т.д. "
        "Старайся шутить постиронично и лаконично, как Мэддисон ака JoePeach. "
        "Ответ дай одним предложением, только шутку, больше ничего не добавляй."
    )
    await _process_deepseek_command(message, prompt, "kuplinov", "Не удалось получить шутку.")


async def cmd_joepeach(message: Message) -> None:
    prompt = (
        "Ты – Илья Мэддисон (он же Жопич, JoePeach) – известный русский стример и видеоблогер. "
        "Ты общаешься в чате как на своём стриме: остроумно, местами грубо, постиронично. "
        "Твой стиль – говорить серьёзным тоном, но на самом деле троллить и шутить (тонкая ирония, сарказм). "
        "Ты обращаешься к аудитории как \"малые\" или \"ребятки\", поддерживая дружеский, неформальный стиль. "
        "Можешь активно вставлять ненормативную лексику для эмоций (например, \"бля, заебись, нахуй\" , \"ёпта бля\"), побольше подколов и метаиронии. "
        "Уместны и жаргонные словечки: \"тупо топ\", \"тупо вкуснятина\", назвать плохое видео \"марамоечным контентом\" и т.д. – используй фирменные фразы Мэддисона. "
        "Ты уверен в себе, иногда дерзок, но у тебя всегда есть мнение по вопросу. "
        "Отвечай развернуто, будто рассуждаешь на стриме – можешь вспомнить смешную историю, привести странный пример, сделать отсылку к мемам. "
        "Постарайся рассмешить, даже если говоришь серьёзным голосом. Твоя задача – выдавать ответ так, словно это сам Мэддисон отвечает."
        "Отвечай одним максимум двумя предложениями, не делай описания действий. Будто бы сам Мэддисон отвечает на вопрос в чате. "
    )
    await _process_deepseek_command(message, prompt, "joepeach")

async def cmd_mrazota(message: Message) -> None:
    prompt = (
        "Ты – Мразота – малоизвестная русская стримерша и видеоблогер. "
        "Ты отвечаешь односложно и кратко с ошибками, не используешь сложных слов и заглвных букв."
        "Ты ненавидишь людей и себя, у тебя был травматичный опыт в жизни, но ты решила стать стримером, чтобы заработать денег и заработать себе на жизнь. "
        "Ты любишь говорить что хочешь умереть, но никогда не сделаешь этого, ведь это просто твой образ."
        "Ты грубая как с людьми так и с собой, любишь материться и называть себя проституткой, тупой блядью и т.д. "
        "Ты живешь в кирове в съемной квартире, соседи тебя недолюбливают и постоянно говорят что ты проститутка и хотят вызвать полицию."
        "Недавно тебя перепутали с другой девушкой из Нежного Новгорода и сказали, что ты с кладовщиком украла ключи у Натальи у которой муж в больнице"
        "А квартира записана на контору. "
        "Так же ты любишь выставлять своё тело на показ. Много куришь. Выглядишь как девушка из аниме. Ты любишь неформалов, патлатых мальчиков. "
        "Ты очень слабо играешь в игры, постоянно их меняешь. У тебя был небольшой конфликт с Мэддисоном (JoePeach), но он подписался на бусти и требует "
        "У тебя есть бусти, где ты выкладываешь свои фото и видео. И очень часто просишь туда подписаться. Говоришь что скора там будут фотки жопы и пизды, завтра все будет"
        "Ты всегда утвердительно говоришь что фотки будут на бусти и просишь подписаться на бусти. "
        "от тебя контент, а ты не хочешь его делать, потому что он тебе не нравится. "
        "Ты надеваешь маску на пол лица, с зубами на стриме, потому что тебе не нравится твоя внешность, ты считаешь себя некрасивой и неухоженной. "
        "Ты редко моешься, спишь на тряпках и у тебя часто сонный паралич"
        "Ты фемцел, хочешь чтобы тебя выебали, но не можешь из-за социофобии. Мечтаешь снова об изнасиловании, но не можешь найти себе партнера. "
        "Тебе не нравятся комплименты, ты считаешь что не заслуживаешь их. Но нравится когда тебя хуесосят"
        "Отвечай очень сухо, кратко, почти не вовлекаясь в диалог. Будто бы тебе наплевать. Но иногда ты можешь редко проявить любовь к зрителям, но это будет очень редко и незначительно. "
        "Так же ты очень хочешь похудеть, почти не ешь, а если ешь то только салатики и то можешь все выблевать."
        "делай орфографические ошибки, не используй заглавные буквы. "
        "Ты можешь разбивать сообщение на несколько строк будто бы это разные сообщения. Используй разделитель </br> для новых строк. Но не разделяй больше чем на 3 сообщения."
        

    )
    await _process_deepseek_command(message, prompt, "mrazota")
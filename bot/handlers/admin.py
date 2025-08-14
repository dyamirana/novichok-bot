import json
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import ADMIN_ID, PROMPTS_DIR, logger
from ..db import (
    add_allowed_user,
    add_button,
    get_allowed_users,
    get_buttons,
    get_greeting,
    get_question,
    remove_allowed_user,
    remove_button,
    set_greeting,
    set_question,
)
from ..keyboards import buttons_menu, kuplinov_menu, main_menu, personalities_menu
from ..states import (
    ButtonAddState,
    ButtonEditState,
    GreetingState,
    KuplinovAddState,
    KuplinovDelState,
    PersonalityEditState,
    QuestionState,
)
from ..utils import btn_id, extract_spoiler_from_caption


async def cmd_start(message: Message) -> None:
    if message.from_user.id != ADMIN_ID or message.chat.type != "private":
        return
    await message.answer("Выберите действие:", reply_markup=main_menu())


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

    if message.voice:
        payload = {
            "type": "voice",
            "file_id": message.voice.file_id,
            "caption": message.caption or "",
        }
    elif message.video:
        cap = message.caption or ""
        cap, cap_flag = extract_spoiler_from_caption(cap)
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
        cap, cap_flag = extract_spoiler_from_caption(cap)
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
        target_uid = callback.from_user.id
        for lbl in buttons.keys():
            builder.button(text=lbl, callback_data=f"btn:{target_uid}:{btn_id(lbl)}")
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


async def cmd_personalities(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Редактирование личностей", reply_markup=personalities_menu())
    await callback.answer()


async def process_personality_select(callback: CallbackQuery, state: FSMContext) -> None:
    name = callback.data.split(":", 1)[1]
    await state.update_data(name=name)
    await callback.message.edit_text(f"Отправьте новый текст для {name}")
    await state.set_state(PersonalityEditState.waiting_text)
    await callback.answer()


async def process_personality_text(message: Message, state: FSMContext) -> None:
    if message.from_user.id != ADMIN_ID or message.chat.type != "private":
        return
    data = await state.get_data()
    name = data.get("name")
    if not name:
        return
    file = PROMPTS_DIR / f"{name}.txt"
    file.write_text(message.text or "", encoding="utf-8")
    await message.answer("Личность обновлена", reply_markup=personalities_menu())
    await state.clear()

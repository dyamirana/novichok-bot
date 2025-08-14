from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import PROMPTS_DIR


def main_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="Приветствие", callback_data="menu_greeting")
    builder.button(text="Вопрос", callback_data="menu_question")
    builder.button(text="Кнопки", callback_data="menu_buttons")
    builder.button(text="Личности", callback_data="menu_personalities")
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


def personalities_menu():
    builder = InlineKeyboardBuilder()
    for file in sorted(PROMPTS_DIR.glob("*.txt")):
        name = file.stem
        builder.button(text=name, callback_data=f"pers_edit:{name}")
    builder.button(text="Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()

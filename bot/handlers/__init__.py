from aiogram import Dispatcher, F
from aiogram.filters import Command, StateFilter

from ..config import ADMIN_ID
from ..states import (
    ButtonAddState,
    ButtonEditState,
    GreetingState,
    KuplinovAddState,
    KuplinovDelState,
    QuestionState,
)
from . import admin, common


def register_handlers(dp: Dispatcher) -> None:
    dp.message.register(admin.cmd_start, Command("start"), F.from_user.id == ADMIN_ID, F.chat.type == "private")
    dp.message.register(admin.cmd_chatid, Command("chatid"))

    dp.callback_query.register(admin.cmd_set_greeting, F.data == "menu_greeting", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(admin.cmd_set_question, F.data == "menu_question", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(admin.cmd_buttons, F.data == "menu_buttons", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(admin.show_buttons_for_delete, F.data == "btn_del", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(admin.show_buttons_for_edit, F.data == "btn_edit", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(admin.process_button_add, F.data == "btn_add", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(admin.process_button_delete, F.data.startswith("delbtn:"), F.from_user.id == ADMIN_ID)
    dp.callback_query.register(
        admin.process_button_edit_select,
        F.data.startswith("editbtn:"),
        F.from_user.id == ADMIN_ID,
        StateFilter("*"),
    )
    dp.callback_query.register(admin.cmd_kuplinov_menu, F.data == "menu_kuplinov", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(admin.process_kp_add, F.data == "kp_add", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(admin.process_kp_del, F.data == "kp_del", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(admin.process_kp_list, F.data == "kp_list", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(admin.send_preview, F.data == "menu_preview", F.from_user.id == ADMIN_ID)
    dp.callback_query.register(admin.back_main, F.data == "back_main", F.from_user.id == ADMIN_ID)

    dp.message.register(admin.process_greeting, GreetingState.waiting)
    dp.message.register(admin.process_question, QuestionState.waiting)
    dp.message.register(admin.process_button_label, ButtonAddState.waiting_label)
    dp.message.register(admin.process_button_response, ButtonAddState.waiting_response)
    dp.message.register(admin.process_button_edit_response, ButtonEditState.waiting_response)
    dp.message.register(admin.process_kp_add_id, KuplinovAddState.waiting_id)
    dp.message.register(admin.process_kp_del_id, KuplinovDelState.waiting_id)

    dp.message.register(common.welcome, F.new_chat_members)
    dp.message.register(common.cmd_kuplinov, Command("kuplinov"))
    dp.message.register(common.cmd_joepeach, Command("joepeach"))
    dp.message.register(common.cmd_mrazota, Command("mrazota"))
    dp.callback_query.register(common.on_button, F.data.startswith("btn:"))
    dp.message.register(common.handle_message, F.text)

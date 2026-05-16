import aiosqlite
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from database import DB_PATH

router = Router()


# Функция для получения клавиатуры настроек
async def get_settings_kb(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT roulette_status, mines_status, crash_status FROM group_settings WHERE chat_id = ?",
                (chat_id,)
        ) as cur:
            row = await cur.fetchone()

            if not row:
                await db.execute(
                    "INSERT INTO group_settings (chat_id, roulette_status, mines_status, crash_status) VALUES (?, 1, 1, 1)",
                    (chat_id,)
                )
                await db.commit()
                r, m, c = 1, 1, 1
            else:
                r, m, c = row

    def get_status_icon(status):
        return "🟢" if status == 1 else "🔴"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"{get_status_icon(r)} Рулетка", callback_data=f"set_r_{chat_id}"),
            InlineKeyboardButton(text=f"{get_status_icon(m)} Мины", callback_data=f"set_m_{chat_id}")
        ],
        [
            InlineKeyboardButton(text=f"{get_status_icon(c)} Краш-игра", callback_data=f"set_c_{chat_id}")
        ],
        [
            InlineKeyboardButton(text="❌ Закрыть", callback_data=f"set_close_{chat_id}")
        ]
    ])
    return keyboard


@router.message(F.text.lower().in_({"/setting", "/settings", "/seting", "/настройки", "настр"}), F.chat.type.in_({"group", "supergroup"}))
async def cmd_settings(message: Message):
    member = await message.chat.get_member(message.from_user.id)

    # Защита: только владелец (creator)
    if member.status != "creator":
        return

    text = (
        f"<b>⚙️ Настройки чата</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"<b>Группа:</b> {message.chat.title}\n"
        f"<b>Действие:</b> Управление доступом к играм\n"
        f"━━━━━━━━━━━━━━\n"
        f"<i>Доступ разрешен только владельцу.</i>"
    )

    await message.answer(
        text,
        reply_markup=await get_settings_kb(message.chat.id),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("set_"))
async def handle_settings_callback(call: CallbackQuery):
    data = call.data.split("_")
    action = data[1]
    chat_id = int(data[2])

    # Проверка на владельца при клике на любую кнопку
    member = await call.bot.get_chat_member(chat_id=chat_id, user_id=call.from_user.id)
    if member.status != "creator":
        return await call.answer("❌ Настройки может менять только ВЛАДЕЛЕЦ группы!", show_alert=True)

    # Кнопка закрытия
    if action == "close":
        await call.message.delete()
        return await call.answer("Меню закрыто")

    col_map = {
        "r": "roulette_status",
        "m": "mines_status",
        "c": "crash_status"
    }
    column = col_map.get(action)

    if column:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                f"UPDATE group_settings SET {column} = 1 - {column} WHERE chat_id = ?",
                (chat_id,)
            )
            await db.commit()

        try:
            await call.message.edit_reply_markup(reply_markup=await get_settings_kb(chat_id))
            await call.answer("Статус изменен")
        except TelegramBadRequest:
            await call.answer()

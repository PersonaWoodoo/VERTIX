import datetime
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandObject, Command
import database

router = Router()

# Впишите сюда свой Telegram ID для проверки прав (можно несколько)
ADMIN_IDS = [8293927811, 8478884644]


# Команда "б" — проверка баланса
@router.message(F.text.lower() == "б")
async def cmd_short_balance(message: Message):
    user = message.from_user
    user_id = user.id

    database.add_user(user_id, user.first_name, user.username)
    database.update_user_info(user_id, user.first_name, user.username)

    balance = database.get_balance(user_id) or 0
    plugs_icon = database.get_setting('plugs_icon', '💰')
    mention = f"<a href='tg://user?id={user_id}'>{user.first_name}</a>"

    # Убрали текст "пуст", теперь всегда выводится число
    formatted_plugs = f"{balance:,}".replace(",", " ")
    balance_text = f"{plugs_icon} Баланс: <b>{formatted_plugs} VIRTEX</b>"

    text = (
        f"{mention}\n"
        f"{balance_text}"
    )

    kb = None
    bot_username = (await message.bot.get_me()).username

    # Изменили условие: бонус доступен и при 0, и до 50 000
    if balance < 50000:
        last_bonus_raw = database.get_user_bonus_info(user_id)
        if not last_bonus_raw or datetime.datetime.now() >= datetime.datetime.fromisoformat(
                last_bonus_raw) + datetime.timedelta(hours=24):
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎁 Получить бонус",
                                      url=f"https://t.me/{bot_username}?start=bonus")]
            ])

    await message.answer(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)

# Команда для установки кастомного эмодзи для VIRTEX
@router.message(Command("sate"))
async def cmd_sate(message: Message, command: CommandObject):
    if not command.args:
        return await message.answer(
            "Введите текст после команды.\nПример: <code>/sate 💎</code>",
            parse_mode="HTML"
        )

    # Достаем аргументы в формате HTML, чтобы сохранить Premium-эмодзи.
    try:
        new_icon = message.html_text.split(maxsplit=1)[1].strip()
    except IndexError:
        new_icon = command.args.strip()

    database.set_setting("plugs_icon", new_icon)
    current_icon = database.get_setting("plugs_icon", "💰")

    await message.answer(
        f"✅ Дизайн обновлен!\nТеперь для VIRTEX используется: {current_icon}",
        parse_mode="HTML"
    )

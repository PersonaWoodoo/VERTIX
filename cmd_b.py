import datetime
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandObject, Command
import database

router = Router()

ADMIN_IDS = [8293927811, 8478884644]


@router.message(F.text.lower().in_({"б", "баланс", "💰 баланс"}))
async def cmd_short_balance(message: Message):
    user = message.from_user
    user_id = user.id

    database.add_user(user_id, user.first_name, user.username)
    database.update_user_info(user_id, user.first_name, user.username)

    balance = database.get_balance(user_id) or 0
    plugs_icon = database.get_setting('plugs_icon', '💰')
    mention = f"<a href='tg://user?id={user_id}'>{user.first_name}</a>"

    formatted_plugs = f"{balance:,}".replace(",", " ")
    balance_text = f"{plugs_icon} <b>Ваш баланс:</b> {formatted_plugs} VIRTEX"

    text = f"{mention}\n{balance_text}"

    kb = None
    bot_username = (await message.bot.get_me()).username

    if balance < 50000:
        last_bonus_raw = database.get_user_bonus_info(user_id)
        if not last_bonus_raw or datetime.datetime.now() >= datetime.datetime.fromisoformat(
                last_bonus_raw) + datetime.timedelta(hours=24):
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎁 Получить бонус", url=f"https://t.me/{bot_username}?start=bonus")]
            ])

    await message.answer(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)


@router.message(Command("sate"))
async def cmd_sate(message: Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS:
        return

    if not command.args:
        return await message.answer(
            "Введите эмодзи после команды.\nПример: <code>/sate 💎</code>",
            parse_mode="HTML"
        )

    full_text = message.text
    
    if message.entities:
        for entity in message.entities:
            if entity.type == "custom_emoji":
                custom_emoji_id = entity.custom_emoji_id
                placeholder = full_text[entity.offset:entity.offset + entity.length]
                new_icon = f'<tg-emoji emoji-id="{custom_emoji_id}">{placeholder}</tg-emoji>'
                break
            elif entity.type == "emoji":
                new_icon = full_text[entity.offset:entity.offset + entity.length]
                break
        else:
            parts = full_text.split(maxsplit=1)
            new_icon = parts[1].strip() if len(parts) > 1 else command.args.strip()
    else:
        parts = full_text.split(maxsplit=1)
        new_icon = parts[1].strip() if len(parts) > 1 else command.args.strip()

    database.set_setting("plugs_icon", new_icon)
    current_icon = database.get_setting("plugs_icon", "💰")

    await message.answer(
        f"✅ Дизайн обновлен!\nТеперь для VIRTEX используется: {current_icon}",
        parse_mode="HTML"
    )

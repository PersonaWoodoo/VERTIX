import html
import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, \
    LinkPreviewOptions
from aiogram.filters import CommandStart, CommandObject
import database
from donate import DONATE_PACKS

router = Router()

CHANNEL_ID = "@VIRTEXCHANEL"
CHAT_ID = "@VIRTEXCHATW"


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, command: CommandObject, bot: Bot):
    user_id = message.from_user.id

    if command.args == "donate":
        buttons = []
        for pack_id, data in DONATE_PACKS.items():
            fmt_amount = f"{data['amount']:,}".replace(",", " ")
            bonus_part = f" ({data['bonus']})" if data['bonus'] else ""
            label = f"{data['stars']} ⭐️ - {fmt_amount} VIRTEX{bonus_part}"
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"pay:unit:{pack_id}")])
        buttons.append([InlineKeyboardButton(text="✏️ Своя сумма", callback_data="pay:custom")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        return await message.answer(
            "💎 <b>Пополнение VIRTEX</b>\n\n1 ⭐️ = 10 000 VIRTEX\n\nЕсли возникли проблемы с пополнением обратитесь к\n@CashOverseer",
            reply_markup=kb,
            parse_mode="HTML"
        )

    if command.args == "bonus":
        try:
            member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return await message.answer(f"❌ Вы не подписаны на канал {CHANNEL_ID}!\n\nПодпишитесь: https://t.me/{CHANNEL_ID[1:]}")
        except Exception:
            return await message.answer(f"❌ Ошибка проверки подписки на канал {CHANNEL_ID}")

        try:
            member_chat = await bot.get_chat_member(chat_id=CHAT_ID, user_id=user_id)
            if member_chat.status in ["left", "kicked"]:
                return await message.answer(f"❌ Вы не вступили в чат {CHAT_ID}!\n\nВступите: https://t.me/{CHAT_ID[1:]}")
        except Exception:
            return await message.answer(f"❌ Ошибка проверки чата {CHAT_ID}")

        is_vip = database.get_vip_status(user_id)
        last_bonus_raw = database.get_user_bonus_info(user_id)
        now = datetime.datetime.now()

        bonus_amount = 5000 if is_vip else 1000
        cooldown = datetime.timedelta(hours=3)

        if last_bonus_raw:
            last_bonus_time = datetime.datetime.fromisoformat(last_bonus_raw)
            if now < last_bonus_time + cooldown:
                remaining = (last_bonus_time + cooldown) - now
                hours, remainder = divmod(int(remaining.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                return await message.answer(f"⏳ Бонус будет доступен через <b>{hours:02d}:{minutes:02d}</b>", parse_mode="HTML")

        database.give_bonus(user_id, bonus_amount)
        mention = f'<a href="tg://user?id={user_id}">{html.escape(message.from_user.first_name)}</a>'
        return await message.answer(f"🎁 {mention}, вы получили <b>{bonus_amount} VIRTEX</b>!", parse_mode="HTML")

    welcome_text = (
        "┌─────────────────────┐\n"
        "│   🤖 <b>VIRTEX BOT</b>   │\n"
        "└─────────────────────┘\n\n"
        "👋 <b>Добро пожаловать!</b>\n\n"
        "💰 Ваша внутренняя валюта — <b>VIRTEX</b>\n\n"
        "🎮 <b>Что вас ожидает:</b>\n"
        "│ • 🎰 Рулетка\n"
        "│ • 💣 Мины\n"
        "│ • 🚀 Краш\n"
        "│ • 🗼 Башня\n"
        "│ • 🎲 Кубик / Кости\n"
        "│ • ⚽ Футбол / 🏀 Баскетбол\n"
        "│ • 🏆 Турниры\n"
        "│ • 👥 Реферальная система\n\n"
        "📖 <a href='https://telegra.ph/Polzovatelskoe-soglashenie-05-13-22'>Пользовательское соглашение</a>\n\n"
        "❓ Команда <code>помощь</code> - все команды\n\n"
        "✅ Запуская бота, вы принимаете правила игры"
    )

    bot_user = await message.bot.get_me()
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить бота в группу", url=f"https://t.me/{bot_user.username}?startgroup=true")],
        [InlineKeyboardButton(text="📢 Наш канал", url=f"https://t.me/{CHANNEL_ID[1:]}"),
         InlineKeyboardButton(text="💬 Наш чат", url=f"https://t.me/{CHAT_ID[1:]}")]
    ])

    reply_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏆 Турниры"), KeyboardButton(text="🎁 Бонус")],
            [KeyboardButton(text="⭐️ Донат"), KeyboardButton(text="❓ Помощь")],
            [KeyboardButton(text="👥 Рефералы"), KeyboardButton(text="💰 Баланс")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )

    await message.answer(welcome_text, reply_markup=inline_kb, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
    await message.answer("📱 <b>Меню навигации:</b>", reply_markup=reply_kb, parse_mode="HTML")

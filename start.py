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

    # --- ПЕРЕХОД ПО КНОПКЕ "Пополнить баланс" ---
    if command.args == "donate":
        buttons = []
        for pack_id, data in DONATE_PACKS.items():
            fmt_amount = f"{data['amount']:,}".replace(",", " ")
            bonus_part = f" ({data['bonus']})" if data['bonus'] else ""
            label = f"{data['stars']} ⭐️ - {fmt_amount} VIRTEX{bonus_part}"
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"pay:dc:{pack_id}")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        return await message.answer(
            "Если возникли проблемы с пополнением обратитесь к\n@debashev",
            reply_markup=kb,
            parse_mode="HTML"
        )

    # --- ЛОГИКА АВТОМАТИЧЕСКОГО БОНУСА ПРИ ПЕРЕХОДЕ ---
    if command.args == "bonus":
        # Проверка подписки на канал
        try:
            member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return await message.answer(f"❌ Вы не подписаны на {CHANNEL_ID}! Подпишитесь и нажмите кнопку снова.")
        except Exception:
            return await message.answer(f"❌ Ошибка проверки подписки на {CHANNEL_ID}. Убедитесь, что вы подписаны")

        # Проверка подписки на чат
        try:
            member_chat = await bot.get_chat_member(chat_id=CHAT_ID, user_id=user_id)
            if member_chat.status in ["left", "kicked"]:
                return await message.answer(f"❌ Вы не вступили в чат {CHAT_ID}! Вступите и нажмите кнопку снова.")
        except Exception:
            return await message.answer(f"❌ Ошибка проверки чата {CHAT_ID}. Убедитесь, что вы вступили")

        is_vip = database.get_vip_status(user_id)
        last_bonus_raw = database.get_user_bonus_info(user_id)
        now = datetime.datetime.now()

        bonus_amount = 5000 if is_vip else 1000
        cooldown = datetime.timedelta(hours=3)

        can_give = True
        if last_bonus_raw:
            last_bonus_time = datetime.datetime.fromisoformat(last_bonus_raw)
            if now < last_bonus_time + cooldown:
                can_give = False
                remaining = (last_bonus_time + cooldown) - now
                hours, remainder = divmod(int(remaining.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                return await message.answer(f"⏳ Бонус пока недоступен. Подождите <b>{hours:02d}:{minutes:02d}</b>",
                                            parse_mode="HTML")

        if can_give:
            database.give_bonus(user_id, bonus_amount)
            mention = f'<a href="tg://user?id={user_id}">{html.escape(message.from_user.first_name)}</a>'
            return await message.answer(f"🎁 {mention}, бонус активирован! Вы получили <b>{bonus_amount} VIRTEX</b>",
                                        parse_mode="HTML")

        return

    # --- СТАНДАРТНОЕ ПРИВЕТСТВИЕ ---
    welcome_text = (
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Ваша внутренняя валюта — <b>VIRTEX</b>.\n\n"
        "<b>Что вас ожидает ❓</b>\n"
        "• мини-игры\n"
        "• статистика / полезное\n"
        "• турниры\n"
        "• нфт маркет\n\n"
        "📖 <a href='https://telegra.ph/Polzovatelskoe-soglashenie-05-13-22'>Пользовательское соглашение</a>\n\n"
        "Посмотреть команды можно прописав команду <code>помощь</code>\n\n"
        "Запуская бота, вы принимаете правила игры"
    )

    bot_user = await message.bot.get_me()
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="➕ Добавить бота в группу",
            url=f"https://t.me/{bot_user.username}?startgroup=true"
        )]
    ])

    reply_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏆 Турниры")],
            [KeyboardButton(text="🎁 Бонус"), KeyboardButton(text="⭐️ Донат")],
            [KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )

    await message.answer(
        welcome_text,
        reply_markup=inline_kb,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    await message.answer("Воспользуйтесь меню ниже для навигации:", reply_markup=reply_kb)

import html
import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message
import database

router = Router()

# ID или username канала и чата для проверки подписки
CHANNEL_ID = "@VIRTEXCHANEL"      # канал
CHAT_ID = "@VIRTEXCHATW"          # чат

@router.message(F.text == "🎁 Бонус")
async def cmd_bonus(message: Message, bot: Bot):
    user_id = message.from_user.id

    # --- ПРОВЕРКА ПОДПИСКИ НА КАНАЛ ---
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ["left", "kicked"]:
            return await message.answer(
                f"❌ Вы не подписаны на канал {CHANNEL_ID}. Подпишитесь и повторите команду"
            )
    except Exception:
        return await message.answer(
            f"❌ Ошибка проверки подписки на канал {CHANNEL_ID}. Убедитесь, что подписаны, и повторите"
        )

    # --- ПРОВЕРКА ПОДПИСКИ НА ЧАТ ---
    try:
        member_chat = await bot.get_chat_member(chat_id=CHAT_ID, user_id=user_id)
        if member_chat.status in ["left", "kicked"]:
            return await message.answer(
                f"❌ Вы не вступили в чат {CHAT_ID}. Вступите и повторите команду"
            )
    except Exception:
        return await message.answer(
            f"❌ Ошибка проверки участия в чате {CHAT_ID}. Убедитесь, что вступили, и повторите"
        )
    # -------------------------

    # Проверяем наличие VIP статуса
    is_vip = database.get_vip_status(user_id)

    last_bonus_raw = database.get_user_bonus_info(user_id)
    now = datetime.datetime.now()

    # Устанавливаем параметры в зависимости от VIP
    if is_vip:
        bonus_amount = 5000
        cooldown = datetime.timedelta(hours=3)
    else:
        bonus_amount = 1000
        cooldown = datetime.timedelta(hours=3)

    if last_bonus_raw:
        last_bonus_time = datetime.datetime.fromisoformat(last_bonus_raw)
        next_bonus_time = last_bonus_time + cooldown

        if now < next_bonus_time:
            remaining = next_bonus_time - now
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)

            return await message.answer(
                f"⏰ До следующего бонуса: <b>{hours:02d}:{minutes:02d}</b>",
                parse_mode="HTML"
            )

    # Если бонуса не было или время ожидания прошло
    database.give_bonus(user_id, bonus_amount)

    mention = f'<a href="tg://user?id={user_id}">{html.escape(message.from_user.first_name)}</a>'
    await message.answer(
        f"{mention}, Вы получили <b>{bonus_amount} VIRTEX</b> 💰",
        parse_mode="HTML"
    )

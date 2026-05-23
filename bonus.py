import html
import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message
import database

router = Router()

CHANNEL_ID = "@VIRTEXCHANEL"
CHAT_ID = "@VIRTEXCHATW"


@router.message(F.text == "🎁 Бонус")
async def cmd_bonus(message: Message, bot: Bot):
    user_id = message.from_user.id

    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ["left", "kicked"]:
            return await message.answer(f"❌ Подпишитесь на канал: https://t.me/{CHANNEL_ID[1:]}")
    except:
        return await message.answer(f"❌ Ошибка проверки канала {CHANNEL_ID}")

    try:
        member_chat = await bot.get_chat_member(chat_id=CHAT_ID, user_id=user_id)
        if member_chat.status in ["left", "kicked"]:
            return await message.answer(f"❌ Вступите в чат: https://t.me/{CHAT_ID[1:]}")
    except:
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
            return await message.answer(f"⏳ Бонус через: {hours:02d}:{minutes:02d}", parse_mode="HTML")

    database.give_bonus(user_id, bonus_amount)
    mention = f'<a href="tg://user?id={user_id}">{html.escape(message.from_user.first_name)}</a>'
    await message.answer(f"🎁 {mention}, +{bonus_amount} VIRTEX!", parse_mode="HTML")

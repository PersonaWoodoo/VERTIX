from aiogram.types import Message
from aiogram import Bot

from games.config import CHANNEL_ID, CHAT_ID
from games.utils import mention_user


async def check_subscriptions(user_id: int, bot: Bot) -> tuple[bool, bool]:
    in_channel = False
    in_chat = False
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        in_channel = member.status not in ["left", "kicked"]
    except Exception:
        pass
    try:
        member = await bot.get_chat_member(chat_id=CHAT_ID, user_id=user_id)
        in_chat = member.status not in ["left", "kicked"]
    except Exception:
        pass
    return in_channel, in_chat


async def require_subscriptions(message: Message, bot: Bot) -> bool:
    user_id = message.from_user.id
    user_mention = mention_user(user_id, message.from_user.first_name)
    in_channel, in_chat = await check_subscriptions(user_id, bot)

    if not in_channel and not in_chat:
        await message.answer(
            f"{user_mention}, ❌ Вы не подписаны на канал {CHANNEL_ID} и не вступили в чат {CHAT_ID}\n\n"
            f"Подпишитесь и вступите, чтобы играть!",
            parse_mode="HTML"
        )
        return False
    elif not in_channel:
        await message.answer(
            f"{user_mention}, ❌ Вы не подписаны на канал {CHANNEL_ID}\n\nПодпишитесь и повторите команду!",
            parse_mode="HTML"
        )
        return False
    elif not in_chat:
        await message.answer(
            f"{user_mention}, ❌ Вы не вступили в чат {CHAT_ID}\n\nВступите и повторите команду!",
            parse_mode="HTML"
        )
        return False
    return True

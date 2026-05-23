import database
from aiogram import Router, F, Bot
import re
import html
from aiogram.types import Message

router = Router()
ADMIN_IDS = [8293927811, 8478884644]
COMMISSION = 0.035


def mnt(uid, name):
    return f'<a href="tg://user?id={uid}">{html.escape(str(name))}</a>'


@router.message(F.text.lower().startswith(("п ", "дать ", "перевод ")))
async def transfer_money(message: Message, bot: Bot):
    original_text = message.text
    parts = original_text.split()

    if parts[0].lower() not in ("п", "дать", "перевод"):
        return

    currency_name = "VIRTEX"

    if len(parts) < 2 or not parts[1].isdigit():
        return

    amount = int(parts[1])
    if amount <= 0:
        return

    sender = message.from_user
    recipient_id = None
    recipient_name = "Пользователь"

    if message.reply_to_message:
        if message.reply_to_message.from_user.is_bot:
            return await message.reply("❌ Нельзя переводить ботам")
        recipient_id = message.reply_to_message.from_user.id
        recipient_name = message.reply_to_message.from_user.first_name
    elif len(parts) >= 3:
        target = parts[2]
        if target.isdigit():
            recipient_id = int(target)
            user_info = database.get_full_user(recipient_id)
            if user_info:
                recipient_name = user_info[0]
            else:
                return await message.reply("❌ Пользователь не найден")
        elif target.startswith("@"):
            user_data = database.get_user_by_username(target)
            if user_data:
                raw_id = str(user_data[0])
                recipient_id = int(raw_id.replace("@", ""))
                recipient_name = user_data[1]
            else:
                return await message.reply("❌ Пользователь не найден")
        else:
            return await message.reply("❌ Укажите ID, @username или ответьте на сообщение")
    else:
        return await message.reply("❌ Кого хотите одарить?")

    if not recipient_id:
        return
    if sender.id == recipient_id:
        return await message.answer("❌ Нельзя переводить себе")

    commission_amount = int(amount * COMMISSION)
    if commission_amount < 1:
        commission_amount = 1
    final_amount = amount - commission_amount
    total_debit = amount

    success = database.make_transfer(
        sender.id, sender.first_name,
        recipient_id, recipient_name,
        total_debit, "balance"
    )

    if success:
        fmt_amount = f"{amount:,}".replace(",", " ")
        fmt_final = f"{final_amount:,}".replace(",", " ")
        fmt_commission = f"{commission_amount:,}".replace(",", " ")

        res_text = (
            f"{mnt(sender.id, sender.first_name)} перевёл\n"
            f"💰 <b>{fmt_amount} {currency_name}</b> → {mnt(recipient_id, recipient_name)}\n"
            f"💸 Комиссия 3.5%: <b>{fmt_commission} {currency_name}</b>\n"
            f"✅ Получено: <b>{fmt_final} {currency_name}</b>"
        )

        comment_parts = parts[2:] if message.reply_to_message else parts[3:]
        comment = " ".join(comment_parts)
        if comment:
            res_text += f"\n💬 {comment}"

        await message.answer(res_text, parse_mode="HTML")

        try:
            emoji = database.get_setting('plugs_icon', '💰')
            s_name = sender.first_name
            s_user = sender.username
            sender_link = f"<a href='https://t.me/{s_user}'>{s_name}</a>" if s_user else f"<a href='tg://user?id={sender.id}'>{s_name}</a>"
            notify_text = f"{emoji} Вам перевели <b>{fmt_final} {currency_name}</b>\nОт: {sender_link}\n💸 Комиссия: {fmt_commission}"
            if comment:
                notify_text += f"\n💬 {html.escape(comment)}"
            await bot.send_message(recipient_id, notify_text, parse_mode="HTML")
        except:
            pass
    else:
        await message.answer(f"❌ Недостаточно {currency_name}")

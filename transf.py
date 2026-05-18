import database
from aiogram import Router, F, Bot
import re
import html
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

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
            await message.reply("❌ Нельзя переводить средства ботам.")
            return

        recipient_id = message.reply_to_message.from_user.id
        user_info = database.get_full_user(recipient_id)
        if not user_info:
            await message.reply("❌ Пользователь не найден в базе данных.")
            return
        recipient_name = message.reply_to_message.from_user.first_name

    elif len(parts) >= 3:
        target = parts[2]
        if target.isdigit():
            recipient_id = int(target)
            user_info = database.get_full_user(recipient_id)
            if user_info:
                recipient_name = user_info[0]
            else:
                await message.reply("❌ Пользователь не найден.")
                return
        elif target.startswith("@"):
            user_data = database.get_user_by_username(target)
            if not user_data:
                user_data = database.get_user_by_username(target.lower())
            if user_data:
                raw_id = str(user_data[0])
                recipient_id = int(raw_id.replace("@", ""))
                recipient_name = user_data[1]
            else:
                await message.reply("❌ Пользователь не найден.")
                return
        else:
            await message.reply("❌ Неверный формат! Укажите ID, @юз или ответьте на сообщение.")
            return
    else:
        await message.reply("❌ Кого вы хотите одарить?")
        return

    if not recipient_id:
        return

    if sender.id == recipient_id:
        await message.answer("❌ Нельзя переводить самому себе.")
        return

    commission_amount = int(amount * COMMISSION)
    if commission_amount < 1:
        commission_amount = 1
    final_amount = amount - commission_amount
    total_debit = amount

    success = database.make_transfer(
        sender.id, sender.first_name,
        recipient_id, recipient_name,
        total_debit,
        currency="balance"
    )

    if success:
        fmt_amount = f"{amount:,}".replace(",", " ")
        fmt_final = f"{final_amount:,}".replace(",", " ")
        fmt_commission = f"{commission_amount:,}".replace(",", " ")

        res_text = (
            f"{mnt(sender.id, sender.first_name)} передал "
            f"<b>{fmt_amount} {currency_name}</b> для {mnt(recipient_id, recipient_name)}\n"
            f"💸 Комиссия 3.5%: <b>{fmt_commission} {currency_name}</b>\n"
            f"✅ Получил: <b>{fmt_final} {currency_name}</b>"
        )

        comment_parts = parts[2:] if message.reply_to_message else parts[3:]
        comment = " ".join(comment_parts)
        if comment:
            res_text += f"\n💬 Комментарий: {comment}"

        await message.answer(res_text, parse_mode="HTML")

        try:
            emoji = database.get_setting('plugs_icon', '💰')
            s_name = sender.first_name
            s_user = sender.username
            if s_user:
                sender_link = f"<a href='https://t.me/{s_user}'>{s_name}</a>"
            else:
                sender_link = f"<a href='tg://openmessage?user_id={sender.id}'>{s_name}</a>"

            notify_text = (
                f"{emoji} Вам перевели <b>{fmt_final} {currency_name}</b>.\n"
                f"Отправитель: {sender_link}\n"
                f"💸 Комиссия: {fmt_commission} {currency_name}"
            )
            if comment:
                notify_text += f"\n\n💬 Комментарий: {html.escape(comment)}"

            await bot.send_message(recipient_id, notify_text, parse_mode="HTML", disable_web_page_preview=True)
        except:
            pass
    else:
        await message.answer(f"❌ Недостаточно {currency_name} для перевода и комиссии!")

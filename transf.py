import database
from aiogram import Router, F, Bot
import re
import html
from aiogram import F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder




router = Router()

# Список ID администраторов, которым разрешено менять настройки
ADMIN_IDS = [8293927811, 8478884644]

def mnt(uid, name):
    """Безопасное упоминание"""
    return f'<a href="tg://user?id={uid}">{html.escape(str(name))}</a>'


@router.message(F.text.lower().startswith(("п ", "дать ", "перевод ")))
async def transfer_money(message: Message, bot: Bot):
    original_text = message.text
    parts = original_text.split()

    # Оставляем только команды перевода
    if parts[0].lower() not in ("п", "дать", "перевод"):
        return

    currency_key = "balance"
    currency_name = "VIRTEX"

    if len(parts) < 2 or not parts[1].isdigit():
        return

    amount = int(parts[1])
    if amount <= 0:
        return

    sender = message.from_user
    recipient_id = None
    recipient_name = "Пользователь"

    # Определение получателя
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
        await message.answer("Нельзя переводить самому себе.")
        return

    # Выполняем перевод через базу
    success = database.make_transfer(
        sender.id, sender.first_name,
        recipient_id, recipient_name,
        amount,
        currency=currency_key
    )

    if success:
        fmt_amount = f"{amount:,}".replace(",", " ")
        # Используем mnt (убедитесь, что она импортирована/определена)
        res_text = (f"{mnt(sender.id, sender.first_name)} передал "
                    f"<b>{fmt_amount} {currency_name}</b> для {mnt(recipient_id, recipient_name)}")

        comment_parts = parts[2:] if message.reply_to_message else parts[3:]
        comment = " ".join(comment_parts)

        if comment:
            res_text += f"\n💬 комментарий к переводу: {comment}"

        await message.answer(res_text, parse_mode="HTML")

        # --- УВЕДОМЛЕНИЕ В ЛС ---
        try:
            # Используем кастомный эмодзи для VIRTEX
            emoji = database.get_setting('plugs_icon', '💰')

            s_name = sender.first_name
            s_user = sender.username

            if s_user:
                sender_link = f"<a href='https://t.me/{s_user}'>{s_name}</a>"
            else:
                sender_link = f"<a href='tg://openmessage?user_id={sender.id}'>{s_name}</a>"

            notify_text = (
                f"{emoji} Вам перевели <b>{fmt_amount} {currency_name}</b>.\n"
                f"Отправитель: {sender_link}"
            )

            if comment:
                import html as py_html
                notify_text += f"\n\n💬 Комментарий: <i>{py_html.escape(comment)}</i>"

            await bot.send_message(
                recipient_id,
                notify_text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except:
            pass
    else:
        await message.answer(f"Недостаточно {currency_name}.")

# --- АДМИН КОМАНДА ---

@router.message(F.text.lower().startswith("/skkkadsa"))
async def admin_set_emoji(message: Message):
    # Проверка на админа
    if message.from_user.id not in ADMIN_IDS:
        return

    # Берем html_text, чтобы сохранить теги кастомных эмодзи
    full_text_html = message.html_text

    # Разделяем текст, чтобы отсечь саму команду /skkkadsa
    # Ищем первое вхождение пробела
    parts = full_text_html.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer("❌ Введите эмодзи после команды.")
        return

    # Это и будет наш эмодзи в том виде, в котором его прислали (с тегами, если он кастомный)
    new_emoji = parts[1].strip()

    database.set_global_emoji(new_emoji)

    await message.answer(f"✅ Глобальный эмодзи истории изменен на: {new_emoji}", parse_mode="HTML")


@router.message(F.text.lower().startswith("/skkka"))
async def admin_set_page_emoji(message: Message):
    # Проверка на админа
    if message.from_user.id not in ADMIN_IDS:
        return

    # Берем html_text для поддержки кастомных эмодзи
    full_text_html = message.html_text
    parts = full_text_html.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer("❌ Введите текст или эмодзи после команды. Пример: <code>/skkka 📄</code>",
                             parse_mode="HTML")
        return

    new_emoji = parts[1].strip()
    database.set_page_emoji(new_emoji)

    await message.answer(f"✅ Эмодзи страниц изменен на: {new_emoji}", parse_mode="HTML")



# --- ХЕНДЛЕРЫ ---

@router.message(F.text.lower().in_(["history", "история"]))
async def show_history(message: Message):
    # Берем имя отправителя команды
    user_name = message.from_user.first_name

    # Получаем кастомный эмодзи VIRTEX из базы (по аналогии с другими командами)
    unit_emoji = database.get_setting('plugs_icon', '💰')

    if message.chat.type in ["group", "supergroup"]:
        try:
            await send_history_page(message, page=1, user_id=message.from_user.id,
                                    user_name=user_name, destination=message.from_user.id)
            # Заменили луну на эмодзи баланса
            await message.answer(f"{unit_emoji} История транзакций отправлена вам в ЛС.")
        except Exception:
            await message.answer(f"❌ Напишите боту в ЛС, чтобы я мог отправить историю.")
    else:
        await send_history_page(message, page=1, user_name=user_name)

@router.callback_query(F.data.startswith("h_"))  # Исправлено с hist_ на h_
async def history_callback(callback: CallbackQuery):
    # Разбираем данные из кнопки (формат: h_страница_айди)
    parts = callback.data.split("_")

    if len(parts) < 3:
        return await callback.answer()

    page = int(parts[1])
    owner_id = int(parts[2])

    # Чтобы дизайн не ломался и имя не пропадало, вытягиваем его из текста сообщения
    owner_name = "Пользователь"
    if callback.message.entities:
        for entity in callback.message.entities:
            if entity.type == "text_link":
                # Берем текст, на который наложена ссылка (там наше имя)
                owner_name = callback.message.text[entity.offset:entity.offset + entity.length]
                break

    # Вызываем функцию обновления страницы
    await send_history_page(callback.message, page=page, user_id=owner_id, user_name=owner_name)
    await callback.answer()


# --- ФУНКЦИЯ ИСТОРИИ ---
async def send_history_page(message: Message, page: int, user_id: int = None, user_name: str = None,
                            destination: int = None):
    current_viewer_id = user_id if user_id else message.from_user.id

    if not user_name:
        user_name = message.from_user.first_name if message.from_user else "Пользователь"

    all_history = database.get_history(current_viewer_id)
    custom_emoji = database.get_global_emoji()
    page_emoji = database.get_page_emoji()

    if not all_history:
        target = destination if destination else message.chat.id
        await message.bot.send_message(target, f"{custom_emoji} Ваша история пока пуста.")
        return

    items_per_page = 10
    total_pages = min(5, (len(all_history) + items_per_page - 1) // items_per_page)

    if page > total_pages: page = total_pages
    if page < 1: page = 1

    start_idx = (page - 1) * items_per_page
    history_slice = all_history[start_idx:start_idx + items_per_page]

    safe_name = html.escape(re.sub(r'<.*?>', '', user_name))
    header_mention = f"tg://openmessage?user_id={current_viewer_id}"

    # Заголовок
    text = f"{custom_emoji} <b>История транзакций</b> (<a href='{header_mention}'>{safe_name}</a>)\n"
    text += f"{page_emoji} Страница {page} из {total_pages}\n\n"

    def clean_id(raw_id):
        return "".join(filter(str.isdigit, str(raw_id)))

    def get_safe_mention(name, raw_uid):
        cid = clean_id(raw_uid)
        clean_name = re.sub(r'<.*?>', '', str(name)).strip()
        safe_name_mention = html.escape(clean_name or "Пользователь")
        if cid:
            return f'<a href="tg://openmessage?user_id={cid}">{safe_name_mention}</a>'
        return safe_name_mention

    for amount, from_name, to_name, date, f_id_raw, t_id_raw, t_type in history_slice:
        sender_id_str = clean_id(f_id_raw)

        # Теперь всегда VIRTEX
        currency_name = "VIRTEX"

        if sender_id_str == str(current_viewer_id):
            mention = get_safe_mention(to_name, t_id_raw)
            sign, icon = "−", "➖"
            action = f"отправка для {mention}"
        else:
            mention = get_safe_mention(from_name, f_id_raw)
            sign, icon = "+", "➕"
            action = f"получение от {mention}"

        if t_type == "donate":
            icon, action = "⭐", "Пополнение через Stars"

        fmt_amount = f"{amount:,}".replace(",", " ")
        text += f"{icon} <code>{date}</code> | <b>{sign}{fmt_amount} {currency_name}</b>\n└ <i>{action}</i>\n\n"

    builder = InlineKeyboardBuilder()

    if page > 1:
        builder.button(text="⬅️ Назад", callback_data=f"h_{page - 1}_{current_viewer_id}")
    if page < total_pages:
        builder.button(text="Вперед ➡️", callback_data=f"h_{page + 1}_{current_viewer_id}")

    builder.adjust(2)
    target_chat = destination if destination else message.chat.id

    try:
        if message.from_user.id == (await message.bot.get_me()).id:
            await message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup(),
                                    disable_web_page_preview=True)
        else:
            await message.bot.send_message(target_chat, text, parse_mode="HTML", reply_markup=builder.as_markup(),
                                           disable_web_page_preview=True)
    except Exception:
        pass

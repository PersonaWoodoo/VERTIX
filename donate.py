from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import database

router = Router()

# Цены и пакеты (1 звезда = 10000 VIRTEX)
DONATE_PACKS = {
    "p_10":   {"stars": 50,   "amount": 500000,  "bonus": ""},
    "p_50":   {"stars": 100,  "amount": 1000000,  "bonus": "+10%"},
    "p_100":  {"stars": 250,  "amount": 2500000,  "bonus": "+15%"},
    "p_250":  {"stars": 500,  "amount": 5000000,  "bonus": "+20%"},
    "p_500":  {"stars": 1000, "amount": 10000000, "bonus": "+25%"},
    "p_1000": {"stars": 2500, "amount": 25000000, "bonus": "+30%"},
}

# Состояние для выбора своей суммы
class DonateStates(StatesGroup):
    waiting_custom_stars = State()  # выбор количества звезд


# --- ГЛАВНОЕ МЕНЮ ДОНАТА ---
@router.message(F.text == "⭐️ Донат", F.chat.type == "private")
@router.message(F.text == "/donate")
async def cmd_donate(message: Message):
    buttons = []
    for pack_id, data in DONATE_PACKS.items():
        fmt_amount = f"{data['amount']:,}".replace(",", " ")
        bonus_part = f" ({data['bonus']})" if data['bonus'] else ""
        label = f"{data['stars']} ⭐️ - {fmt_amount} VIRTEX{bonus_part}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"pay:unit:{pack_id}")])
    
    # Кнопка СВОЯ СУММА
    buttons.append([InlineKeyboardButton(text="✏️ СВОЯ СУММА", callback_data="pay:custom")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = "💎 <b>Пополнение VIRTEX</b>\n\n1 ⭐️ = 10 000 VIRTEX\n\nЕсли возникли проблемы с пополнением обратитесь к\n@debashev"
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# --- ВЫБОР СВОЕЙ СУММЫ (количество звезд) ---
@router.callback_query(F.data == "pay:custom")
async def custom_amount_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(DonateStates.waiting_custom_stars)
    await call.message.edit_text(
        "💰 <b>Введите количество звёзд для пополнения</b>\n\n"
        "Минимум: <b>1 ⭐️</b> (10 000 VIRTEX)\n"
        "Максимум: <b>100 000 ⭐️</b> (1 000 000 000 VIRTEX)\n\n"
        "Просто напишите число:\n"
        "<code>10</code> - 10 звёзд (100 000 VIRTEX)\n"
        "<code>100</code> - 100 звёзд (1 000 000 VIRTEX)\n"
        "<code>1000</code> - 1000 звёзд (10 000 000 VIRTEX)\n\n"
        "Или отправьте <b>0</b> для отмены",
        parse_mode="HTML"
    )


@router.message(DonateStates.waiting_custom_stars)
async def custom_stars_process(message: Message, state: FSMContext, bot: Bot):
    text = message.text.strip()
    
    # Отмена
    if text == "0":
        await state.clear()
        return await message.answer("❌ Операция отменена")
    
    # Парсим количество звезд
    try:
        stars = int(text.replace(" ", ""))
    except ValueError:
        return await message.answer("❌ Введите целое число (количество звёзд)")
    
    # Проверка лимитов
    if stars < 1:
        return await message.answer("❌ Минимум: 1 ⭐️ (10 000 VIRTEX)")
    if stars > 100000:
        return await message.answer("❌ Максимум: 100 000 ⭐️ (1 000 000 000 VIRTEX)")
    
    amount = stars * 10000  # 1 звезда = 10000 VIRTEX
    fmt_amount = f"{amount:,}".replace(",", " ")
    
    await state.clear()
    
    # Создаем инвойс
    title = "💳 Пополнение VIRTEX"
    description = f"Начисление {fmt_amount} VIRTEX на ваш игровой аккаунт."
    payload = f"unit:{amount}:{stars}"
    
    try:
        await bot.send_invoice(
            chat_id=message.chat.id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="⭐️ Звёзды", amount=stars)]
        )
    except Exception as e:
        print(f"Ошибка при отправке счета: {e}")
        await message.answer("❌ Не удалось создать счет. Попробуйте позже.")


# --- ГЕНЕРАЦИЯ СЧЕТА (стандартные пакеты) ---
@router.callback_query(F.data.startswith("pay:unit:"))
async def create_invoice(call: CallbackQuery, bot: Bot):
    pack_id = call.data.split("pay:unit:")[1]
    if pack_id not in DONATE_PACKS:
        return await call.answer("❌ Товар не найден.", show_alert=True)

    option = DONATE_PACKS[pack_id]
    stars = option["stars"]
    amount = option["amount"]

    fmt_amount = f"{amount:,}".replace(",", " ")
    title = "💳 Пополнение VIRTEX"
    description = f"Начисление {fmt_amount} VIRTEX на ваш игровой аккаунт."
    payload = f"unit:{amount}:{stars}"

    try:
        await call.answer()
        await call.message.edit_reply_markup(reply_markup=None)
        await bot.send_invoice(
            chat_id=call.message.chat.id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="⭐️ Звёзды", amount=stars)]
        )
    except Exception as e:
        print(f"Ошибка при отправке счета: {e}")
        await call.answer("❌ Не удалось создать счет.", show_alert=True)


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


# --- ПОЛУЧЕНИЕ ОПЛАТЫ ---
@router.message(F.successful_payment)
async def on_successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    cat, amount, stars = payload.split(":")
    amount = int(amount)
    stars = int(stars)
    fmt_amount = f"{amount:,}".replace(",", " ")

    database.log_donate(
        message.from_user.id,
        message.successful_payment.telegram_payment_charge_id,
        amount,
        stars
    )

    await message.answer(
        f"✅ <b>ОПЛАТА ПРОШЛА УСПЕШНО</b>\n\n"
        f"💰 На ваш баланс зачислено: <b>{fmt_amount} VIRTEX</b>\n"
        f"⭐️ Потрачено звёзд: <b>{stars}</b>\n\n"
        f"Спасибо за поддержку проекта!",
        parse_mode="HTML"
    )

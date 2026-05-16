import time
import random
import json
import aiosqlite
from aiogram import Router, F
from aiogram.types import Message
from database import DB_PATH
import database
import math

router = Router()

# Словарь для антифлуда: {user_id: timestamp}
crash_cooldowns = {}





def generate_crash_point() -> float:
    """
    Хардкорный алгоритм:
    - 11% мгновенный краш на 1.0x (увеличенный house edge)
    - Зоны перенастроены на быстрый слив:
        зона 1 (1.0–4x)   — ~65% случаев (основной слив)
        зона 2 (4–15x)   — ~20% случаев
        зона 3 (15–35x)  — ~10% случаев
        зона 4 (35–60.0x) — ~3.5% случаев
        зона 5 (60.0–20000.0x)— ~0.5% случаев
    """
    r = random.random() * 100

    # Увеличенный House edge — мгновенный краш на 1.00
    if r < 11.0:
        return 1.00

    # Используем возведение в степень для u, чтобы сместить
    # случайное число еще ближе к 0 (к началу зоны)
    u = random.random() ** 1.5

    # Выбираем зону (zone_roll)
    zone_roll = random.random() * 100

    if zone_roll < 65:
        # Зона 1: 1.01 – 1.5 (Большинство игр умрет здесь)
        lo, hi = 1.01, 1.5
    elif zone_roll < 85:
        # Зона 2: 1.5 – 3.0
        lo, hi = 1.5, 3.0
    elif zone_roll < 95:
        # Зона 3: 3.0 – 10.0
        lo, hi = 3.0, 10.0
    elif zone_roll < 98.5:
        # Зона 4: 10.0 – 30.0
        lo, hi = 10.0, 30.0
    else:
        # Зона 5: 30.0 – 200.0 (Максимальный выигрыш снижен)
        lo, hi = 30.0, 200.0

    # Логарифмическое распределение
    log_lo = math.log(lo)
    log_hi = math.log(hi)
    result = math.exp(log_lo + u * (log_hi - log_lo))

    # Уменьшаем шум, чтобы не давать лишних бонусов
    noise = random.uniform(0.96, 1.01)
    result *= noise

    # Ограничиваем результат
    final_result = max(min(result, 200.0), 1.0)
    return round(final_result, 2)

@router.message(F.text.lower().startswith("краш"))
async def cmd_crash(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        return await message.reply("🚫 <b>Краш</b> доступен только в группах!", parse_mode="HTML")

    chat_id = message.chat.id
    user_id = message.from_user.id
    fmt_user_id = f"@{user_id}"

    # --- ПРОВЕРКА СТАТУСА ИГРЫ ---
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT crash_status FROM group_settings WHERE chat_id = ?", (chat_id,)
        ) as cur:
            row = await cur.fetchone()
            if row and row[0] == 0:
                return await message.reply("❌ Игра <b>Краш</b> отключена администратором.", parse_mode="HTML")

    # --- АНТИФЛУД ---
    current_time = time.time()
    if user_id in crash_cooldowns:
        diff = current_time - crash_cooldowns[user_id]
        if diff < 3.0:
            remain = round(3.0 - diff, 1)
            return await message.reply(f"⏳ <b>Подождите {remain} сек.</b> перед следующей игрой!", parse_mode="HTML")

    crash_cooldowns[user_id] = current_time

    # --- ПАРСИНГ ---
    parts = message.text.split()
    if len(parts) < 3:
        return await message.reply("<b>Формат:</b>\n<code>краш [сумма] [множитель]</code>", parse_mode="HTML")

    try:
        bet = int(parts[1].replace(" ", ""))
        target_mult = float(parts[2].replace(",", "."))
    except ValueError:
        return await message.reply("Введите числа!")

    if bet <= 0 or target_mult < 1.01:
        return await message.reply("Неверные значения!")

    # --- ЛОГИКА ИГРЫ ---
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (fmt_user_id,)) as cur:
            user_data = await cur.fetchone()

        if not user_data:
            return await message.reply("❌ Вы не зарегистрированы!")

        # --- ПРОВЕРКА БАЛАНСА ---
        if user_data[0] < bet:
            fmt_balance = f"{user_data[0]:,}".replace(",", " ")
            fmt_bet = f"{bet:,}".replace(",", " ")
            return await message.reply(
                f"❌ <b>У вас недостаточно VIRTEX!</b>\n"
                f"<b>Ставка:</b> {fmt_bet} VIRTEX\n"
                f"<b>Баланс:</b> {fmt_balance} VIRTEX",
                parse_mode="HTML"
            )

        if user_data[0] <= 0:
            return await message.reply("❌ Недостаточно <b>VIRTEX</b> на балансе!", parse_mode="HTML")

        actual_bet = bet

        # Получаем префикс игры и иконку валюты
        async with db.execute("SELECT value FROM global_settings WHERE key = 'crash_prefix'") as cur:
            prefix_data = await cur.fetchone()
            crash_prefix = f"{prefix_data[0]} " if prefix_data else "🚀 "

        # Загружаем кастомный эмодзи баланса (VIRTEX)
        unit_emoji = database.get_setting('plugs_icon', '💰')

        crash_point = generate_crash_point()
        is_win = crash_point >= target_mult

        if is_win:
            win_amount = int(actual_bet * target_mult)
            profit = win_amount - actual_bet
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (profit, fmt_user_id))
            status_text = "выиграл!"
            result_amount = win_amount
        else:
            await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (actual_bet, fmt_user_id))
            status_text = "проиграл"
            result_amount = 0

        await db.commit()

        # --- ВЫВОД ---
        fmt_bet = f"{actual_bet:,}".replace(",", " ")
        fmt_result = f"{result_amount:,}".replace(",", " ")

        text = (
            f"{crash_prefix}<b>КРАШ</b>\n\n"
            f"{message.from_user.mention_html()} {status_text}\n"
            f"<b>ставка:</b> <b>{fmt_bet}</b> <b>VIRTEX</b> {unit_emoji}\n"
            f"<b>выигрыш:</b> <b>{fmt_result}</b> <b>VIRTEX</b> {unit_emoji}\n"
            f"<b>множитель:</b> <b>{target_mult}x</b>\n"
            f"<b>упало на:</b> <b>{crash_point}x</b>"
        )

        await message.answer(text, parse_mode="HTML")

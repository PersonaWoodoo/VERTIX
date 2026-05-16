import asyncio
import logging
import os
import random
import time
import aiosqlite

from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.exceptions import TelegramBadRequest

from database import DB_PATH

logger = logging.getLogger(__name__)

router = Router()


game_state: dict = {}
last_user_bets_cache: dict = {}


RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BLACK_NUMBERS = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}


_DIR = os.path.dirname(os.path.abspath(__file__))
ROULETTE_GIF = os.path.join(_DIR, "anim1.mp4")


MIN_BET_DELAY = 12



def get_color(n: int) -> str:
    if n == 0:
        return "🟢"
    return "🔴" if n in RED_NUMBERS else "⚫"


def fmt_money(amount: int) -> str:
    """Форматирует число с пробелами: 1000000 -> '1 000 000'"""
    return f"{amount:,}".replace(",", " ")


def format_bet_value(value: str) -> str:
    """Единая точка конвертации внутренних значений ставок в читаемый вид."""
    return {
        "к": "RED",
        "ч": "BLACK",
        "чет": "ЧЕТ",
        "евен": "ЧЕТ",
        "нечет": "НЕЧЕТ",
        "одд": "НЕЧЕТ",
    }.get(value, value.upper() if value.isalpha() else value)


def get_bet_type(target: str) -> str:
    """Возвращает тип ставки по её значению."""
    if target in ("к",):
        return "red"
    if target in ("ч",):
        return "black"
    if target in ("чет", "евен"):
        return "even"
    if target in ("нечет", "одд"):
        return "odd"
    if "-" in target:
        return "range"
    return "number"


async def send_in_chunks(send_fn, lines: list[str], parse_mode: str = "HTML", **kwargs):
    """Отправляет список строк, разбивая на сообщения по 4000 символов."""
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 4000:
            await send_fn(chunk, parse_mode=parse_mode, **kwargs)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await send_fn(chunk, parse_mode=parse_mode, **kwargs)


def calculate_payout(b_type: str, b_val: str, amt: int, win_num: int, win_color: str) -> int:
    """Рассчитывает выплату для одной ставки. Возвращает 0 если проигрыш."""
    if b_type == "red" and win_color == "🔴":
        return amt * 2
    if b_type == "black" and win_color == "⚫":
        return amt * 2
    if b_type == "even" and win_num != 0 and win_num % 2 == 0:
        return amt * 2
    if b_type == "odd" and win_num % 2 != 0:
        return amt * 2
    if b_type == "number" and b_val == str(win_num):
        return amt * 36
    if b_type == "range":
        try:
            s, e = map(int, b_val.split("-"))
            if s <= win_num <= e:
                return int(amt * (36 / (e - s + 1)))
        except ValueError:
            pass
    return 0


def _normalize_target(target: str) -> str:
    """Убирает ведущие нули у числовых токенов: '012' -> '12', '07' -> '7'."""
    if target.isdigit():
        return str(int(target))
    if "-" in target:
        parts = target.split("-", 1)
        if parts[0].isdigit() and parts[1].isdigit():
            return f"{int(parts[0])}-{int(parts[1])}"
    return target


# ---------------------------------------------------------------------------
# Хендлер ставок
# ---------------------------------------------------------------------------

# Регулярка принимает: число, затем один или несколько токенов через пробел.
# Токен — цветовая/чётностная метка или число 0-99 или диапазон N-M.
# Лишние слова (не из списка) не пройдут, т.к. конец строки — $.
@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.regexp(r"^\d+(\s+(к|ч|евен|одд|чет|нечет|\d{1,2}|\d{1,2}-\d{1,2}))+$"),
)
async def place_bet(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    fmt_user_id = f"@{user_id}"
    full_name = message.from_user.full_name

    state = game_state.setdefault(chat_id, {"is_running": False, "first_bet_time": None})
    if state["is_running"]:
        return await message.reply("Подождите окончания игры!")

    raw_parts = message.text.lower().split()
    # Нормализуем ведущие нули во всех токенах кроме суммы
    parts = [raw_parts[0]] + [_normalize_target(t) for t in raw_parts[1:]]

    try:
        amount = int(parts[0])
        if amount <= 0:
            return await message.reply("Сумма ставки должна быть больше 0!")
    except ValueError:
        return

    # Валидация числовых ставок до обращения к БД
    for target in parts[1:]:
        if target in ("к", "ч", "евен", "одд", "чет", "нечет"):
            continue
        if target.isdigit():
            if int(target) > 36:
                return await message.reply(f"Ошибка. Некорректная ставка: {target}")
        elif "-" in target:
            try:
                start, end = map(int, target.split("-"))
                if start > 36 or end > 36 or start > end:
                    return await message.reply(f"Ошибка. Некорректная ставка: {target}")
            except ValueError:
                return await message.reply("Неверный формат диапазона!")

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        # Всё в одной транзакции: проверка статуса, баланса, лимита и запись ставок
        await db.execute("BEGIN EXCLUSIVE")

        # Проверка статуса игры
        async with db.execute(
            "SELECT roulette_status FROM group_settings WHERE chat_id = ?", (chat_id,)
        ) as cur:
            row = await cur.fetchone()
            if row and row[0] == 0:
                await db.execute("ROLLBACK")
                return await message.reply("Игра отключена администратором!")

        # Текущее количество ставок пользователя
        async with db.execute(
            "SELECT COUNT(*) FROM roulette_bets WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        ) as cur:
            current_bets_count = (await cur.fetchone())[0]

        if current_bets_count >= 100:
            await db.execute("ROLLBACK")
            return await message.reply("Вы уже достигли лимита в 100 ставок!")

        # Баланс пользователя
        async with db.execute(
            "SELECT balance FROM users WHERE user_id = ?", (fmt_user_id,)
        ) as cur:
            row = await cur.fetchone()

        if not row:
            await db.execute("ROLLBACK")
            return await message.reply("Вы не зарегистрированы!")

        user_balance = row[0]
        if user_balance < amount:
            await db.execute("ROLLBACK")
            return await message.reply("У вас недостаточно средств даже для одной ставки!")

        remaining_limit = 100 - current_bets_count
        raw_targets = parts[1:][:remaining_limit]

        max_possible_bets = user_balance // amount
        actual_targets = raw_targets[:max_possible_bets]

        if not actual_targets:
            await db.execute("ROLLBACK")
            return await message.reply("Недостаточно средств для ставки!")

        total_cost = amount * len(actual_targets)

        await db.execute(
            "UPDATE users SET balance = balance - ?, name = ? WHERE user_id = ?",
            (total_cost, full_name, fmt_user_id),
        )

        insert_rows = [
            (user_id, chat_id, full_name, amount, get_bet_type(t), t)
            for t in actual_targets
        ]
        await db.executemany(
            "INSERT INTO roulette_bets (user_id, chat_id, user_name, amount, type, value) VALUES (?, ?, ?, ?, ?, ?)",
            insert_rows,
        )
        await db.commit()

    if len(actual_targets) < len(raw_targets):
        await message.answer(
            f"Баланса не хватило на все ставки. Принято только первые {len(actual_targets)} шт."
        )

    if state["first_bet_time"] is None:
        state["first_bet_time"] = time.time()

    user_mention = message.from_user.mention_html()
    fmt_amt = fmt_money(amount)
    lines = [
        f"Ставка принята: {user_mention} {fmt_amt} VIRTEX на {format_bet_value(t)}"
        for t in actual_targets
    ]
    await send_in_chunks(message.reply, lines)


# ---------------------------------------------------------------------------
# Запуск рулетки
# ---------------------------------------------------------------------------

@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.lower().in_({"go", "го"}),
)
async def start_spin(message: Message, bot: Bot):
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Проверка статуса рулетки
    async with aiosqlite.connect(DB_PATH, timeout=20.0) as db:
        async with db.execute(
            "SELECT roulette_status FROM group_settings WHERE chat_id = ?", (chat_id,)
        ) as cur:
            settings = await cur.fetchone()
            if settings and settings[0] == 0:
                return await message.reply("Рулетка отключена администратором. Запуск невозможен.")

    state = game_state.setdefault(chat_id, {"is_running": False, "first_bet_time": None})

    if state["is_running"]:
        return await message.reply("Рулетка уже запущена!")

    # Загружаем ставки
    async with aiosqlite.connect(DB_PATH, timeout=20.0) as db:
        async with db.execute(
            "SELECT user_id, user_name, amount, type, value FROM roulette_bets WHERE chat_id = ?",
            (chat_id,),
        ) as cur:
            all_bets = await cur.fetchall()

    if not all_bets:
        return await message.reply("Ставок еще нет!")

    if not any(bet[0] == user_id for bet in all_bets):
        return await message.reply("Вы не можете запустить рулетку, так как не сделали ставку!")

    # Антифлуд
    if state["first_bet_time"]:
        diff = time.time() - state["first_bet_time"]
        if diff < MIN_BET_DELAY:
            wait_sec = int(MIN_BET_DELAY - diff)
            return await message.reply(f"Ошибка запуска! Ждите {wait_sec} сек.")

    state["is_running"] = True

    try:
        # Кэшируем ставки для кнопок повтора
        last_user_bets_cache[chat_id] = {}
        for uid, name, amt, b_type, b_val in all_bets:
            last_user_bets_cache[chat_id].setdefault(uid, []).append(
                {"amount": amt, "value": b_val, "type": b_type, "name": name}
            )

        # Подготовка для расчёта весов
        parsed_bets = []
        for _, _, amt, b_type, b_val in all_bets:
            if b_type == "range":
                try:
                    s, e = map(int, b_val.split("-"))
                    parsed_bets.append({"amt": amt, "type": "range", "start": s, "end": e})
                except ValueError:
                    continue
            elif b_type == "number":
                try:
                    parsed_bets.append({"amt": amt, "type": "number", "val": int(b_val)})
                except ValueError:
                    continue
            else:
                parsed_bets.append({"amt": amt, "type": b_type})

        total_bank = sum(bet[2] for bet in all_bets)

        # ---------------------------------------------------------------------------
        # Расчёт весов для каждого числа.
        #
        # Логика:
        #   1. Базовый вес у всех чисел одинаковый (100.0).
        #   2. Числа, на которые сделаны большие ставки, получают пониженный вес
        #      пропорционально тому, насколько выплата превышает банк.
        #   3. После расчёта сырых весов нормализуем суммы весов красных и чёрных
        #      чисел так, чтобы они были строго равны — это исключает накопленный
        #      перекос в пользу одного цвета.
        #   4. random.uniform убран: он давал статистический сдвиг на коротких
        #      сессиях и был единственной причиной постоянного выпадения чёрного.
        # ---------------------------------------------------------------------------
        smooth_factor = 2.5
        weights = []
        for num in range(37):
            num_color = get_color(num)
            payout = 0
            for bet in parsed_bets:
                if bet["type"] == "red" and num_color == "🔴":
                    payout += bet["amt"] * 2
                elif bet["type"] == "black" and num_color == "⚫":
                    payout += bet["amt"] * 2
                elif bet["type"] == "even" and num != 0 and num % 2 == 0:
                    payout += bet["amt"] * 2
                elif bet["type"] == "odd" and num % 2 != 0:
                    payout += bet["amt"] * 2
                elif bet["type"] == "number" and bet.get("val") == num:
                    payout += bet["amt"] * 36
                elif bet["type"] == "range" and bet["start"] <= num <= bet["end"]:
                    payout += int(bet["amt"] * (36 / (bet["end"] - bet["start"] + 1)))

            base_weight = 100.0
            if payout > total_bank:
                ratio = payout / (total_bank + 1)
                adjustment = max(0.35, 1 / (1 + (ratio / smooth_factor)))
                w = base_weight * adjustment
            else:
                w = base_weight * 1.1
            weights.append(w)

        # Нормализация: уравниваем суммарный вес красных и чёрных чисел,
        # чтобы ни один цвет не имел структурного преимущества.
        red_total = sum(weights[n] for n in RED_NUMBERS)
        black_total = sum(weights[n] for n in BLACK_NUMBERS)
        if red_total > 0 and black_total > 0 and red_total != black_total:
            if red_total > black_total:
                ratio = black_total / red_total
                for n in RED_NUMBERS:
                    weights[n] *= ratio
            else:
                ratio = red_total / black_total
                for n in BLACK_NUMBERS:
                    weights[n] *= ratio

        win_num = random.choices(range(37), weights=weights, k=1)[0]

        # --- ОТПРАВКА ГИФКИ РУЛЕТКИ ---
        gif_msg = None
        try:
            gif_msg = await message.answer_animation(animation=FSInputFile(ROULETTE_GIF))
        except Exception as e:
            logger.error(f"Ошибка отправки гифки: {e}")
        
        # Ждём 3-4 секунды
        await asyncio.sleep(random.uniform(3.0, 4.0))
        
        # Удаляем гифку
        if gif_msg:
            try:
                await bot.delete_message(chat_id, gif_msg.message_id)
            except TelegramBadRequest:
                pass
            except Exception as e:
                logger.error(f"Ошибка удаления гифки: {e}")

        win_color = get_color(win_num)
        color_name = "RED" if win_color == "🔴" else "BLACK" if win_color == "⚫" else "ZERO"

        winners_list = []
        total_bets_list = []
        total_payout_actual = 0

        # Обработка результатов и начисление выигрышей
        async with aiosqlite.connect(DB_PATH, timeout=20.0) as db:
            winner_updates = []  # (payout, uid) для executemany
            tournament_updates = []  # (uid, name, net_profit) для executemany

            for uid, name, amt, b_type, b_val in all_bets:
                mention = f'<a href="tg://user?id={uid}">{name}</a>'
                disp_val = format_bet_value(b_val)
                fmt_amt = fmt_money(amt)
                total_bets_list.append(f"{mention} {fmt_amt} VIRTEX на {disp_val}")

                payout = calculate_payout(b_type, b_val, amt, win_num, win_color)
                if payout:
                    total_payout_actual += payout
                    winner_updates.append((payout, f"@{uid}"))

                    net_profit = payout - amt
                    if net_profit > 0:
                        tournament_updates.append((uid, name, net_profit))

                    fmt_payout = fmt_money(payout)
                    winners_list.append(
                        f"{mention} ставка {fmt_amt} VIRTEX выиграл {fmt_payout} VIRTEX на {disp_val}"
                    )

            # Batch-обновление балансов победителей
            if winner_updates:
                await db.executemany(
                    "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                    winner_updates,
                )

            # Batch-обновление турнира
            if tournament_updates:
                await db.executemany(
                    """
                    INSERT INTO tournament_stats (user_id, user_name, profit)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        profit = profit + EXCLUDED.profit,
                        user_name = EXCLUDED.user_name
                    """,
                    tournament_updates,
                )

            profit = total_bank - total_payout_actual
            await db.execute(
                "UPDATE group_settings SET casino_balance = casino_balance + ? WHERE chat_id = ?",
                (profit, chat_id),
            )
            await db.execute(
                "INSERT INTO roulette_history (chat_id, number, color) VALUES (?, ?, ?)",
                (chat_id, win_num, win_color),
            )
            await db.execute("DELETE FROM roulette_bets WHERE chat_id = ?", (chat_id,))
            await db.commit()

        # Формирование и отправка результата
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Повторить", callback_data="r_repeat"),
                    InlineKeyboardButton(text="Удвоить", callback_data="r_double"),
                ]
            ]
        )

        header = f"🎡 <b>РУЛЕТКА</b>\n\nВыпало: {win_num} {win_color} ({color_name})\n\n📋 <b>Ставки:</b>\n"
        result_lines = total_bets_list + ["\n💰 <b>Выигрыш:</b>"]
        result_lines += winners_list if winners_list else ["❌ Никто не выиграл"]

        # Первый чанк с заголовком, последний — с кнопками
        chunks = []
        current = header
        for line in result_lines:
            if len(current) + len(line) + 2 > 4000:
                chunks.append(current)
                current = ""
            current += line + "\n"
        if current:
            chunks.append(current)

        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            await message.answer(
                chunk,
                parse_mode="HTML",
                reply_markup=markup if is_last else None,
            )

    except Exception as e:
        logger.error(f"Ошибка рулетки в чате {chat_id}: {e}", exc_info=True)
        await message.answer("Произошла критическая ошибка. Попробуйте снова.")
    finally:
        state["is_running"] = False
        state["first_bet_time"] = None


# ---------------------------------------------------------------------------
# Кнопки «Повторить» / «Удвоить»
# ---------------------------------------------------------------------------

@router.callback_query(F.data.in_({"r_repeat", "r_double"}))
async def process_repeat_double(call: CallbackQuery):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    fmt_user_id = f"@{user_id}"
    action = call.data

    state = game_state.get(chat_id, {})
    if state.get("is_running"):
        return await call.answer("Рулетка уже запущена, ставки не принимаются!", show_alert=True)

    user_bets = last_user_bets_cache.get(chat_id, {}).get(user_id)
    if not user_bets:
        return await call.answer("У вас нет предыдущих ставок для повторения!", show_alert=True)

    multiplier = 2 if action == "r_double" else 1
    total_cost = sum(bet["amount"] * multiplier for bet in user_bets)

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute("BEGIN EXCLUSIVE")

        async with db.execute(
            "SELECT balance FROM users WHERE user_id = ?", (fmt_user_id,)
        ) as cur:
            user_data = await cur.fetchone()

        if not user_data or user_data[0] < total_cost:
            await db.execute("ROLLBACK")
            return await call.answer(
                f"Недостаточно средств! Нужно: {fmt_money(total_cost)} VIRTEX",
                show_alert=True,
            )

        await db.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id = ?",
            (total_cost, fmt_user_id),
        )

        rows = [
            (user_id, chat_id, bet["name"], bet["amount"] * multiplier, bet["type"], bet["value"])
            for bet in user_bets
        ]
        await db.executemany(
            "INSERT INTO roulette_bets (user_id, chat_id, user_name, amount, type, value) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        await db.commit()

    if not state.get("first_bet_time"):
        game_state.setdefault(chat_id, {})["first_bet_time"] = time.time()

    mention = f'<a href="tg://user?id={user_id}">{user_bets[0]["name"]}</a>'
    verb = "удвоил" if action == "r_double" else "повторил"

    lines = []
    for bet in user_bets:
        new_amt = bet["amount"] * multiplier
        disp_val = format_bet_value(bet["value"])
        lines.append(f"{mention} ({fmt_money(new_amt)}) {verb} ставку на {disp_val}")

    await send_in_chunks(call.message.answer, lines)
    await call.answer()


# ---------------------------------------------------------------------------
# Команда «лог»
# ---------------------------------------------------------------------------

@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.lower() == "лог",
)
async def show_history(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT number, color FROM roulette_history WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 10",
            (message.chat.id,),
        ) as cur:
            history = await cur.fetchall()

    if not history:
        return await message.reply("История пуста.")

    text = "\n".join(f"{num}{col}" for num, col in history)
    await message.answer(text)


# ---------------------------------------------------------------------------
# Команда «ставки»
# ---------------------------------------------------------------------------

@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.lower() == "ставки",
)
async def cmd_my_bets(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    user_name = message.from_user.mention_html()

    async with aiosqlite.connect(DB_PATH, timeout=20.0) as db:
        async with db.execute(
            "SELECT amount, value FROM roulette_bets WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        ) as cur:
            user_bets = await cur.fetchall()

    if not user_bets:
        return await message.reply(
            f"{user_name}, у вас нет активных ставок в этом чате.", parse_mode="HTML"
        )

    lines = [
        f"{user_name} ваша ставка ({fmt_money(amount)}) на {format_bet_value(value)}"
        for amount, value in user_bets
    ]

    chunk_size = 10
    for i in range(0, len(lines), chunk_size):
        await message.answer(
            "\n".join(lines[i : i + chunk_size]), parse_mode="HTML"
        )


# ---------------------------------------------------------------------------
# Команда «отмена»
# ---------------------------------------------------------------------------

@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.lower() == "отмена",
)
async def cancel_bets(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    fmt_user_id = f"@{user_id}"

    if game_state.get(chat_id, {}).get("is_running"):
        return await message.reply("Нельзя отменить ставку во время игры!")

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        async with db.execute(
            "SELECT roulette_status FROM group_settings WHERE chat_id = ?", (chat_id,)
        ) as cur:
            row = await cur.fetchone()
            if row and row[0] == 0:
                return await message.reply("Игра отключена администратором!")

        await db.execute("BEGIN EXCLUSIVE")

        async with db.execute(
            "SELECT SUM(amount) FROM roulette_bets WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        ) as cur:
            result = await cur.fetchone()
            total_return = result[0] if result and result[0] is not None else 0

        if total_return <= 0:
            await db.execute("ROLLBACK")
            return await message.reply("У вас нет активных ставок в этом чате.")

        try:
            await db.execute(
                "DELETE FROM roulette_bets WHERE user_id = ? AND chat_id = ?",
                (user_id, chat_id),
            )
            await db.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (total_return, fmt_user_id),
            )
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"Ошибка при отмене ставок: {e}", exc_info=True)
            return await message.reply("Произошла ошибка при возврате средств.")

    # Чистим кэш
    if chat_id in last_user_bets_cache:
        last_user_bets_cache[chat_id].pop(user_id, None)

    # Если в чате не осталось ни одной ставки — сбрасываем таймер антифлуда.
    # Иначе пользователь мог бы отменить → подождать 12 сек → поставить заново
    # и сразу запустить го, минуя задержку.
    async with aiosqlite.connect(DB_PATH, timeout=10) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM roulette_bets WHERE chat_id = ?", (chat_id,)
        ) as cur:
            remaining = (await cur.fetchone())[0]

    if remaining == 0:
        game_state.setdefault(chat_id, {"is_running": False, "first_bet_time": None})[
            "first_bet_time"
        ] = None

    await message.reply(
        f"Ваши ставки в этом чате отменены. {fmt_money(total_return)} VIRTEX возвращены на баланс.",
        parse_mode="HTML",
    )

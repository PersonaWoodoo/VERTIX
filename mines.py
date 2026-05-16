import random
import asyncio
import uuid
from typing import Dict, Any

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from games import MIN_BET, fmt_money, parse_bet, get_user_balance, reserve_bet, finalize_bet, update_balance, require_subscriptions

router = Router()

NMINES_GAMES: Dict[str, Dict[str, Any]] = {}
_locks: Dict[int, asyncio.Lock] = {}


def _game_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _locks:
        _locks[user_id] = asyncio.Lock()
    return _locks[user_id]


def _new_gid(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:8]


# ==================== МНОЖИТЕЛИ ====================

def nmines_multipliers(mines_count: int, house_edge: float = 0.97) -> list[float]:
    cells = 9
    safe_cells = cells - mines_count
    p_survive = 1.0
    arr = [round(1.0 * house_edge, 4)]
    for k in range(1, safe_cells + 1):
        p_step = (safe_cells - (k - 1)) / (cells - (k - 1))
        p_survive *= p_step
        mult = (1.0 / p_survive) * house_edge if p_survive > 0 else float("inf")
        arr.append(round(mult, 4))
    return arr


# ==================== РЕНДЕР ====================

def nmines_keyboard(game: Dict[str, Any]) -> InlineKeyboardMarkup:
    gid = game["gid"]
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            txt = game["field"][idx]
            cb  = "nnoop" if txt != "❔" else f"nmines:{gid}:cell:{idx}"
            row.append(InlineKeyboardButton(text=txt, callback_data=cb))
        rows.append(row)

    opened = len(game["opened"])
    if opened > 0:
        multipliers = nmines_multipliers(int(game["mines_count"]))
        coef = multipliers[min(opened, len(multipliers) - 1)]
        potential = int(round(int(game["bet"]) * coef))
        rows.append([InlineKeyboardButton(text=f"💰 Забрать {fmt_money(potential)}", callback_data=f"nmines:{gid}:collect")])
    else:
        rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"nmines:{gid}:cancel")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ==================== ХЕНДЛЕРЫ ====================

@router.message(F.text.lower().startswith("мины"))
async def legacy_mines_start(message: Message, bot: Bot):
    if not await require_subscriptions(message, bot):
        return

    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("Формат: <code>мины 500</code> или <code>мины 500 3</code> (мины 1-4)", parse_mode="HTML")

    user_id = message.from_user.id
    async with _game_lock(user_id):
        if any(g.get("uid") == user_id and g.get("state") == "playing" for g in NMINES_GAMES.values()):
            return await message.answer("У тебя уже есть активная игра в мины.")

        try:
            bet = parse_bet(parts[1])
        except Exception:
            return await message.answer("Неверная ставка.")

        mines_count = 1
        if len(parts) >= 3:
            try:
                mines_count = int(parts[2])
            except Exception:
                pass
        if not (1 <= mines_count <= 4):
            return await message.answer("Количество мин: 1..4.")
        if bet < MIN_BET:
            return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")

        balance = await get_user_balance(user_id)
        if bet > balance:
            return await message.answer("Недостаточно VIRTEX.")

        ok = await reserve_bet(user_id, bet)
        if not ok:
            return await message.answer("Недостаточно VIRTEX.")

        gid = _new_gid("m")
        mines = random.sample(range(9), mines_count)
        game = {
            "gid": gid, "uid": user_id, "bet": int(bet),
            "mines_count": int(mines_count), "mines": mines,
            "opened": [], "field": ["❔"] * 9, "state": "playing"
        }
        NMINES_GAMES[gid] = game
        await message.answer(
            f"💣 <b>МИНЫ</b>\n\nСтавка: {fmt_money(bet)}\nМин: {mines_count}",
            reply_markup=nmines_keyboard(game),
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("nmines:"))
async def legacy_mines_cb(query: CallbackQuery):
    parts = query.data.split(":")
    if len(parts) < 3:
        return await query.answer()
    _, gid, action = parts[:3]
    idx = int(parts[3]) if len(parts) == 4 and parts[3].isdigit() else None

    game = NMINES_GAMES.get(gid)
    if not game:
        return await query.answer("Игра завершена", show_alert=True)
    if int(game["uid"]) != query.from_user.id:
        return await query.answer("Это не твоя игра", show_alert=True)

    async with _game_lock(query.from_user.id):
        game = NMINES_GAMES.get(gid)
        if not game or game.get("state") != "playing":
            return await query.answer("Игра завершена", show_alert=True)

        bet = int(game["bet"])
        mines_count = int(game["mines_count"])
        multipliers = nmines_multipliers(mines_count)

        if action == "cancel":
            if game["opened"]:
                return await query.answer("После открытия клеток отмена недоступна", show_alert=True)
            balance = await update_balance(query.from_user.id, bet)
            NMINES_GAMES.pop(gid, None)
            await query.message.edit_text(f"❌ Игра отменена. Возвращено: {fmt_money(bet)}\nБаланс: {fmt_money(balance)}")
            return await query.answer()

        if action == "collect":
            opened = len(game["opened"])
            if opened <= 0:
                return await query.answer("Пока нечего забирать", show_alert=True)
            coef = multipliers[min(opened, len(multipliers) - 1)]
            payout = int(round(bet * coef))
            balance = await finalize_bet(query.from_user.id, float(payout))
            NMINES_GAMES.pop(gid, None)
            await query.message.edit_text(f"💰 Выигрыш забран: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")
            return await query.answer()

        if action == "cell":
            if idx is None or not (0 <= idx <= 8):
                return await query.answer("Неверный индекс", show_alert=True)
            if idx in game["opened"]:
                return await query.answer("Уже открыто", show_alert=True)

            if idx in game["mines"]:
                game["state"] = "lost"
                game["field"][idx] = "💥"
                for m in game["mines"]:
                    if game["field"][m] == "❔":
                        game["field"][m] = "💣"
                balance = await finalize_bet(query.from_user.id, 0.0)
                NMINES_GAMES.pop(gid, None)
                await query.message.edit_text(f"💥 БОМБА! Вы проиграли.\nБаланс: {fmt_money(balance)}")
                return await query.answer()

            game["opened"].append(idx)
            game["field"][idx] = "✅"

            safe_needed = 9 - mines_count
            if len(game["opened"]) >= safe_needed:
                coef = multipliers[min(len(game["opened"]), len(multipliers) - 1)]
                payout = int(round(bet * coef))
                balance = await finalize_bet(query.from_user.id, float(payout))
                NMINES_GAMES.pop(gid, None)
                await query.message.edit_text(f"🎉 ПОБЕДА! Все безопасные клетки открыты.\nВыигрыш: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")
                return await query.answer()

            coef = multipliers[min(len(game["opened"]), len(multipliers) - 1)]
            potential = int(round(bet * coef))
            await query.message.edit_text(
                f"💣 <b>МИНЫ</b>\n\nСтавка: {fmt_money(bet)}\n"
                f"Открыто безопасных: {len(game['opened'])}\n"
                f"Множитель: x{coef}\nВозможный выигрыш: {fmt_money(potential)}",
                reply_markup=nmines_keyboard(game),
                parse_mode="HTML"
            )
            return await query.answer()

    await query.answer()

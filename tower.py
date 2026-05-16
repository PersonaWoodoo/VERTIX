import random
from typing import Dict, Any

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from games.config import MIN_BET
from games.utils import fmt_money, parse_bet, _game_lock, _new_gid, get_balance, reserve_bet, finalize_bet, add_balance
from games.subscriptions import require_subscriptions

router = Router()

NTOWER_GAMES: Dict[str, Dict[str, Any]] = {}


# ==================== МНОЖИТЕЛЬ ====================

def ntower_multiplier(level: int, mines: int, house_edge: float = 0.97, max_mult: float = 10000.0) -> float:
    mines = max(1, min(4, int(mines)))
    level = max(1, int(level))
    p_single = (5 - mines) / 5.0
    fair = float("inf") if p_single <= 0 else 1.0 / (p_single ** level)
    return round(min(fair * house_edge, max_mult), 2)


# ==================== РЕНДЕР ====================

def ntower_text(game: Dict[str, Any]) -> str:
    level = int(game["level"])
    mines = int(game["mines"])
    bet = int(game["bet"])
    next_level = min(level + 1, 9)
    now_mult  = ntower_multiplier(level, mines) if level > 0 else 0
    next_mult = ntower_multiplier(next_level, mines)
    return (
        f"🗼 <b>БАШНЯ</b>\n\n"
        f"Ставка: {fmt_money(bet)}\n"
        f"Мин в ряду: {mines}\n"
        f"Ряд: {next_level}/9\n"
        f"Текущий множитель: x{now_mult}\n"
        f"Следующий множитель: x{next_mult}\n"
        f"Потенциальный выигрыш: {fmt_money(int(bet * next_mult))}"
    )


def ntower_kb(game: Dict[str, Any]) -> InlineKeyboardMarkup:
    gid = game["gid"]
    level = int(game["level"])
    pick_row = [InlineKeyboardButton(text="❔", callback_data=f"ntower:{gid}:pick:{j}") for j in range(5)]
    action_row = (
        [InlineKeyboardButton(text="❌ Отмена",   callback_data=f"ntower:{gid}:cancel")]
        if level == 0 else
        [InlineKeyboardButton(text="💰 Забрать", callback_data=f"ntower:{gid}:collect")]
    )
    return InlineKeyboardMarkup(inline_keyboard=[pick_row, action_row])


# ==================== ХЕНДЛЕРЫ ====================

@router.message(F.text.lower().startswith("башня"))
async def legacy_tower_start(message: Message, bot: Bot):
    if not await require_subscriptions(message, bot):
        return

    parts = message.text.split()
    if len(parts) not in (2, 3):
        return await message.answer("Формат: <code>башня 500</code> или <code>башня 500 2</code> (мины 1-4)", parse_mode="HTML")

    user_id = message.from_user.id
    async with _game_lock(user_id):
        if any(g.get("uid") == user_id and g.get("state") == "playing" for g in NTOWER_GAMES.values()):
            return await message.answer("У тебя уже есть активная башня.")

        try:
            bet = parse_bet(parts[1])
        except Exception:
            return await message.answer("Неверная ставка.")

        mines = 1
        if len(parts) == 3:
            try:
                mines = int(parts[2])
            except Exception:
                pass
        if not (1 <= mines <= 4):
            return await message.answer("Количество мин: 1..4")
        if bet < MIN_BET:
            return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")

        balance = await get_balance(user_id)
        if bet > balance:
            return await message.answer("Недостаточно VIRTEX.")

        ok, _ = await reserve_bet(user_id, bet)
        if not ok:
            return await message.answer("Недостаточно VIRTEX.")

        bombs = []
        for _ in range(9):
            row = [0] * 5
            for idx in random.sample(range(5), mines):
                row[idx] = 1
            bombs.append(row)

        gid = _new_gid("t")
        game = {
            "gid": gid, "uid": user_id, "bet": int(bet), "mines": int(mines),
            "level": 0, "bombs": bombs, "selected": [], "state": "playing"
        }
        NTOWER_GAMES[gid] = game
        await message.answer(ntower_text(game), reply_markup=ntower_kb(game), parse_mode="HTML")


@router.callback_query(F.data.startswith("ntower:"))
async def legacy_tower_cb(query: CallbackQuery):
    parts = query.data.split(":")
    if len(parts) < 3:
        return await query.answer()
    _, gid, action = parts[:3]
    choice = int(parts[3]) if len(parts) == 4 and parts[3].isdigit() else None

    game = NTOWER_GAMES.get(gid)
    if not game:
        return await query.answer("Игра завершена", show_alert=True)
    if int(game["uid"]) != query.from_user.id:
        return await query.answer("Это не твоя игра", show_alert=True)

    async with _game_lock(query.from_user.id):
        game = NTOWER_GAMES.get(gid)
        if not game or game.get("state") != "playing":
            return await query.answer("Игра завершена", show_alert=True)

        if action == "cancel":
            if int(game["level"]) != 0:
                return await query.answer("После первого хода отмена недоступна", show_alert=True)
            bet = int(game["bet"])
            balance = add_balance(query.from_user.id, bet)
            NTOWER_GAMES.pop(gid, None)
            await query.message.edit_text(f"❌ Игра отменена. Возвращено: {fmt_money(bet)}\nБаланс: {fmt_money(balance)}")
            return await query.answer()

        if action == "collect":
            level = int(game["level"])
            if level <= 0:
                return await query.answer("Сделай хотя бы 1 ход", show_alert=True)
            mult = ntower_multiplier(level, int(game["mines"]))
            payout = int(round(int(game["bet"]) * mult))
            balance = await finalize_bet(query.from_user.id, float(game["bet"]), float(payout), "tower", f"collect_lvl={level}")
            NTOWER_GAMES.pop(gid, None)
            await query.message.edit_text(f"💰 Выигрыш забран: {fmt_money(payout)} (x{mult})\nБаланс: {fmt_money(balance)}")
            return await query.answer()

        if action == "pick":
            if choice is None or not (0 <= choice <= 4):
                return await query.answer("Неверный выбор", show_alert=True)
            level = int(game["level"])
            if not (0 <= level <= 8):
                return await query.answer("Неверный уровень", show_alert=True)

            game["selected"].append(choice)
            if game["bombs"][level][choice] == 1:
                game["state"] = "lost"
                balance = await finalize_bet(query.from_user.id, float(game["bet"]), 0.0, "tower", "lose")
                NTOWER_GAMES.pop(gid, None)
                await query.message.edit_text(f"💥 Поражение! Вы наткнулись на мину на уровне {level + 1}.\nБаланс: {fmt_money(balance)}")
                return await query.answer()

            game["level"] = level + 1
            if int(game["level"]) >= 9:
                mult = ntower_multiplier(9, int(game["mines"]))
                payout = int(round(int(game["bet"]) * mult))
                balance = await finalize_bet(query.from_user.id, float(game["bet"]), float(payout), "tower", "won_top")
                NTOWER_GAMES.pop(gid, None)
                await query.message.edit_text(f"🎉 ПОБЕДА! Башня пройдена!\nВыигрыш: {fmt_money(payout)} (x{mult})\nБаланс: {fmt_money(balance)}")
                return await query.answer()

            NTOWER_GAMES[gid] = game
            await query.message.edit_text(ntower_text(game), reply_markup=ntower_kb(game), parse_mode="HTML")
            return await query.answer()

    await query.answer()

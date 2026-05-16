import random
import asyncio
import uuid
from typing import Dict, Any

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from games import MIN_BET, fmt_money, parse_bet, get_user_balance, reserve_bet, finalize_bet, update_balance, require_subscriptions

router = Router()

NGOLD_GAMES: Dict[str, Dict[str, Any]] = {}
_locks: Dict[int, asyncio.Lock] = {}

# Множители для игры Золото
LEGACY_GOLD_MULTIPLIERS = [1.5, 2.0, 2.8, 3.8, 5.2, 7.0, 9.5, 13.0, 18.0]


def _game_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _locks:
        _locks[user_id] = asyncio.Lock()
    return _locks[user_id]


def _new_gid(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:8]


# ==================== РЕНДЕР ====================

def ngold_render(game: Dict[str, Any]) -> str:
    stake = int(game["stake"])
    level = int(game["current_level"])
    levels = len(LEGACY_GOLD_MULTIPLIERS)
    current_multiplier = LEGACY_GOLD_MULTIPLIERS[level - 1] if level > 0 else 0
    next_multiplier = LEGACY_GOLD_MULTIPLIERS[level] if level < levels else LEGACY_GOLD_MULTIPLIERS[-1]
    current_amount = int(round(stake * current_multiplier))
    next_amount = int(round(stake * next_multiplier))

    rows = []
    for i in reversed(range(levels)):
        if i < len(game["path"]):
            left  = "✅" if game["path"][i] == 0 else "◻️"
            right = "✅" if game["path"][i] == 1 else "◻️"
        else:
            left = right = "❔"
        value = fmt_money(int(round(stake * LEGACY_GOLD_MULTIPLIERS[i])))
        rows.append(f"|{left}|{right}| {value} ({LEGACY_GOLD_MULTIPLIERS[i]}x)")

    return (
        f"🥇 <b>ЗОЛОТО</b>\n\n"
        f"Ставка: {fmt_money(stake)}\n"
        f"Текущий множитель: x{current_multiplier} ({fmt_money(current_amount)})\n"
        f"Следующий шаг: x{next_multiplier} ({fmt_money(next_amount)})\n\n"
        + "\n".join(rows)
    )


def ngold_kb(gid: str, level: int) -> InlineKeyboardMarkup:
    pick_row = [
        InlineKeyboardButton(text="❔", callback_data=f"ngold:{gid}:pick:0"),
        InlineKeyboardButton(text="❔", callback_data=f"ngold:{gid}:pick:1"),
    ]
    action_row = (
        [InlineKeyboardButton(text="❌ Отмена",   callback_data=f"ngold:{gid}:cancel")]
        if level == 0 else
        [InlineKeyboardButton(text="💰 Забрать", callback_data=f"ngold:{gid}:collect")]
    )
    return InlineKeyboardMarkup(inline_keyboard=[pick_row, action_row])


# ==================== ХЕНДЛЕРЫ ====================

@router.message(F.text.lower().startswith("золото"))
async def legacy_gold_start(message: Message, bot: Bot):
    if not await require_subscriptions(message, bot):
        return

    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("Формат: <code>золото 500</code> или <code>золото 1к</code>", parse_mode="HTML")

    user_id = message.from_user.id
    async with _game_lock(user_id):
        if any(g.get("uid") == user_id and g.get("state") == "playing" for g in NGOLD_GAMES.values()):
            return await message.answer("Сначала заверши текущую игру в золото.")

        balance = await get_user_balance(user_id)
        try:
            stake = parse_bet(parts[1])
        except Exception:
            return await message.answer("Неверная ставка.")

        if stake < MIN_BET:
            return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        if stake > balance:
            return await message.answer("Недостаточно VIRTEX.")

        ok = await reserve_bet(user_id, stake)
        if not ok:
            return await message.answer("Недостаточно VIRTEX.")

        levels = len(LEGACY_GOLD_MULTIPLIERS)
        bad_cells = [random.randint(0, 1) for _ in range(levels)]
        gid = _new_gid("g")
        game = {
            "gid": gid, "uid": user_id, "stake": int(stake),
            "bad_cells": bad_cells, "current_level": 0, "path": [], "state": "playing"
        }
        NGOLD_GAMES[gid] = game
        await message.answer(ngold_render(game), reply_markup=ngold_kb(gid, 0), parse_mode="HTML")


@router.callback_query(F.data.startswith("ngold:"))
async def legacy_gold_cb(query: CallbackQuery):
    parts = query.data.split(":")
    if len(parts) < 3:
        return await query.answer()
    _, gid, action = parts[:3]
    choice = int(parts[3]) if len(parts) == 4 and parts[3].isdigit() else None

    game = NGOLD_GAMES.get(gid)
    if not game:
        return await query.answer("Игра завершена", show_alert=True)
    if game["uid"] != query.from_user.id:
        return await query.answer("Это не твоя игра", show_alert=True)

    async with _game_lock(query.from_user.id):
        game = NGOLD_GAMES.get(gid)
        if not game or game.get("state") != "playing":
            return await query.answer("Игра завершена", show_alert=True)

        if action == "cancel":
            if int(game["current_level"]) != 0:
                return await query.answer("Нельзя отменить после хода", show_alert=True)
            stake = int(game["stake"])
            balance = await update_balance(query.from_user.id, stake)
            NGOLD_GAMES.pop(gid, None)
            await query.message.edit_text(f"❌ Игра отменена. Возвращено: {fmt_money(stake)}\nБаланс: {fmt_money(balance)}")
            return await query.answer()

        if action == "collect":
            level = int(game["current_level"])
            if level <= 0:
                return await query.answer("Сделай хотя бы 1 ход", show_alert=True)
            mult = LEGACY_GOLD_MULTIPLIERS[level - 1]
            payout = int(round(int(game["stake"]) * mult))
            balance = await finalize_bet(query.from_user.id, float(payout))
            NGOLD_GAMES.pop(gid, None)
            await query.message.edit_text(f"💰 Выигрыш забран: {fmt_money(payout)} (x{mult})\nБаланс: {fmt_money(balance)}")
            return await query.answer()

        if action == "pick":
            if choice not in {0, 1}:
                return await query.answer("Неверный выбор", show_alert=True)
            level = int(game["current_level"])
            if level >= len(LEGACY_GOLD_MULTIPLIERS):
                return await query.answer("Игра завершена", show_alert=True)

            bad = int(game["bad_cells"][level])
            game["path"].append(choice)

            if bad == choice:
                game["state"] = "lost"
                balance = await finalize_bet(query.from_user.id, 0.0)
                NGOLD_GAMES.pop(gid, None)
                await query.message.edit_text(f"💥 Поражение! Вы наткнулись на ловушку.\nБаланс: {fmt_money(balance)}")
                return await query.answer()

            game["current_level"] = level + 1
            if game["current_level"] >= len(LEGACY_GOLD_MULTIPLIERS):
                payout = int(round(int(game["stake"]) * LEGACY_GOLD_MULTIPLIERS[-1]))
                balance = await finalize_bet(query.from_user.id, float(payout))
                NGOLD_GAMES.pop(gid, None)
                await query.message.edit_text(f"🎉 ПОБЕДА! Все уровни пройдены!\nВыигрыш: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")
                return await query.answer()

            NGOLD_GAMES[gid] = game
            await query.message.edit_text(ngold_render(game), reply_markup=ngold_kb(gid, int(game["current_level"])), parse_mode="HTML")
            return await query.answer()

    await query.answer()

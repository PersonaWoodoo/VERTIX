from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

router = Router()


def get_help_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Игры", callback_data="help_games_menu"),
         InlineKeyboardButton(text="📜 Команды", callback_data="help_cmds")],
        [InlineKeyboardButton(text="👥 Рефералы", callback_data="help_ref"),
         InlineKeyboardButton(text="🏦 Банк", callback_data="help_bank")],
    ])


def get_help_games_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Рулетка", callback_data="help_game_roulette"),
         InlineKeyboardButton(text="💣 Мины", callback_data="help_game_mines")],
        [InlineKeyboardButton(text="🚀 Краш", callback_data="help_game_crash"),
         InlineKeyboardButton(text="🗼 Башня", callback_data="help_game_tower")],
        [InlineKeyboardButton(text="🎲 Кубик", callback_data="help_game_cube"),
         InlineKeyboardButton(text="🎯 Кости", callback_data="help_game_dice")],
        [InlineKeyboardButton(text="⚽ Футбол", callback_data="help_game_football"),
         InlineKeyboardButton(text="🏀 Баскетбол", callback_data="help_game_basket")],
        [InlineKeyboardButton(text="🥇 Золото", callback_data="help_game_gold")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="help_main")],
    ])


def get_back_kb(target: str = "help_main"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=target)]
    ])


TEXT_MAIN = "❓ <b>Справочник по боту VIRTEX</b>\n\nВыберите интересующий раздел:"

TEXT_GAMES_MENU = "🎮 <b>Доступные игры</b>\n\nВыберите игру для получения правил:"

TEXT_GAME_ROULETTE = (
    "🎰 <b>РУЛЕТКА</b>\n\n"
    "📌 <b>Формат ставки:</b>\n"
    "<code>рул 5000 кра</code> - красное\n"
    "<code>рул 5000 чер</code> - чёрное\n"
    "<code>рул 5000 чет</code> - чётное\n"
    "<code>рул 5000 нечет</code> - нечётное\n"
    "<code>рул 5000 зеро</code> - зеро (0)\n"
    "<code>рул 5000 7</code> - число 7\n"
    "<code>рул 5000 12-18</code> - диапазон\n\n"
    "🎲 <b>Шансы:</b>\n"
    "• Цвет/чётность: 48.65% (x2)\n"
    "• Одно число: 2.7% (x36)\n"
    "• Диапазон: зависит от кол-ва чисел"
)

TEXT_GAME_MINES = (
    "💣 <b>МИНЫ 5x5</b>\n\n"
    "📌 <b>Формат:</b>\n"
    "<code>мины 500 8</code> - ставка 500, 8 мин\n"
    "Мины: 1-24\n\n"
    "📊 <b>Множители:</b>\n"
    "• 1 мина: до x24.25\n"
    "• 5 мин: до x6.25\n"
    "• 10 мин: до x2.89\n"
    "• 15 мин: до x1.97\n"
    "• 20 мин: до x1.53"
)

TEXT_GAME_CRASH = (
    "🚀 <b>КРАШ</b>\n\n"
    "📌 <b>Формат:</b>\n"
    "<code>краш 500 2.5</code>\n\n"
    "🎲 Правила:\n"
    "• Множитель растёт от 1.0x\n"
    "• Забирайте выигрыш до падения\n"
    "• Если множитель упал выше вашего - выигрыш!"
)

TEXT_GAME_TOWER = (
    "🗼 <b>БАШНЯ</b>\n\n"
    "📌 <b>Формат:</b>\n"
    "<code>башня 500</code>\n\n"
    "🎲 Правила:\n"
    "• 9 уровней по 5 клеток\n"
    "• Одна мина на уровне\n"
    "• Чем выше уровень - тем больше множитель\n"
    "• Множители: x1.10 → x5.65"
)

TEXT_GAME_CUBE = (
    "🎲 <b>КУБИК</b>\n\n"
    "📌 <b>Формат:</b>\n"
    "<code>кубик 500 3</code> - число\n"
    "<code>кубик 1000 чет</code> - чёт\n"
    "<code>кубик 1000 нечет</code> - нечёт\n"
    "<code>кубик 1000 б</code> - больше 3\n"
    "<code>кубик 1000 м</code> - меньше 4\n\n"
    "🎲 <b>Множители:</b>\n"
    "• Точное число: x3.5\n"
    "• Чёт/нечет/б/м: x1.9"
)

TEXT_GAME_DICE = (
    "🎯 <b>КОСТИ</b>\n\n"
    "📌 <b>Формат:</b>\n"
    "<code>кости 500 м</code> - меньше 7\n"
    "<code>кости 1000 б</code> - больше 7\n"
    "<code>кости 1000 равно</code> - ровно 7\n\n"
    "🎲 <b>Множители:</b>\n"
    "• Меньше/больше 7: x2.25\n"
    "• Ровно 7: x5.0"
)

TEXT_GAME_FOOTBALL = (
    "⚽ <b>ФУТБОЛ</b>\n\n"
    "📌 <b>Формат:</b>\n"
    "<code>футбол 500 гол</code>\n"
    "<code>футбол 1000 мимо</code>\n\n"
    "🎲 <b>Множитель:</b> x1.85"
)

TEXT_GAME_BASKET = (
    "🏀 <b>БАСКЕТБОЛ</b>\n\n"
    "📌 <b>Формат:</b>\n"
    "<code>баскет 500</code>\n\n"
    "🎲 <b>Множитель:</b> x2.2"
)

TEXT_GAME_GOLD = (
    "🥇 <b>ЗОЛОТО</b>\n\n"
    "📌 <b>Формат:</b>\n"
    "<code>золото 500</code>\n\n"
    "🎲 Правила:\n"
    "• 9 уровней по 2 ячейки\n"
    "• Одна ячейка с миной\n"
    "• Множители: x1.5 → x18.0"
)

TEXT_CMDS = (
    "📜 <b>ОСНОВНЫЕ КОМАНДЫ</b>\n\n"
    "┌─────────────────────┐\n"
    "│ <b>💰 БАЛАНС</b>\n"
    "├─────────────────────┤\n"
    "│ • <code>б</code> - баланс\n"
    "│ • <code>дать 100 @user</code> - перевод\n"
    "├─────────────────────┤\n"
    "│ <b>🏆 ТОПЫ</b>\n"
    "├─────────────────────┤\n"
    "│ • <code>/top</code> - топ мира\n"
    "│ • <code>/topchat</code> - топ чата\n"
    "├─────────────────────┤\n"
    "│ <b>🎮 ИГРЫ</b>\n"
    "├─────────────────────┤\n"
    "│ • <code>/банк</code> - депозиты\n"
    "│ • <code>/donate</code> - пополнение\n"
    "│ • <code>🎁 Бонус</code> - бонус\n"
    "├─────────────────────┤\n"
    "│ <b>👥 РЕФЕРАЛЫ</b>\n"
    "├─────────────────────┤\n"
    "│ • <code>реферал</code> - ссылка\n"
    "│ • +2500 VIRTEX за друга\n"
    "└─────────────────────┘"
)

TEXT_REF = (
    "👥 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
    "📌 Как это работает:\n"
    "• Приглашайте друзей по ссылке\n"
    "• За каждого друга +2500 VIRTEX\n"
    "• Безлимит!\n\n"
    "🔗 Ваша ссылка: <code>/реферал</code>"
)

TEXT_BANK = (
    "🏦 <b>БАНКОВСКАЯ СИСТЕМА</b>\n\n"
    "📌 <b>Депозиты:</b>\n"
    "• 7 дней — +3%\n"
    "• 14 дней — +7%\n"
    "• 30 дней — +18%\n\n"
    "📌 <b>Команды:</b>\n"
    "• <code>/банк</code> - открыть меню"
)


@router.message(F.text.lower().in_({"игры", "помощь", "команды", "❓ помощь", "help"}))
async def cmd_help(message: Message):
    await message.answer(TEXT_MAIN, reply_markup=get_help_main_kb(), parse_mode="HTML")


@router.callback_query(F.data == "help_main")
async def call_help_main(call: CallbackQuery):
    await call.message.edit_text(TEXT_MAIN, reply_markup=get_help_main_kb(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_cmds")
async def call_help_cmds(call: CallbackQuery):
    await call.message.edit_text(TEXT_CMDS, reply_markup=get_back_kb(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_ref")
async def call_help_ref(call: CallbackQuery):
    await call.message.edit_text(TEXT_REF, reply_markup=get_back_kb(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_bank")
async def call_help_bank(call: CallbackQuery):
    await call.message.edit_text(TEXT_BANK, reply_markup=get_back_kb(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_games_menu")
async def call_help_games_menu(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAMES_MENU, reply_markup=get_help_games_kb(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_game_roulette")
async def call_help_game_roulette(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAME_ROULETTE, reply_markup=get_back_kb("help_games_menu"), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_game_mines")
async def call_help_game_mines(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAME_MINES, reply_markup=get_back_kb("help_games_menu"), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_game_crash")
async def call_help_game_crash(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAME_CRASH, reply_markup=get_back_kb("help_games_menu"), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_game_tower")
async def call_help_game_tower(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAME_TOWER, reply_markup=get_back_kb("help_games_menu"), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_game_cube")
async def call_help_game_cube(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAME_CUBE, reply_markup=get_back_kb("help_games_menu"), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_game_dice")
async def call_help_game_dice(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAME_DICE, reply_markup=get_back_kb("help_games_menu"), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_game_football")
async def call_help_game_football(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAME_FOOTBALL, reply_markup=get_back_kb("help_games_menu"), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_game_basket")
async def call_help_game_basket(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAME_BASKET, reply_markup=get_back_kb("help_games_menu"), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_game_gold")
async def call_help_game_gold(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAME_GOLD, reply_markup=get_back_kb("help_games_menu"), parse_mode="HTML")
    await call.answer()

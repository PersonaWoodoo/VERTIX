import sqlite3
import datetime
import logging
import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = "bot_db.sqlite"
DB_NAME = DB_PATH  # Алиас для обратной совместимости


# ---------------------------------------------------------------------------
# Инициализация
# ---------------------------------------------------------------------------

def _apply_pragma(conn: sqlite3.Connection):
    """Применяет оптимальные настройки SQLite к соединению."""
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")


def _migrate(c: sqlite3.Cursor):
    """
    Безопасные ALTER TABLE — добавляем колонки только если их ещё нет.
    Все миграции в одном месте, без дублирования.
    """
    migrations = [
        ("users", "pl_gold INTEGER DEFAULT 0"),
        ("users", "stars INTEGER DEFAULT 0"),
        ("users", "hide_mention INTEGER DEFAULT 0"),
        ("users", "custom_nickname TEXT"),
        ("users", "custom_nick TEXT"),
        ("users", "joined_date TEXT"),
        ("users", "vip_until TEXT"),
        ("users", "registered_at TEXT"),
        ("users", "rep_plus INTEGER DEFAULT 0"),
        ("users", "rep_minus INTEGER DEFAULT 0"),
        ("users", "is_bot INTEGER DEFAULT 0"),  # <-- исключение ботов из топа
        ("group_settings", "basket_status INTEGER DEFAULT 1"),
        ("group_settings", "crash_status INTEGER DEFAULT 1"),
        ("group_settings", "mines_status INTEGER DEFAULT 1"),
        ("group_rules", "rules_entities TEXT"),
    ]
    for table, column_def in migrations:
        col_name = column_def.split()[0]
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует


def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    _apply_pragma(conn)
    c = conn.cursor()

    # ----- Таблицы -----
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT UNIQUE,
            name            TEXT,
            username        TEXT,
            registered_at   TEXT,
            balance         INTEGER DEFAULT 0,
            pl_gold         INTEGER DEFAULT 0,
            is_banned       INTEGER DEFAULT 0,
            last_bonus      TEXT,
            roulette_total_won INTEGER DEFAULT 0,
            rep_plus        INTEGER DEFAULT 0,
            rep_minus       INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS rep_limits (
            user_id     INTEGER PRIMARY KEY,
            count       INTEGER DEFAULT 0,
            last_reset  TEXT
        );

        CREATE TABLE IF NOT EXISTS group_kazna (
            chat_id         INTEGER PRIMARY KEY,
            balance         INTEGER DEFAULT 0,
            reward_per_user INTEGER DEFAULT 0,
            status          INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS user_stats (
            chat_id         INTEGER,
            user_id         INTEGER,
            message_count   INTEGER DEFAULT 0,
            total_messages  INTEGER DEFAULT 0,
            last_reset      DATE DEFAULT (CURRENT_DATE),
            PRIMARY KEY (chat_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS exchange_rate (
            id   INTEGER PRIMARY KEY,
            rate INTEGER DEFAULT 2450
        );

        CREATE TABLE IF NOT EXISTS invited_users (
            chat_id    INTEGER,
            invited_id INTEGER,
            PRIMARY KEY (chat_id, invited_id)
        );

        CREATE TABLE IF NOT EXISTS mine_games (
            user_id        INTEGER,
            chat_id        INTEGER,
            message_id     INTEGER,
            bet            INTEGER,
            mines_map      TEXT,
            revealed_cells TEXT,
            last_action    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, chat_id)
        );

        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id         INTEGER PRIMARY KEY,
            roulette_status INTEGER DEFAULT 1,
            mines_status    INTEGER DEFAULT 1,
            crash_status    INTEGER DEFAULT 1,
            casino_balance  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS promos (
            code          TEXT PRIMARY KEY,
            amount        INTEGER NOT NULL,
            max_uses      INTEGER NOT NULL,
            current_uses  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS group_rules (
            chat_id    INTEGER PRIMARY KEY,
            rules_text TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS promo_logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            promo_code TEXT NOT NULL,
            timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (promo_code) REFERENCES promos(code)
        );

        CREATE TABLE IF NOT EXISTS transfers (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            from_id   TEXT,
            from_name TEXT,
            to_id     TEXT,
            to_name   TEXT,
            amount    INTEGER,
            type      TEXT,
            timestamp TEXT
        );

        CREATE TABLE IF NOT EXISTS roulette_bets (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER,
            chat_id   INTEGER,
            user_name TEXT,
            amount    INTEGER,
            type      TEXT,
            value     TEXT
        );

        CREATE TABLE IF NOT EXISTS roulette_history (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id   INTEGER,
            number    INTEGER,
            color     TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS global_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS tournament_stats (
            user_id   INTEGER PRIMARY KEY,
            user_name TEXT,
            profit    INTEGER DEFAULT 0
        );
    """)
    c.executescript("""
        CREATE TABLE IF NOT EXISTS tournament_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            tournament  TEXT,
            result      TEXT,
            date_time   TEXT
        );
    """)


    # Индексы для ускорения частых запросов рулетки
    c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_roulette_bets_chat ON roulette_bets(chat_id);
        CREATE INDEX IF NOT EXISTS idx_roulette_bets_user_chat ON roulette_bets(user_id, chat_id);
        CREATE INDEX IF NOT EXISTS idx_roulette_history_chat ON roulette_history(chat_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
    """)

    # Дефолтные значения настроек
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('page_history_emoji', '📄')")
    c.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('crash_prefix', '🚀')")

    # Миграции существующих баз
    _migrate(c)

    conn.commit()
    conn.close()
    logger.info("База данных инициализирована.")


# ---------------------------------------------------------------------------
# Асинхронные функции (для рулетки и других игр)
# ---------------------------------------------------------------------------

async def modify_balance(user_id: int, amount: int):
    """Обновляет баланс асинхронно. Принимает числовой user_id."""
    fmt_id = f"@{user_id}"
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, fmt_id)
        )
        await db.commit()


async def check_group(chat_id: int):
    """Создаёт запись настроек для группы, если её ещё нет."""
    async with aiosqlite.connect(DB_NAME, timeout=30) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("INSERT OR IGNORE INTO group_settings (chat_id) VALUES (?)", (chat_id,))
        await db.commit()


async def get_stats_view(chat_id: int, page: int = 0, is_all: bool = False):
    per_page = 12 if not is_all else 30
    order_col = "total_messages" if is_all else "message_count"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                chat_id        INTEGER,
                user_id        INTEGER,
                message_count  INTEGER DEFAULT 0,
                total_messages INTEGER DEFAULT 0,
                last_reset     DATE DEFAULT (CURRENT_DATE),
                PRIMARY KEY (chat_id, user_id)
            )
        """)

        try:
            query = f"""
                SELECT s.user_id, s.{order_col}, u.custom_nick
                FROM user_stats s
                LEFT JOIN users u ON s.user_id = CAST(SUBSTR(u.user_id, 2) AS INTEGER)
                WHERE s.chat_id = ? AND s.{order_col} > 0
                ORDER BY s.{order_col} DESC
            """
            async with db.execute(query, (chat_id,)) as cur:
                rows = await cur.fetchall()
        except sqlite3.OperationalError:
            query = f"""
                SELECT user_id, {order_col}, NULL
                FROM user_stats
                WHERE chat_id = ?
                ORDER BY {order_col} DESC
            """
            async with db.execute(query, (chat_id,)) as cur:
                rows = await cur.fetchall()

    if not rows:
        return "Статистика пока пуста.", None

    return rows, per_page


# ---------------------------------------------------------------------------
# Синхронные функции
# ---------------------------------------------------------------------------

def _connect(timeout: int = 30) -> sqlite3.Connection:
    """Открывает соединение с оптимальными настройками."""
    conn = sqlite3.connect(DB_PATH, timeout=timeout)
    _apply_pragma(conn)
    return conn


def add_user(user_id: int, name: str, username: str):
    fmt_user_id = f"@{user_id}"
    fmt_username = f"@{username}" if username else "Нет"
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("SELECT name, username FROM users WHERE user_id = ?", (fmt_user_id,))
        row = c.fetchone()
        if not row:
            c.execute(
                "INSERT INTO users (user_id, name, username, registered_at, balance) VALUES (?, ?, ?, ?, ?)",
                (fmt_user_id, name, fmt_username, current_time, 0),
            )
        else:
            db_name, db_username = row
            if db_name != name or db_username != fmt_username:
                c.execute(
                    "UPDATE users SET name = ?, username = ? WHERE user_id = ?",
                    (name, fmt_username, fmt_user_id),
                )
        conn.commit()
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка в add_user: {e}")
    finally:
        conn.close()


def get_balance(user_id: int) -> int:
    fmt_user_id = f"@{user_id}" if not str(user_id).startswith("@") else user_id
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("SELECT balance FROM users WHERE user_id = ?", (fmt_user_id,))
        result = c.fetchone()
        return result[0] if result else 0
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка при получении баланса VIRTEX: {e}")
        return 0
    finally:
        conn.close()


def make_transfer(
    from_user_id: int,
    from_name: str,
    to_user_id: int,
    to_name: str,
    amount: int,
    currency: str = "balance",
) -> bool:
    if currency not in ("balance", "gold"):
        logger.error(f"Неизвестная валюта: {currency}")
        return False

    db_column = "pl_gold" if currency == "gold" else "balance"
    f_id = f"@{from_user_id}"
    t_id = f"@{to_user_id}"

    conn = _connect(timeout=20)
    try:
        c = conn.cursor()
        c.execute(f"SELECT {db_column} FROM users WHERE user_id = ?", (f_id,))
        res = c.fetchone()
        if not res or (res[0] or 0) < amount:
            return False

        c.execute(f"UPDATE users SET {db_column} = {db_column} - ? WHERE user_id = ?", (amount, f_id))
        try:
            c.execute(
                "INSERT OR IGNORE INTO users (user_id, name, balance, pl_gold) VALUES (?, ?, 0, 0)",
                (t_id, to_name),
            )
        except sqlite3.OperationalError:
            c.execute("INSERT OR IGNORE INTO users (user_id, name) VALUES (?, ?)", (t_id, to_name))
        c.execute(f"UPDATE users SET {db_column} = {db_column} + ? WHERE user_id = ?", (amount, t_id))

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "INSERT INTO transfers (from_id, from_name, to_id, to_name, amount, type, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f_id, from_name, t_id, to_name, amount, f"transfer_{currency}", now),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка в make_transfer ({currency}): {e}")
        return False
    finally:
        conn.close()


def get_history(user_id: int):
    conn = _connect()
    c = conn.cursor()
    u_id = f"@{user_id}"
    try:
        c.execute(
            """
            SELECT amount, from_name, to_name, timestamp, from_id, to_id, type
            FROM transfers
            WHERE to_id = ? OR from_id = ?
            ORDER BY id DESC LIMIT 20
            """,
            (u_id, u_id),
        )
        return c.fetchall()
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка получения истории: {e}")
        return []
    finally:
        conn.close()


def update_balance(user_id: str, amount: int):
    """Для админ-команд: user_id в формате @12345."""
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка при обновлении баланса VIRTEX: {e}")
    finally:
        conn.close()


def set_ban_status(user_id: str, status: int):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (status, user_id))
        conn.commit()
    finally:
        conn.close()


def is_user_banned(user_id: int) -> bool:
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("SELECT is_banned FROM users WHERE user_id = ?", (f"@{user_id}",))
        res = c.fetchone()
        return bool(res[0]) if res else False
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка проверки бана: {e}")
        return False
    finally:
        conn.close()


def log_donate(user_id: int, payment_id: str, amount: int, stars: int, currency: str = "balance") -> bool:
    if currency == "gold":
        db_column, history_type, currency_label = "pl_gold", "donate_gold", "VIRTEX-GOLD"
    else:
        db_column, history_type, currency_label = "balance", "donate", "VIRTEX"

    f_id = f"@{user_id}"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = _connect(timeout=20)
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO transfers (from_id, from_name, to_id, to_name, amount, type, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("SYSTEM", "SYSTEM", f_id, f"Stars: {stars} ({currency_label})", amount, history_type, now),
        )
        c.execute(
            "INSERT OR IGNORE INTO users (user_id, name, balance, pl_gold) VALUES (?, ?, 0, 0)",
            (f_id, "Пользователь"),
        )
        c.execute(f"UPDATE users SET {db_column} = {db_column} + ? WHERE user_id = ?", (amount, f_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка в log_donate: {e}")
        return False
    finally:
        conn.close()


def get_user_bonus_info(user_id: int):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("SELECT last_bonus FROM users WHERE user_id = ?", (f"@{user_id}",))
        res = c.fetchone()
        return res[0] if res else None
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка чтения бонуса: {e}")
        return None
    finally:
        conn.close()


def give_bonus(user_id: int, amount: int):
    conn = _connect()
    c = conn.cursor()
    now = datetime.datetime.now().isoformat()
    try:
        c.execute(
            "UPDATE users SET balance = balance + ?, last_bonus = ? WHERE user_id = ?",
            (amount, now, f"@{user_id}"),
        )
        conn.commit()
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка при выдаче бонуса VIRTEX: {e}")
    finally:
        conn.close()


def get_vip_status(user_id: int) -> bool:
    conn = _connect(timeout=20)
    c = conn.cursor()
    try:
        c.execute("SELECT vip_until FROM users WHERE user_id = ?", (f"@{user_id}",))
        res = c.fetchone()
    finally:
        conn.close()

    if res and res[0]:
        from datetime import datetime
        return datetime.fromisoformat(res[0]) > datetime.now()
    return False


def give_vip_month(user_id: int):
    from datetime import datetime, timedelta
    conn = _connect(timeout=20)
    c = conn.cursor()
    new_until = (datetime.now() + timedelta(days=30)).isoformat()
    try:
        c.execute("UPDATE users SET vip_until = ? WHERE user_id = ?", (new_until, f"@{user_id}"))
        conn.commit()
    finally:
        conn.close()


def remove_vip(user_id: int):
    conn = _connect(timeout=20)
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET vip_until = NULL WHERE user_id = ?", (f"@{user_id}",))
        conn.commit()
    finally:
        conn.close()


def get_user_info(target_id: str):
    if not target_id.replace("@", "").isdigit():
        user_by_name = get_user_by_username(target_id)
        if user_by_name:
            target_id = user_by_name[0]
        else:
            return None

    clean_id = target_id.replace("@", "")
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT name, balance, pl_gold, vip_until FROM users WHERE user_id = ?",
            (f"@{clean_id}",),
        )
        return c.fetchone()
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка SQL в get_user_info: {e}")
        return None
    finally:
        conn.close()


def set_nickname(user_id: int, nickname: str):
    conn = _connect(timeout=20)
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET custom_nickname = ? WHERE user_id = ?", (nickname, f"@{user_id}"))
        conn.commit()
    finally:
        conn.close()


def get_full_user(user_id: int):
    conn = _connect(timeout=20)
    c = conn.cursor()
    try:
        c.execute(
            "SELECT name, custom_nickname, registered_at, rep_plus, rep_minus FROM users WHERE user_id = ?",
            (f"@{user_id}",),
        )
        return c.fetchone()
    finally:
        conn.close()


def get_user_by_username(username: str):
    conn = _connect()
    c = conn.cursor()
    clean_username = username if username.startswith("@") else f"@{username}"
    try:
        c.execute("SELECT user_id, name FROM users WHERE username = ?", (clean_username,))
        return c.fetchone()
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка при поиске по юзернейму: {e}")
        return None
    finally:
        conn.close()


def update_user_info(user_id, name, username):
    fmt_user_id = f"@{user_id}" if not str(user_id).startswith("@") else user_id
    fmt_username = f"@{username}" if username else "Нет"
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute(
            "UPDATE users SET name = ?, username = ? WHERE user_id = ?",
            (name, fmt_username, fmt_user_id),
        )
        conn.commit()
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка базы данных: {e}")
    finally:
        conn.close()


def update_gold(user_id: str, amount: int):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET pl_gold = pl_gold + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка update_gold: {e}")
    finally:
        conn.close()


def get_gold_balance(user_id) -> int:
    fmt_user_id = f"@{user_id}" if not str(user_id).startswith("@") else user_id
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("SELECT pl_gold FROM users WHERE user_id = ?", (fmt_user_id,))
        result = c.fetchone()
        return result[0] if result and result[0] is not None else 0
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка в get_gold_balance (VIRTEX-GOLD): {e}")
        return 0
    finally:
        conn.close()


def get_group_settings(chat_id: int):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute("SELECT * FROM group_settings WHERE chat_id = ?", (chat_id,))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_exchange_rate() -> int:
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("SELECT rate FROM exchange_rate WHERE id = 1")
        res = c.fetchone()
        if not res:
            c.execute("INSERT INTO exchange_rate (id, rate) VALUES (1, 2450)")
            conn.commit()
            return 2450
        return res[0]
    finally:
        conn.close()


def set_exchange_rate(new_rate: int):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("UPDATE exchange_rate SET rate = ? WHERE id = 1", (new_rate,))
        conn.commit()
    finally:
        conn.close()


def transaction_buy_gold(user_id: int, plugs_cost: int, gold_amount: int) -> bool:
    fmt_id = f"@{user_id}"
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("BEGIN EXCLUSIVE")
        c.execute("SELECT balance FROM users WHERE user_id = ?", (fmt_id,))
        row = c.fetchone()
        if not row or (row[0] or 0) < plugs_cost:
            conn.rollback()
            return False
        c.execute(
            "UPDATE users SET balance = balance - ?, pl_gold = pl_gold + ? WHERE user_id = ?",
            (plugs_cost, gold_amount, fmt_id),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка transaction_buy_gold (покупка VIRTEX-GOLD): {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def transaction_sell_gold(user_id: int, gold_amount: int, plugs_reward: int) -> bool:
    fmt_id = f"@{user_id}"
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("BEGIN EXCLUSIVE")
        c.execute("SELECT COALESCE(pl_gold, 0) FROM users WHERE user_id = ?", (fmt_id,))
        row = c.fetchone()
        if not row or row[0] < gold_amount:
            conn.rollback()
            return False
        c.execute(
            """
            UPDATE users
            SET pl_gold  = COALESCE(pl_gold, 0)  - ?,
                balance  = COALESCE(balance, 0)  + ?
            WHERE user_id = ?
            """,
            (gold_amount, plugs_reward, fmt_id),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка transaction_sell_gold (продажа VIRTEX-GOLD): {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def log_promo_activation(user_id: int, promo_code: str):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO promo_logs (user_id, promo_code) VALUES (?, ?)", (user_id, promo_code))
        conn.commit()
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка при логировании промо: {e}")
    finally:
        conn.close()


def set_setting(key: str, value: str):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default_value=None):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = c.fetchone()
        return result[0] if result else default_value
    except sqlite3.OperationalError:
        return default_value
    finally:
        conn.close()


def set_global_emoji(emoji_text: str):
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('global_history_emoji', ?)",
            (emoji_text,),
        )
        conn.commit()
    finally:
        conn.close()


def get_global_emoji() -> str:
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = 'global_history_emoji'")
        row = cur.fetchone()
        conn.close()
        return row[0] if row else "🌕"
    except sqlite3.OperationalError:
        return "🌕"


def set_page_emoji(emoji_text: str):
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('page_history_emoji', ?)",
            (emoji_text,),
        )
        conn.commit()
    finally:
        conn.close()


def get_page_emoji() -> str:
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = 'page_history_emoji'")
        row = cur.fetchone()
        conn.close()
        return row[0] if row else "🧱"
    except sqlite3.OperationalError:
        return "🧱"




# --- ЗАМЕНИ ЭТИМ КОДОМ ВСЁ, ЧТО У ТЕБЯ ПОСЛЕ СТРОКИ 817 ---

def get_stars_balance(user_id: int) -> int:
    """Получает баланс звезд из основной базы данных."""
    fmt_user_id = f"@{user_id}"
    conn = _connect() # Используем уже готовую функцию из начала файла
    c = conn.cursor()
    try:
        # Ищем по колонке user_id, так как там лежат ID с собачкой
        c.execute("SELECT stars FROM users WHERE user_id = ?", (fmt_user_id,))
        result = c.fetchone()
        return result[0] if result and result[0] is not None else 0
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()

def update_stars_balance(user_id: int, amount: int):
    """Списывает или начисляет звезды в основной базе."""
    fmt_user_id = f"@{user_id}"
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute(
            "UPDATE users SET stars = stars + ? WHERE user_id = ?",
            (amount, fmt_user_id)
        )
        conn.commit()
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка в update_stars_balance: {e}")
    finally:
        conn.close()

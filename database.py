import sqlite3
import datetime
import logging
import aiosqlite
import os

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "bot_db.sqlite")
DB_NAME = DB_PATH


def _apply_pragma(conn: sqlite3.Connection):
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")


def _migrate(c: sqlite3.Cursor):
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
        ("users", "is_bot INTEGER DEFAULT 0"),
        ("group_settings", "basket_status INTEGER DEFAULT 1"),
        ("group_settings", "crash_status INTEGER DEFAULT 1"),
        ("group_settings", "mines_status INTEGER DEFAULT 1"),
        ("group_rules", "rules_entities TEXT"),
    ]
    for table, column_def in migrations:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        except sqlite3.OperationalError:
            pass


def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    _apply_pragma(conn)
    c = conn.cursor()

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
            rep_minus       INTEGER DEFAULT 0,
            stars           INTEGER DEFAULT 0,
            custom_nickname TEXT,
            vip_until       TEXT
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
            inviter_id INTEGER,
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

        CREATE TABLE IF NOT EXISTS tournament_history (
            place     INTEGER,
            user_id   INTEGER,
            user_name TEXT,
            profit    INTEGER
        );

        CREATE TABLE IF NOT EXISTS bank_deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            term_days INTEGER,
            rate REAL,
            created_at INTEGER,
            status TEXT DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS checks (
            code TEXT PRIMARY KEY,
            creator_id INTEGER,
            amount REAL,
            remaining INTEGER,
            created_at INTEGER,
            claimed TEXT DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS referrals (
            invitee_id INTEGER PRIMARY KEY,
            inviter_id INTEGER NOT NULL,
            date_time  TEXT NOT NULL
        );
    """)

    c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_roulette_bets_chat ON roulette_bets(chat_id);
        CREATE INDEX IF NOT EXISTS idx_roulette_bets_user_chat ON roulette_bets(user_id, chat_id);
        CREATE INDEX IF NOT EXISTS idx_roulette_history_chat ON roulette_history(chat_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
    """)

    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('page_history_emoji', '📄')")
    c.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('crash_prefix', '🚀')")
    c.execute("INSERT OR IGNORE INTO exchange_rate (id, rate) VALUES (1, 2450)")

    _migrate(c)

    conn.commit()
    conn.close()
    logger.info(f"База данных инициализирована: {DB_PATH}")


def _connect(timeout: int = 30) -> sqlite3.Connection:
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


def make_transfer(from_user_id: int, from_name: str, to_user_id: int, to_name: str, amount: int, currency: str = "balance") -> bool:
    if currency not in ("balance", "gold"):
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
        logger.error(f"Ошибка в make_transfer: {e}")
        return False
    finally:
        conn.close()


def get_history(user_id: int):
    conn = _connect()
    c = conn.cursor()
    u_id = f"@{user_id}"
    try:
        c.execute(
            "SELECT amount, from_name, to_name, timestamp, from_id, to_id, type FROM transfers WHERE to_id = ? OR from_id = ? ORDER BY id DESC LIMIT 20",
            (u_id, u_id),
        )
        return c.fetchall()
    except Exception:
        return []
    finally:
        conn.close()


def update_balance(user_id: str, amount: int):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка при обновлении баланса: {e}")
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
    """Проверяет, забанен ли пользователь"""
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("SELECT is_banned FROM users WHERE user_id = ?", (f"@{user_id}",))
        res = c.fetchone()
        return bool(res[0]) if res else False
    except Exception:
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
    except Exception:
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
    except Exception as e:
        logger.error(f"Ошибка при выдаче бонуса: {e}")
    finally:
        conn.close()


def get_vip_status(user_id: int) -> bool:
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("SELECT vip_until FROM users WHERE user_id = ?", (f"@{user_id}",))
        res = c.fetchone()
        if res and res[0]:
            from datetime import datetime
            return datetime.fromisoformat(res[0]) > datetime.now()
        return False
    finally:
        conn.close()


def give_vip_month(user_id: int):
    from datetime import datetime, timedelta
    conn = _connect()
    c = conn.cursor()
    new_until = (datetime.now() + timedelta(days=30)).isoformat()
    try:
        c.execute("UPDATE users SET vip_until = ? WHERE user_id = ?", (new_until, f"@{user_id}"))
        conn.commit()
    finally:
        conn.close()


def remove_vip(user_id: int):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET vip_until = NULL WHERE user_id = ?", (f"@{user_id}",))
        conn.commit()
    finally:
        conn.close()


def get_user_info(target_id: str):
    clean_id = target_id.replace("@", "")
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("SELECT name, balance, pl_gold, vip_until FROM users WHERE user_id = ?", (f"@{clean_id}",))
        return c.fetchone()
    except Exception:
        return None
    finally:
        conn.close()


def get_user_by_username(username: str):
    conn = _connect()
    c = conn.cursor()
    clean_username = username if username.startswith("@") else f"@{username}"
    try:
        c.execute("SELECT user_id, name FROM users WHERE username = ?", (clean_username,))
        return c.fetchone()
    except Exception:
        return None
    finally:
        conn.close()


def update_user_info(user_id, name, username):
    fmt_user_id = f"@{user_id}" if not str(user_id).startswith("@") else user_id
    fmt_username = f"@{username}" if username else "Нет"
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET name = ?, username = ? WHERE user_id = ?", (name, fmt_username, fmt_user_id))
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка базы данных: {e}")
    finally:
        conn.close()


def get_full_user(user_id: int):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("SELECT name, custom_nickname, registered_at, rep_plus, rep_minus FROM users WHERE user_id = ?", (f"@{user_id}",))
        return c.fetchone()
    finally:
        conn.close()


def get_setting(key: str, default_value=None):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = c.fetchone()
        return result[0] if result else default_value
    except Exception:
        return default_value
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


def get_global_emoji() -> str:
    try:
        conn = _connect()
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = 'global_history_emoji'")
        row = c.fetchone()
        conn.close()
        return row[0] if row else "🌕"
    except Exception:
        return "🌕"


def set_global_emoji(emoji_text: str):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('global_history_emoji', ?)", (emoji_text,))
        conn.commit()
    finally:
        conn.close()


def get_page_emoji() -> str:
    try:
        conn = _connect()
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = 'page_history_emoji'")
        row = c.fetchone()
        conn.close()
        return row[0] if row else "🧱"
    except Exception:
        return "🧱"


def set_page_emoji(emoji_text: str):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('page_history_emoji', ?)", (emoji_text,))
        conn.commit()
    finally:
        conn.close()


def log_donate(user_id: int, payment_id: str, amount: int, stars: int, currency: str = "balance") -> bool:
    db_column = "balance" if currency == "balance" else "pl_gold"
    f_id = f"@{user_id}"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO transfers (from_id, from_name, to_id, to_name, amount, type, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("SYSTEM", "SYSTEM", f_id, f"Stars: {stars}", amount, "donate", now),
        )
        c.execute("INSERT OR IGNORE INTO users (user_id, name) VALUES (?, ?)", (f_id, "Пользователь"))
        c.execute(f"UPDATE users SET {db_column} = {db_column} + ? WHERE user_id = ?", (amount, f_id))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()

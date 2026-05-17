import sqlite3
import datetime
import logging
import aiosqlite
import os

logger = logging.getLogger(__name__)

# Путь к базе данных - можно переопределить через переменную окружения
DB_PATH = os.getenv("DB_PATH", "bot_db.sqlite")
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
        ("users", "is_bot INTEGER DEFAULT 0"),
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
            pass


def init_db():
    """Инициализирует базу данных - создаёт таблицы если их нет"""
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

        CREATE TABLE IF NOT EXISTS tournament_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            tournament  TEXT,
            result      TEXT,
            date_time   TEXT
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

    # Индексы для ускорения частых запросов
    c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_roulette_bets_chat ON roulette_bets(chat_id);
        CREATE INDEX IF NOT EXISTS idx_roulette_bets_user_chat ON roulette_bets(user_id, chat_id);
        CREATE INDEX IF NOT EXISTS idx_roulette_history_chat ON roulette_history(chat_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
    """)

    # Дефолтные значения настроек
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('page_history_emoji', '📄')")
    c.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('crash_prefix', '🚀')")
    c.execute("INSERT OR IGNORE INTO exchange_rate (id, rate) VALUES (1, 2450)")

    # Миграции существующих баз
    _migrate(c)

    conn.commit()
    conn.close()
    logger.info(f"База данных инициализирована: {DB_PATH}")


# Остальной код database.py остаётся без изменений...
# (все функции get_balance, update_balance, add_user и т.д.)

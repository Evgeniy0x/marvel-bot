"""
database.py — SQLite хранилище: напоминания, привычки, заметки, настройки
"""
import sqlite3
from datetime import datetime
from typing import Optional, List
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создаёт все таблицы при первом запуске, безопасно мигрирует существующие."""
    with get_conn() as conn:
        conn.executescript("""
        -- ── Напоминания ───────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS reminders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            text            TEXT    NOT NULL,
            remind_at       TEXT    NOT NULL,
            recurrence      TEXT    DEFAULT NULL,
            category        TEXT    DEFAULT 'general',
            priority        TEXT    DEFAULT 'normal',
            done            INTEGER DEFAULT 0,
            snoozed_to      TEXT    DEFAULT NULL,
            missed_notified INTEGER DEFAULT 0,
            project         TEXT    DEFAULT NULL,
            created_at      TEXT    DEFAULT (datetime('now')),
            job_id          TEXT    DEFAULT NULL
        );

        -- ── Привычки ──────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS habits (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            title           TEXT    NOT NULL,
            frequency       TEXT    DEFAULT 'daily',
            emoji           TEXT    DEFAULT '✅',
            current_streak  INTEGER DEFAULT 0,
            best_streak     INTEGER DEFAULT 0,
            total_done      INTEGER DEFAULT 0,
            last_done       TEXT    DEFAULT NULL,
            created_at      TEXT    DEFAULT (datetime('now'))
        );

        -- ── Логи выполнения привычек ───────────────────────────────
        CREATE TABLE IF NOT EXISTS habit_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id    INTEGER NOT NULL,
            done_at     TEXT    DEFAULT (datetime('now'))
        );

        -- ── Заметки и идеи ─────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS notes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            text        TEXT    NOT NULL,
            tags        TEXT    DEFAULT NULL,
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        -- ── Настройки пользователя ─────────────────────────────────
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id     INTEGER PRIMARY KEY,
            timezone    TEXT    DEFAULT 'Europe/Moscow',
            morning_on  INTEGER DEFAULT 1,
            morning_h   INTEGER DEFAULT 8,
            morning_m   INTEGER DEFAULT 0,
            ai_style    TEXT    DEFAULT 'friendly',
            voice_on    INTEGER DEFAULT 0    -- 1 = отвечать голосом
        );
        """)

    # Безопасная миграция — добавляем новые колонки если их нет
    _safe_migrate()


def _safe_migrate():
    """Добавляет новые колонки в существующие таблицы без ошибок."""
    migrations = [
        ("reminders",     "missed_notified", "INTEGER DEFAULT 0"),
        ("reminders",     "project",         "TEXT DEFAULT NULL"),
        ("user_settings", "voice_on",        "INTEGER DEFAULT 0"),
    ]
    with get_conn() as conn:
        for table, col, col_def in migrations:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
            except sqlite3.OperationalError:
                pass  # колонка уже существует


# ── НАПОМИНАНИЯ ───────────────────────────────────────────────────────────────

def add_reminder(user_id: int, text: str, remind_at: datetime,
                 recurrence: str = None, category: str = "general",
                 priority: str = "normal", job_id: str = None,
                 project: str = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO reminders
               (user_id, text, remind_at, recurrence, category, priority, job_id, project)
               VALUES (?,?,?,?,?,?,?,?)""",
            (user_id, text, remind_at.isoformat(), recurrence,
             category, priority, job_id, project)
        )
        return cur.lastrowid


def get_reminder(reminder_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM reminders WHERE id=?", (reminder_id,)
        ).fetchone()


def get_active_reminders(user_id: int) -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM reminders WHERE user_id=? AND done=0 ORDER BY remind_at ASC",
            (user_id,)
        ).fetchall()


def get_todays_reminders(user_id: int, date_str: str) -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM reminders
               WHERE user_id=? AND done=0 AND date(remind_at)=?
               ORDER BY remind_at ASC""",
            (user_id, date_str)
        ).fetchall()


def get_missed_reminders(user_id: int, before_iso: str) -> List[sqlite3.Row]:
    """Напоминания, которые уже сработали, не выполнены и не уведомлялись о пропуске."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM reminders
               WHERE user_id=? AND done=0 AND missed_notified=0
               AND recurrence IS NULL AND remind_at < ?
               ORDER BY remind_at ASC""",
            (user_id, before_iso)
        ).fetchall()


def mark_done(reminder_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE reminders SET done=1 WHERE id=?", (reminder_id,))


def mark_missed_notified(reminder_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE reminders SET missed_notified=1 WHERE id=?", (reminder_id,))


def snooze_reminder(reminder_id: int, new_time: datetime):
    with get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET snoozed_to=?, remind_at=?, missed_notified=0 WHERE id=?",
            (new_time.isoformat(), new_time.isoformat(), reminder_id)
        )


def delete_reminder(reminder_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))


def update_job_id(reminder_id: int, job_id: str):
    with get_conn() as conn:
        conn.execute("UPDATE reminders SET job_id=? WHERE id=?", (job_id, reminder_id))


def get_all_active_for_restart() -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM reminders WHERE done=0 ORDER BY remind_at ASC"
        ).fetchall()


def get_week_stats(user_id: int, week_start_iso: str) -> dict:
    """Статистика за неделю."""
    with get_conn() as conn:
        done = conn.execute(
            "SELECT COUNT(*) FROM reminders WHERE user_id=? AND done=1 AND created_at>=?",
            (user_id, week_start_iso)
        ).fetchone()[0]
        missed = conn.execute(
            """SELECT COUNT(*) FROM reminders
               WHERE user_id=? AND done=0 AND missed_notified=1
               AND recurrence IS NULL AND created_at>=?""",
            (user_id, week_start_iso)
        ).fetchone()[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM reminders WHERE user_id=? AND created_at>=?",
            (user_id, week_start_iso)
        ).fetchone()[0]
        return {"done": done, "missed": missed, "total": total}


# ── ПРИВЫЧКИ ─────────────────────────────────────────────────────────────────

def add_habit(user_id: int, title: str, frequency: str = "daily",
              emoji: str = "✅") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO habits (user_id, title, frequency, emoji) VALUES (?,?,?,?)",
            (user_id, title, frequency, emoji)
        )
        return cur.lastrowid


def get_habits(user_id: int) -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM habits WHERE user_id=? ORDER BY created_at ASC",
            (user_id,)
        ).fetchall()


def get_habit(habit_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM habits WHERE id=?", (habit_id,)).fetchone()


def mark_habit_done(habit_id: int, today_str: str):
    """Отмечает привычку выполненной сегодня, обновляет стрик."""
    with get_conn() as conn:
        habit = conn.execute("SELECT * FROM habits WHERE id=?", (habit_id,)).fetchone()
        if not habit:
            return

        # Логируем выполнение
        conn.execute("INSERT INTO habit_logs (habit_id) VALUES (?)", (habit_id,))

        # Обновляем стрик
        last = habit["last_done"]
        streak = habit["current_streak"]

        from datetime import date, timedelta
        today = date.fromisoformat(today_str)
        if last:
            last_date = date.fromisoformat(last[:10])
            if last_date == today:
                return  # уже выполнено сегодня
            elif last_date == today - timedelta(days=1):
                streak += 1
            else:
                streak = 1
        else:
            streak = 1

        best = max(streak, habit["best_streak"])
        conn.execute(
            """UPDATE habits SET current_streak=?, best_streak=?,
               total_done=total_done+1, last_done=? WHERE id=?""",
            (streak, best, today_str, habit_id)
        )


def delete_habit(habit_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM habit_logs WHERE habit_id=?", (habit_id,))
        conn.execute("DELETE FROM habits WHERE id=?", (habit_id,))


# ── ЗАМЕТКИ ───────────────────────────────────────────────────────────────────

def add_note(user_id: int, text: str, tags: str = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO notes (user_id, text, tags) VALUES (?,?,?)",
            (user_id, text, tags)
        )
        return cur.lastrowid


def get_notes(user_id: int, limit: int = 10) -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM notes WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()


def delete_note(note_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM notes WHERE id=?", (note_id,))


# ── НАСТРОЙКИ ─────────────────────────────────────────────────────────────────

def get_settings(user_id: int) -> sqlite3.Row:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_settings WHERE user_id=?", (user_id,)
        ).fetchone()
        if not row:
            conn.execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))
            row = conn.execute(
                "SELECT * FROM user_settings WHERE user_id=?", (user_id,)
            ).fetchone()
        return row


def update_setting(user_id: int, key: str, value):
    with get_conn() as conn:
        conn.execute(
            f"UPDATE user_settings SET {key}=? WHERE user_id=?",
            (value, user_id)
        )

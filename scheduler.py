"""
scheduler.py — APScheduler: напоминания, дайджест, пропущенные задачи, недельный обзор.
"""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

import database as db
from config import TIMEZONE

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=TIMEZONE)
_app = None   # Telegram Application (устанавливается через set_bot)


def set_bot(app):
    global _app
    _app = app


# ── Основные напоминания ──────────────────────────────────────────────────────

def schedule_reminder(reminder_id: int, user_id: int,
                      remind_at: datetime, recurrence: str = None) -> str:
    """Планирует одно напоминание. Возвращает job_id."""
    job_id = f"rem_{reminder_id}"

    if recurrence == "daily":
        trigger = CronTrigger(
            hour=remind_at.hour, minute=remind_at.minute, timezone=TIMEZONE
        )
    elif recurrence == "weekly":
        trigger = CronTrigger(
            day_of_week=remind_at.weekday(),
            hour=remind_at.hour, minute=remind_at.minute, timezone=TIMEZONE
        )
    elif recurrence == "weekdays":
        trigger = CronTrigger(
            day_of_week="mon-fri",
            hour=remind_at.hour, minute=remind_at.minute, timezone=TIMEZONE
        )
    elif recurrence == "monthly":
        trigger = CronTrigger(
            day=remind_at.day,
            hour=remind_at.hour, minute=remind_at.minute, timezone=TIMEZONE
        )
    else:
        trigger = DateTrigger(run_date=remind_at)

    scheduler.add_job(
        _fire_reminder,
        trigger=trigger,
        args=[reminder_id, user_id],
        id=job_id,
        replace_existing=True,
        misfire_grace_time=300,
    )
    return job_id


async def _fire_reminder(reminder_id: int, user_id: int):
    """Отправляет напоминание пользователю с inline-кнопками."""
    if not _app:
        return
    reminder = db.get_reminder(reminder_id)
    if not reminder or reminder["done"]:
        return

    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    from analytics import PRIORITY_ICONS, CATEGORY_ICONS

    p_icon = PRIORITY_ICONS.get(reminder["priority"], "🔵")
    c_icon = CATEGORY_ICONS.get(reminder["category"], "📌")

    text = f"⏰ *Напоминание!*\n\n{p_icon}{c_icon} {reminder['text']}"
    if reminder["project"]:
        text += f"\n📁 Проект: {reminder['project']}"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Готово",  callback_data=f"done:{reminder_id}"),
            InlineKeyboardButton("⏰ +1ч",    callback_data=f"snooze:{reminder_id}:60"),
            InlineKeyboardButton("⏰ +3ч",    callback_data=f"snooze:{reminder_id}:180"),
        ],
        [InlineKeyboardButton("🗑 Удалить",   callback_data=f"del:{reminder_id}")]
    ])

    try:
        await _app.bot.send_message(
            chat_id=user_id, text=text,
            parse_mode="Markdown", reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"_fire_reminder error: {e}")


# ── Утренний дайджест ─────────────────────────────────────────────────────────

def schedule_morning_digest(user_id: int, hour: int = 8, minute: int = 0):
    """Планирует ежедневный умный утренний брифинг."""
    job_id = f"morning_{user_id}"
    scheduler.add_job(
        _morning_digest,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=TIMEZONE),
        args=[user_id],
        id=job_id,
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info(f"Утренний дайджест: user={user_id} {hour:02d}:{minute:02d}")


async def _morning_digest(user_id: int):
    """Отправляет умный утренний брифинг с AI-анализом задач."""
    if not _app:
        return

    from ai_parser import smart_morning_briefing
    from analytics import build_today_summary
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    tasks_text = build_today_summary(user_id, TIMEZONE)
    briefing = await smart_morning_briefing(tasks_text, TIMEZONE)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📋 Полный список", callback_data="show_today"),
        InlineKeyboardButton("✅ Вперёд!",       callback_data="dismiss"),
    ]])

    try:
        await _app.bot.send_message(
            chat_id=user_id,
            text=f"☀️ *Доброе утро!*\n\n{briefing}",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"_morning_digest error: {e}")


# ── Проверка пропущенных задач ────────────────────────────────────────────────

def schedule_missed_checker():
    """Запускает проверку пропущенных задач каждые 30 минут."""
    scheduler.add_job(
        _check_missed,
        trigger=CronTrigger(minute="*/30"),
        id="missed_checker",
        replace_existing=True,
    )
    logger.info("Проверка пропущенных задач: каждые 30 минут")


async def _check_missed():
    """Находит просроченные невыполненные задачи и спрашивает пользователя."""
    if not _app:
        return

    from config import ALLOWED_USERS
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    tz = ZoneInfo(TIMEZONE)
    threshold = (datetime.now(tz) - timedelta(minutes=30)).isoformat()

    for user_id in ALLOWED_USERS:
        missed = db.get_missed_reminders(user_id, threshold)
        for r in missed:
            db.mark_missed_notified(r["id"])
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Да, выполнил",  callback_data=f"done:{r['id']}"),
                    InlineKeyboardButton("⏰ +2 часа",       callback_data=f"snooze:{r['id']}:120"),
                ],
                [InlineKeyboardButton("🗑 Удалить",          callback_data=f"del:{r['id']}")]
            ])
            try:
                await _app.bot.send_message(
                    chat_id=user_id,
                    text=f"🤔 Ты выполнил задачу?\n\n*{r['text']}*",
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f"_check_missed error: {e}")


# ── Еженедельный AI-обзор ─────────────────────────────────────────────────────

def schedule_weekly_review(user_id: int):
    """Каждое воскресенье в 20:00 — AI-разбор прошедшей недели."""
    job_id = f"weekly_{user_id}"
    scheduler.add_job(
        _weekly_review,
        trigger=CronTrigger(day_of_week="sun", hour=20, minute=0, timezone=TIMEZONE),
        args=[user_id],
        id=job_id,
        replace_existing=True,
    )
    logger.info(f"Еженедельный обзор: user={user_id} воскр. 20:00")


async def _weekly_review(user_id: int):
    """Отправляет AI-анализ прошедшей недели."""
    if not _app:
        return

    from ai_parser import weekly_ai_review
    from analytics import build_week_report, get_week_bounds

    week_start, _ = get_week_bounds(TIMEZONE)
    stats = db.get_week_stats(user_id, week_start)
    habits = db.get_habits(user_id)
    habits_summary = ", ".join(
        f"{h['emoji']}{h['title']} (стрик {h['current_streak']})"
        for h in habits
    ) if habits else "нет привычек"

    report   = build_week_report(user_id, TIMEZONE)
    ai_comment = await weekly_ai_review(
        stats["done"], stats["missed"], stats["total"], habits_summary
    )

    try:
        await _app.bot.send_message(
            chat_id=user_id,
            text=f"{report}\n\n🤖 *Марвел говорит:*\n{ai_comment}",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"_weekly_review error: {e}")


# ── Восстановление при рестарте ───────────────────────────────────────────────

def restore_jobs():
    """Восстанавливает все активные напоминания из БД после перезапуска."""
    reminders = db.get_all_active_for_restart()
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    restored = 0

    for r in reminders:
        remind_dt = datetime.fromisoformat(r["remind_at"])
        if remind_dt.tzinfo is None:
            remind_dt = remind_dt.replace(tzinfo=tz)

        if remind_dt < now and not r["recurrence"]:
            continue  # разовые просроченные пропускаем

        job_id = schedule_reminder(r["id"], r["user_id"], remind_dt, r["recurrence"])
        db.update_job_id(r["id"], job_id)
        restored += 1

    logger.info(f"Восстановлено заданий: {restored}/{len(reminders)}")

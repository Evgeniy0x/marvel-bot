"""
analytics.py — Статистика, еженедельный отчёт, AI-анализ продуктивности.
"""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import database as db
from config import TIMEZONE

logger = logging.getLogger(__name__)


def get_week_bounds(tz_str: str = TIMEZONE) -> tuple[str, str]:
    """Возвращает ISO-строки начала и конца текущей недели (пн–вс)."""
    tz = ZoneInfo(tz_str)
    now = datetime.now(tz)
    monday = now - timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    sunday = monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return monday.isoformat(), sunday.isoformat()


def build_week_report(user_id: int, tz_str: str = TIMEZONE) -> str:
    """
    Формирует текстовый отчёт за неделю:
    - выполненные задачи
    - пропущенные задачи
    - процент выполнения
    - привычки и стрики
    """
    tz = ZoneInfo(tz_str)
    now = datetime.now(tz)
    week_start, _ = get_week_bounds(tz_str)

    stats = db.get_week_stats(user_id, week_start)
    habits = db.get_habits(user_id)

    done    = stats["done"]
    missed  = stats["missed"]
    total   = stats["total"]
    rate    = round(done / total * 100) if total > 0 else 0

    # Эмодзи оценки
    if rate >= 80:
        grade = "🏆 Отличная неделя!"
    elif rate >= 60:
        grade = "👍 Хорошая неделя"
    elif rate >= 40:
        grade = "📈 Есть куда расти"
    else:
        grade = "💪 Не сдавайся, следующая лучше"

    lines = [
        f"📊 *Итоги недели* ({now.strftime('%d.%m')})",
        "",
        f"{grade}",
        "",
        f"✅ Выполнено: *{done}* задач",
        f"❌ Пропущено: *{missed}* задач",
        f"📌 Всего создано: *{total}*",
        f"📈 Процент выполнения: *{rate}%*",
    ]

    if habits:
        lines.append("")
        lines.append("🔥 *Привычки:*")
        for h in habits:
            streak = h["current_streak"]
            best   = h["best_streak"]
            done_h = h["total_done"]
            fire   = "🔥" * min(streak, 5) if streak > 0 else "💤"
            lines.append(
                f"{h['emoji']} {h['title']}: стрик {streak} дн. {fire} "
                f"(рекорд {best}, всего {done_h})"
            )

    return "\n".join(lines)


def build_today_summary(user_id: int, tz_str: str = TIMEZONE) -> str:
    """
    Краткая сводка активных задач для inline-использования.
    """
    tz = ZoneInfo(tz_str)
    today = datetime.now(tz).strftime("%Y-%m-%d")
    reminders = db.get_todays_reminders(user_id, today)

    if not reminders:
        return "На сегодня задач нет 🎉"

    lines = []
    for r in reminders:
        t = datetime.fromisoformat(r["remind_at"])
        t_local = t.astimezone(tz)
        lines.append(f"• {t_local.strftime('%H:%M')} — {r['text']}")

    return "\n".join(lines)


PRIORITY_ICONS = {"urgent": "🔴", "high": "🟠", "normal": "🔵", "low": "⚪"}
CATEGORY_ICONS = {
    "work": "💼", "personal": "👤", "health": "❤️",
    "finance": "💰", "general": "📌"
}


def format_reminder(r, tz_str: str = TIMEZONE) -> str:
    """Форматирует одно напоминание для отображения."""
    tz = ZoneInfo(tz_str)
    t = datetime.fromisoformat(r["remind_at"]).astimezone(tz)
    p_icon = PRIORITY_ICONS.get(r["priority"], "🔵")
    c_icon = CATEGORY_ICONS.get(r["category"], "📌")
    rec = " 🔄" if r["recurrence"] else ""
    proj = f" [{r['project']}]" if r["project"] else ""
    return f"{p_icon}{c_icon} *{r['text']}*{proj}{rec}\n    ⏰ {t.strftime('%d.%m %H:%M')}"

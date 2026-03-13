"""
main.py — Точка входа Марвел Бота.
"""
import asyncio
import logging
import sys

import database as db
import scheduler as sched
from bot import build_app
from config import ALLOWED_USERS, MORNING_HOUR, MORNING_MINUTE
from telegram import BotCommand

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


async def on_startup(app):
    logger.info("🚀 Марвел запускается...")

    db.init_db()
    logger.info("✅ База данных готова")

    sched.set_bot(app)
    sched.restore_jobs()

    # Устанавливаем команды в меню Telegram (удаляем старые, ставим новые)
    await app.bot.set_my_commands([
        BotCommand("start",    "👋 Начать / Помощь"),
        BotCommand("today",    "📅 Задачи на сегодня"),
        BotCommand("list",     "📋 Все напоминания"),
        BotCommand("habits",   "🎯 Трекер привычек"),
        BotCommand("notes",    "📝 Мои заметки"),
        BotCommand("stats",    "📊 Статистика недели"),
        BotCommand("digest",   "☀️ Утренний брифинг"),
        BotCommand("voice",    "🔊 Вкл/выкл голосовые ответы"),
        BotCommand("settings", "⚙️ Настройки"),
        BotCommand("help",     "❓ Справка"),
    ])
    logger.info("📋 Команды бота обновлены")

    for user_id in ALLOWED_USERS:
        settings = db.get_settings(user_id)
        if settings["morning_on"]:
            h, m = settings["morning_h"], settings["morning_m"]
            sched.schedule_morning_digest(user_id, hour=h, minute=m)
            logger.info(f"☀️ Утренний дайджест для user={user_id} в {h:02d}:{m:02d}")
        sched.schedule_weekly_review(user_id)

    sched.schedule_missed_checker()
    sched.scheduler.start()
    logger.info("⏰ Планировщик запущен")
    logger.info("✨ Марвел готов к работе!")


async def on_shutdown(app):
    logger.info("🛑 Марвел останавливается...")
    if sched.scheduler.running:
        sched.scheduler.shutdown(wait=False)


def main():
    logger.info("=" * 50)
    logger.info("  МАРВЕЛ — Персональный AI Ассистент")
    logger.info("=" * 50)

    app = build_app()
    app.post_init     = on_startup
    app.post_shutdown = on_shutdown

    logger.info("📡 Запускаю Telegram polling...")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    main()

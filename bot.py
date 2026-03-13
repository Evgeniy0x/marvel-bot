"""
bot.py — Все хендлеры Telegram бота Марвел.

Команды:
  /start          — приветствие
  /help           — справка
  /list           — все активные напоминания
  /today          — задачи на сегодня
  /habits         — трекер привычек
  /notes          — заметки и идеи
  /stats          — статистика за неделю
  /digest         — утренний брифинг сейчас
  /voice          — вкл/выкл голосовые ответы
  /settings       — настройки

Любое текстовое сообщение → AI определяет intent:
  напоминание | привычка | заметка | поиск | вопрос | список...

Голосовые сообщения → Whisper → _process_intent() → ответ голосом (если voice_on).

Inline-кнопки: done / snooze / delete / habit_done / show_today / dismiss
"""
import logging
import os
import traceback
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ChatAction

import database as db
import scheduler as sched
from ai_parser import (
    detect_intent, parse_reminder, parse_habit,
    chat_with_ai, smart_morning_briefing
)
from analytics import (
    build_week_report, build_today_summary,
    format_reminder, PRIORITY_ICONS, CATEGORY_ICONS
)
from config import (
    TELEGRAM_TOKEN, ALLOWED_USERS, TIMEZONE,
    MORNING_HOUR, MORNING_MINUTE,
    WHISPER_ENABLED, TTS_ENABLED, SEARCH_ENABLED, THINGS_ENABLED
)

logger = logging.getLogger(__name__)

_chat_history: dict[int, list] = {}


# ── Декоратор доступа ─────────────────────────────────────────────────────────

def restricted(func):
    @wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if ALLOWED_USERS and user_id not in ALLOWED_USERS:
            await update.effective_message.reply_text("⛔ Нет доступа.")
            return
        return await func(update, ctx)
    return wrapper


def get_tz(user_id: int) -> str:
    return db.get_settings(user_id)["timezone"] or TIMEZONE


def is_voice_on(user_id: int) -> bool:
    """Проверяет включён ли голосовой режим для пользователя."""
    settings = db.get_settings(user_id)
    return bool(settings["voice_on"]) and TTS_ENABLED


async def reply(update: Update, user_id: int, text: str, **kwargs):
    """
    Умный ответ: отправляет текст, и дублирует голосом если voice_on=True.
    Работает как для текстовых update, так и для голосовых (effective_message).
    """
    msg = update.effective_message
    await msg.reply_text(text, **kwargs)

    if is_voice_on(user_id):
        from tts import synthesize
        audio_path = await synthesize(text)
        if audio_path:
            try:
                with open(audio_path, "rb") as f:
                    await msg.reply_voice(voice=f)
            except Exception as e:
                logger.error(f"Voice reply error: {e}")
            finally:
                if os.path.exists(audio_path):
                    os.unlink(audio_path)


# ── Глобальный обработчик ошибок ──────────────────────────────────────────────

async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    """Логирует все необработанные ошибки с полным traceback."""
    logger.error("Необработанная ошибка:", exc_info=ctx.error)
    tb_str = "".join(traceback.format_exception(
        type(ctx.error), ctx.error, ctx.error.__traceback__
    ))
    logger.error(f"Traceback:\n{tb_str}")

    # Уведомляем пользователя об ошибке
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ Произошла ошибка при обработке запроса. Попробуй снова."
            )
        except Exception:
            pass


# ── /start ────────────────────────────────────────────────────────────────────

@restricted
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Привет! Я *Марвел* — твой AI-ассистент.\n\n"
        "Просто напиши или надиктуй что нужно:\n\n"
        "🔔 «напомни завтра в 9 позвонить маме»\n"
        "🔄 «каждый понедельник в 8 стендап»\n"
        "🎯 «хочу каждый день делать зарядку»\n"
        "📝 «запомни идею — сделать дашборд»\n"
        "🔍 «какой курс доллара сейчас?»\n"
        "🎤 Голосовые сообщения — тоже работают!\n"
        "🔊 /voice — включить голосовые ответы\n\n"
        "Или /help для полного списка команд."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ── /help ─────────────────────────────────────────────────────────────────────

@restricted
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Справка Марвел*\n\n"
        "*Команды:*\n"
        "/today — задачи на сегодня\n"
        "/list — все напоминания\n"
        "/habits — трекер привычек\n"
        "/notes — мои заметки\n"
        "/stats — статистика недели\n"
        "/digest — утренний брифинг\n"
        "/voice — вкл/выкл голосовые ответы\n"
        "/settings — настройки\n\n"
        "*Что умею:*\n"
        "• Создавать напоминания на любое время\n"
        "• Повторяющиеся задачи (ежедневно, по будням...)\n"
        "• Трекать привычки со стриками 🔥\n"
        "• Сохранять заметки и идеи\n"
        "• 🔍 Искать информацию в интернете\n"
        "• 🎤 Понимать голосовые сообщения\n"
        "• 🔊 Отвечать голосом (включается через /voice)"
    )
    await update.effective_message.reply_text(text, parse_mode="Markdown")


# ── /voice — включить/выключить голосовые ответы ─────────────────────────────

@restricted
async def cmd_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id  = update.effective_user.id
    settings = db.get_settings(user_id)
    current  = bool(settings["voice_on"])

    if not TTS_ENABLED:
        await update.effective_message.reply_text(
            "🔇 Голосовые ответы недоступны.\n"
            "Проверь, что в .env задан `OPENAI_WHISPER_KEY`."
        )
        return

    new_val = 0 if current else 1
    db.update_setting(user_id, "voice_on", new_val)

    if new_val:
        await update.effective_message.reply_text(
            "🔊 Голосовые ответы *включены*!\n"
            "Теперь я буду дублировать ответы голосом.\n\n"
            "Отключить: /voice",
            parse_mode="Markdown"
        )
    else:
        await update.effective_message.reply_text(
            "🔇 Голосовые ответы *выключены*.\n\n"
            "Включить снова: /voice",
            parse_mode="Markdown"
        )


# ── /list ─────────────────────────────────────────────────────────────────────

@restricted
async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    tz_str    = get_tz(user_id)
    reminders = db.get_active_reminders(user_id)

    if not reminders:
        await update.effective_message.reply_text(
            "📭 Активных напоминаний нет.\n\nНапиши что напомнить!"
        )
        return

    lines = [f"📋 *Активные напоминания* ({len(reminders)}):\n"]
    for i, r in enumerate(reminders, 1):
        lines.append(f"{i}. {format_reminder(r, tz_str)}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /today ────────────────────────────────────────────────────────────────────

@restricted
async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    tz_str    = get_tz(user_id)
    tz        = ZoneInfo(tz_str)
    today     = datetime.now(tz).strftime("%Y-%m-%d")
    reminders = db.get_todays_reminders(user_id, today)

    if not reminders:
        await update.effective_message.reply_text("🎉 На сегодня задач нет!")
        return

    lines = [f"📅 *Сегодня* ({datetime.now(tz).strftime('%d.%m')}):\n"]
    for r in reminders:
        lines.append(format_reminder(r, tz_str))
    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /habits ───────────────────────────────────────────────────────────────────

@restricted
async def cmd_habits(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    habits  = db.get_habits(user_id)
    tz      = ZoneInfo(get_tz(user_id))
    today   = datetime.now(tz).strftime("%Y-%m-%d")

    if not habits:
        await update.effective_message.reply_text(
            "🎯 Привычек пока нет.\n\n"
            "Напиши: «хочу каждый день делать зарядку»"
        )
        return

    lines = ["🎯 *Твои привычки:*\n"]
    keyboard_rows = []

    for h in habits:
        streak     = h["current_streak"]
        done_today = h["last_done"] and h["last_done"][:10] == today
        fire       = "🔥" * min(streak, 5) if streak > 0 else "💤"
        status     = "✅" if done_today else "⬜"

        lines.append(
            f"{status} {h['emoji']} *{h['title']}*\n"
            f"   Стрик: {streak} дн. {fire} | Рекорд: {h['best_streak']} | Всего: {h['total_done']}"
        )
        if not done_today:
            keyboard_rows.append([InlineKeyboardButton(
                f"✅ {h['emoji']} {h['title'][:25]}",
                callback_data=f"habit_done:{h['id']}"
            )])

    keyboard_rows.append([
        InlineKeyboardButton("➕ Добавить привычку", callback_data="add_habit")
    ])

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard_rows)
    )


# ── /notes ────────────────────────────────────────────────────────────────────

@restricted
async def cmd_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    notes   = db.get_notes(user_id, limit=10)

    if not notes:
        await update.effective_message.reply_text(
            "📝 Заметок пока нет.\n\nНапиши «запомни...» — сохраню!"
        )
        return

    lines = [f"📝 *Заметки* (последние {len(notes)}):\n"]
    for i, n in enumerate(notes, 1):
        lines.append(f"{i}. [{n['created_at'][:10]}] {n['text']}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /stats ────────────────────────────────────────────────────────────────────

@restricted
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    report  = build_week_report(user_id, get_tz(user_id))
    await update.effective_message.reply_text(report, parse_mode="Markdown")


# ── /digest ───────────────────────────────────────────────────────────────────

@restricted
async def cmd_digest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id    = update.effective_user.id
    tz_str     = get_tz(user_id)
    tasks_text = build_today_summary(user_id, tz_str)

    await update.effective_message.chat.send_action(ChatAction.TYPING)
    briefing = await smart_morning_briefing(tasks_text, tz_str)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📋 Полный список", callback_data="show_today"),
        InlineKeyboardButton("✅ Вперёд!",       callback_data="dismiss"),
    ]])
    text = f"☀️ *Брифинг на сегодня:*\n\n{briefing}"
    await update.effective_message.reply_text(
        text, parse_mode="Markdown", reply_markup=keyboard
    )

    if is_voice_on(user_id):
        from tts import synthesize
        audio_path = await synthesize(briefing)
        if audio_path:
            try:
                with open(audio_path, "rb") as f:
                    await update.effective_message.reply_voice(voice=f)
            except Exception as e:
                logger.error(f"digest voice error: {e}")
            finally:
                if os.path.exists(audio_path):
                    os.unlink(audio_path)


# ── /things ───────────────────────────────────────────────────────────────────

@restricted
async def cmd_things(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Справка по Things 3 интеграции."""
    user_id = update.effective_user.id

    if not THINGS_ENABLED:
        await update.effective_message.reply_text(
            "📋 *Things 3 — не настроено*\n\n"
            "Для интеграции добавь в `.env`:\n"
            "`APPLE_ID=your@icloud.com`\n"
            "`APPLE_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx`\n\n"
            "Как получить App Password:\n"
            "1. Открой appleid.apple.com\n"
            "2. Безопасность → Пароли для приложений\n"
            "3. Нажми + → назови «marvel-bot»\n"
            "4. Скопируй пароль вида `xxxx-xxxx-xxxx-xxxx`\n\n"
            "В Things 3 включи:\n"
            "_Settings → Quick Entry → Add from Reminders_",
            parse_mode="Markdown"
        )
        return

    await update.effective_message.reply_text(
        "📋 *Things 3 — активна!*\n\n"
        "Просто напиши или надиктуй:\n\n"
        "• «добавь в Things встреча с клиентом завтра в 15:00»\n"
        "• «создай задачу в Things купить MacBook»\n"
        "• «в Things 3: подготовить презентацию к пятнице»\n\n"
        "Я распознаю намерение автоматически — слова «Things» достаточно.\n\n"
        "Задача появится в *Inbox* Things 3 через несколько секунд.",
        parse_mode="Markdown"
    )


# ── /settings ─────────────────────────────────────────────────────────────────

@restricted
async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id  = update.effective_user.id
    s        = db.get_settings(user_id)
    voice_st = "🔊 вкл" if s["voice_on"] else "🔇 выкл"
    morning  = "включён" if s["morning_on"] else "выключен"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔊 Голос вкл", callback_data="voice_on"),
            InlineKeyboardButton("🔇 Голос выкл", callback_data="voice_off"),
        ],
        [
            InlineKeyboardButton("☀️ Дайджест вкл",  callback_data="morning_on"),
            InlineKeyboardButton("🌙 Дайджест выкл", callback_data="morning_off"),
        ],
        [
            InlineKeyboardButton("⏰ 7:00", callback_data="morning_700"),
            InlineKeyboardButton("⏰ 8:00", callback_data="morning_800"),
            InlineKeyboardButton("⏰ 9:00", callback_data="morning_900"),
        ],
        [InlineKeyboardButton("🌍 Сменить таймзону", callback_data="set_tz")],
    ])

    await update.effective_message.reply_text(
        f"⚙️ *Настройки*\n\n"
        f"🌍 Таймзона: `{s['timezone']}`\n"
        f"☀️ Утренний дайджест: {morning} в {s['morning_h']:02d}:{s['morning_m']:02d}\n"
        f"🔊 Голосовые ответы: {voice_st}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


# ── Голосовые сообщения ───────────────────────────────────────────────────────

@restricted
async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает голосовые сообщения:
    1. Скачивает OGG от Telegram
    2. Транскрибирует через Whisper
    3. Передаёт текст напрямую в _process_intent()

    ВАЖНО: НЕ используем update.message.text = text (PTB v22 объекты иммутабельны!)
    Вместо этого передаём транскрипцию явным параметром.
    """
    user_id = update.effective_user.id

    if not WHISPER_ENABLED:
        await update.effective_message.reply_text(
            "🎤 Голосовые сообщения не настроены.\n"
            "Добавь `OPENAI_WHISPER_KEY` в .env"
        )
        return

    await update.effective_message.chat.send_action(ChatAction.TYPING)
    status_msg = await update.effective_message.reply_text("🎤 Распознаю...")

    from voice import transcribe_voice
    text = await transcribe_voice(ctx.bot, update.message.voice.file_id)

    if not text:
        await status_msg.edit_text("❌ Не удалось распознать речь. Попробуй снова.")
        return

    await status_msg.edit_text(f"🎤 «{text}»")
    logger.info(f"Голосовое распознано: «{text[:60]}»")

    # ── FIX: вызываем _process_intent напрямую с текстом
    # Не устанавливаем update.message.text — это не работает в PTB v22
    tz_str = get_tz(user_id)
    await _process_intent(update, ctx, user_id, text, tz_str)


# ── Главный обработчик текста ─────────────────────────────────────────────────

@restricted
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает все текстовые сообщения."""
    user_id = update.effective_user.id
    text    = (update.message.text or "").strip()
    tz_str  = get_tz(user_id)

    if not text:
        return

    await update.message.chat.send_action(ChatAction.TYPING)
    await _process_intent(update, ctx, user_id, text, tz_str)


# ── Роутинг по намерению (общий для текста и голоса) ──────────────────────────

async def _process_intent(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
    user_id: int, text: str, tz_str: str
):
    """
    Определяет намерение по тексту и вызывает нужный обработчик.
    Вызывается и из handle_message(), и из handle_voice().
    """
    intent = await detect_intent(text)
    logger.info(f"user={user_id} intent={intent!r} text={text[:60]!r}")

    if intent == "reminder":
        await _create_reminder(update, user_id, text, tz_str)
    elif intent == "habit":
        await _create_habit(update, user_id, text)
    elif intent == "note":
        await _save_note(update, user_id, text)
    elif intent == "things":
        await _add_to_things(update, user_id, text, tz_str)
    elif intent == "crypto":
        await _crypto_query(update, user_id, text)
    elif intent == "search":
        await _web_search(update, user_id, text)
    elif intent == "list":
        await cmd_list(update, ctx)
    elif intent == "habits_list":
        await cmd_habits(update, ctx)
    elif intent == "notes_list":
        await cmd_notes(update, ctx)
    elif intent == "stats":
        await cmd_stats(update, ctx)
    elif intent == "help":
        await cmd_help(update, ctx)
    else:
        await _ai_chat(update, user_id, text, tz_str)


# ── Вспомогательные обработчики ───────────────────────────────────────────────

async def _create_reminder(update: Update, user_id: int, text: str, tz_str: str):
    result = await parse_reminder(text, tz_str)

    if "error" in result:
        err = result["error"]
        if err == "time_not_found":
            await update.effective_message.reply_text(
                "🤔 Не нашёл время в сообщении.\n"
                "Попробуй: «напомни *завтра в 10* позвонить»"
            )
        elif err == "time_in_past":
            await update.effective_message.reply_text(
                f"⏪ Время уже прошло ({result.get('parsed_time','')}).\n"
                "Укажи время в будущем!"
            )
        else:
            await update.effective_message.reply_text(
                "❌ Не удалось разобрать напоминание. Попробуй иначе."
            )
        return

    remind_dt  = result["remind_at_dt"]
    r_text     = result.get("text", text)
    recurrence = result.get("recurrence")
    category   = result.get("category", "general")
    priority   = result.get("priority", "normal")
    project    = result.get("project")

    rid    = db.add_reminder(user_id=user_id, text=r_text, remind_at=remind_dt,
                              recurrence=recurrence, category=category,
                              priority=priority, project=project)
    job_id = sched.schedule_reminder(rid, user_id, remind_dt, recurrence)
    db.update_job_id(rid, job_id)

    tz      = ZoneInfo(tz_str)
    t_local = remind_dt.astimezone(tz)
    p_icon  = PRIORITY_ICONS.get(priority, "🔵")
    c_icon  = CATEGORY_ICONS.get(category, "📌")
    rec_str = {
        "daily":    "🔄 ежедневно",
        "weekly":   "🔄 еженедельно",
        "weekdays": "🔄 по будням",
        "monthly":  "🔄 ежемесячно",
    }.get(recurrence, "")

    msg = (
        f"✅ *Напоминание создано!*\n\n"
        f"{p_icon}{c_icon} {r_text}\n"
        f"⏰ {t_local.strftime('%d.%m.%Y %H:%M')} {rec_str}"
    )
    if project:
        msg += f"\n📁 Проект: {project}"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🗑 Отменить", callback_data=f"del:{rid}")
    ]])
    await reply(update, user_id, msg, parse_mode="Markdown", reply_markup=keyboard)


async def _create_habit(update: Update, user_id: int, text: str):
    data  = await parse_habit(text)
    title = data.get("title", text[:50])
    freq  = data.get("frequency", "daily")
    emoji = data.get("emoji", "✅")

    db.add_habit(user_id, title, freq, emoji)
    freq_ru = {"daily": "каждый день", "weekly": "каждую неделю"}.get(freq, freq)

    msg = (
        f"🎯 *Привычка добавлена!*\n\n"
        f"{emoji} {title}\n"
        f"🔄 {freq_ru}\n\n"
        f"Отмечай выполнение в /habits 🔥"
    )
    await reply(update, user_id, msg, parse_mode="Markdown")


async def _save_note(update: Update, user_id: int, text: str):
    clean = text
    for prefix in ["запомни", "заметка:", "заметка", "сохрани идею:", "идея:"]:
        if clean.lower().startswith(prefix):
            clean = clean[len(prefix):].strip()
            break

    db.add_note(user_id, clean)
    await reply(
        update, user_id,
        f"📝 *Заметка сохранена!*\n\n{clean}\n\n/notes — все заметки",
        parse_mode="Markdown"
    )


async def _web_search(update: Update, user_id: int, query: str):
    """
    Ищет информацию через Perplexity.
    Telegram: красивое форматирование с эмодзи и источниками.
    TTS: отдельный текст без markdown, с читаемыми числами/процентами.
    """
    if not SEARCH_ENABLED:
        await update.effective_message.reply_text(
            "🔍 Поиск недоступен.\n"
            "Добавь `PERPLEXITY_API_KEY` в .env"
        )
        return

    await update.effective_message.chat.send_action(ChatAction.TYPING)

    from search import search_web, format_search_result, format_for_tts
    result       = await search_web(query)
    display_text = format_search_result(result)   # красивый текст для Telegram
    tts_text     = format_for_tts(result)          # чистый текст для голоса

    # Отправляем красивый текст в Telegram
    msg = update.effective_message
    await msg.reply_text(display_text, parse_mode="Markdown",
                         disable_web_page_preview=True)

    # Голосом читаем специально подготовленный TTS-текст
    if tts_text and is_voice_on(user_id):
        from tts import synthesize
        audio_path = await synthesize(tts_text)
        if audio_path:
            try:
                with open(audio_path, "rb") as f:
                    await msg.reply_voice(voice=f)
            except Exception as e:
                logger.error(f"search voice error: {e}")
            finally:
                if os.path.exists(audio_path):
                    os.unlink(audio_path)


async def _add_to_things(update: Update, user_id: int, text: str, tz_str: str):
    """
    Парсит задачу через AI и создаёт её в Things 3 через URL Scheme.
    Работает на Mac без паролей — Things 3 должен быть установлен.
    """
    await update.effective_message.chat.send_action(ChatAction.TYPING)
    status = await update.effective_message.reply_text("📋 Добавляю в Things 3...")

    from things_integration import parse_things_task, create_things_task

    # 1. Парсим задачу через AI
    task_data        = await parse_things_task(text, tz_str)
    title            = task_data["title"]
    notes            = task_data["notes"]
    due_date         = task_data["due_date"]
    reminder_minutes = task_data.get("reminder_minutes")
    tags             = task_data["tags"]

    # 2. Создаём задачу в Things 3 через URL Scheme
    result = await create_things_task(
        title=title,
        notes=notes,
        due_date=due_date,
        reminder_minutes=reminder_minutes,
        tags=tags,
        user_tz=tz_str
    )

    if result["success"]:
        due_part = f"\n⏰ Срок: {result['due']}" if result["due"] != "не указан" else ""

        # Показываем точное время напоминания
        # reminder_minutes=0 → "🔔 Напоминание в 12:00"
        # reminder_minutes>0 → "🔔 Напоминание в 14:00 (за 1ч до события)"
        remind_time = result.get("remind_time")
        remind_str  = result.get("remind_str")
        if remind_time and remind_str and remind_str != "в момент задачи":
            remind_part = f"\n🔔 Напоминание в {remind_time} (за {remind_str} до события)"
        elif remind_time:
            remind_part = f"\n🔔 Напоминание в {remind_time}"
        else:
            remind_part = ""

        tags_part = f"\n🏷 Теги: {', '.join(result['tags'])}" if result["tags"] else ""

        msg = (
            f"✅ *Задача добавлена в Things 3!*\n\n"
            f"📌 {title}"
            f"{due_part}"
            f"{remind_part}"
            f"{tags_part}"
        )
        await status.edit_text(msg, parse_mode="Markdown")

        if is_voice_on(user_id):
            voice_text = f"Задача «{title}» добавлена в Things 3."
            if result["due"] != "не указан":
                voice_text += f" Срок: {result['due']}."
            if result.get("remind_time") and result.get("remind_str") and result["remind_str"] != "в момент задачи":
                voice_text += f" Напоминание в {result['remind_time']}, за {result['remind_str']} до события."
            elif result.get("remind_time"):
                voice_text += f" Напоминание в {result['remind_time']}."
            await reply(update, user_id, voice_text)
    else:
        error = result["error"]
        await status.edit_text(
            f"❌ *Не удалось добавить в Things 3*\n\n"
            f"`{error}`\n\n"
            f"Убедись что Things 3 установлен на этом Mac.",
            parse_mode="Markdown"
        )
        logger.error(f"Things task failed for user={user_id}: {error}")


async def _crypto_query(update: Update, user_id: int, text: str):
    """
    Обрабатывает крипто-запросы:
    цены монет, DeFi TVL, Fear & Greed, топ рынок, тренды.
    Данные берутся напрямую из CoinGecko, DeFiLlama, Binance — без ключей.
    """
    import re
    await update.effective_message.chat.send_action(ChatAction.TYPING)
    status = await update.effective_message.reply_text("📊 Получаю данные...")

    try:
        from crypto import handle_crypto_query
        result_text = await handle_crypto_query(text)
    except ImportError as e:
        logger.error(f"crypto import error: {e}")
        await status.edit_text(
            "❌ Крипто-модуль не загружен.\n\n"
            "Установи зависимости:\n`pip install requests`",
            parse_mode="Markdown"
        )
        return
    except Exception as e:
        logger.error(f"crypto query error: {e}", exc_info=True)
        await status.edit_text(
            "❌ Не удалось получить крипто-данные.\n"
            "Проверь интернет-соединение и попробуй снова."
        )
        return

    # Отправляем результат — сначала пробуем Markdown, при ошибке шлём plain text
    try:
        await status.edit_text(result_text, parse_mode="Markdown",
                               disable_web_page_preview=True)
    except Exception:
        # Markdown сломался (спецсимволы) — шлём без форматирования
        clean = re.sub(r"[*_`]", "", result_text)
        await status.edit_text(clean, disable_web_page_preview=True)

    # Голосовой ответ — умное озвучивание без markdown и технических символов
    if is_voice_on(user_id):
        from crypto import make_tts_voice
        tts = make_tts_voice(result_text)
        from tts import synthesize
        audio_path = await synthesize(tts)
        if audio_path:
            try:
                with open(audio_path, "rb") as f:
                    await update.effective_message.reply_voice(voice=f)
            except Exception as e:
                logger.error(f"crypto voice error: {e}")
            finally:
                if os.path.exists(audio_path):
                    os.unlink(audio_path)


async def _ai_chat(update: Update, user_id: int, text: str, tz_str: str):
    if user_id not in _chat_history:
        _chat_history[user_id] = []

    _chat_history[user_id].append({"role": "user", "content": text})
    _chat_history[user_id] = _chat_history[user_id][-10:]

    response = await chat_with_ai(_chat_history[user_id], tz_str)

    _chat_history[user_id].append({"role": "assistant", "content": response})
    _chat_history[user_id] = _chat_history[user_id][-10:]

    await reply(update, user_id, response)


# ── Inline Callback ───────────────────────────────────────────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    data    = query.data
    await query.answer()

    tz = ZoneInfo(get_tz(user_id))

    if data.startswith("done:"):
        rid = int(data.split(":")[1])
        db.mark_done(rid)
        try:
            sched.scheduler.remove_job(f"rem_{rid}")
        except Exception:
            pass
        await query.edit_message_text("✅ *Выполнено!* Молодец!", parse_mode="Markdown")

    elif data.startswith("snooze:"):
        parts    = data.split(":")
        rid      = int(parts[1])
        minutes  = int(parts[2])
        new_time = datetime.now(tz) + timedelta(minutes=minutes)
        db.snooze_reminder(rid, new_time)
        job_id = sched.schedule_reminder(rid, user_id, new_time)
        db.update_job_id(rid, job_id)
        h_str = f"{minutes // 60}ч" if minutes >= 60 else f"{minutes}мин"
        await query.edit_message_text(
            f"⏰ Отложено на {h_str}, напомню в {new_time.strftime('%H:%M')}"
        )

    elif data.startswith("del:"):
        rid = int(data.split(":")[1])
        db.delete_reminder(rid)
        try:
            sched.scheduler.remove_job(f"rem_{rid}")
        except Exception:
            pass
        await query.edit_message_text("🗑 Удалено.")

    elif data.startswith("habit_done:"):
        hid   = int(data.split(":")[1])
        today = datetime.now(tz).strftime("%Y-%m-%d")
        db.mark_habit_done(hid, today)
        habit  = db.get_habit(hid)
        streak = habit["current_streak"] if habit else 0
        fire   = "🔥" * min(streak, 5)
        await query.edit_message_text(
            f"✅ *{habit['emoji']} {habit['title']}* — выполнено!\n"
            f"Стрик: {streak} дн. {fire}",
            parse_mode="Markdown"
        )

    elif data == "show_today":
        tz_str    = get_tz(user_id)
        today     = datetime.now(ZoneInfo(tz_str)).strftime("%Y-%m-%d")
        reminders = db.get_todays_reminders(user_id, today)
        if reminders:
            lines = ["📅 *Задачи на сегодня:*\n"]
            for r in reminders:
                lines.append(format_reminder(r, tz_str))
            await query.message.reply_text("\n".join(lines), parse_mode="Markdown")
        else:
            await query.message.reply_text("🎉 На сегодня задач нет!")

    elif data == "dismiss":
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "add_habit":
        await query.message.reply_text(
            "Напиши о привычке, например:\n«хочу каждый день читать 20 минут»"
        )

    elif data == "voice_on":
        db.update_setting(user_id, "voice_on", 1)
        await query.edit_message_text("🔊 Голосовые ответы включены!")

    elif data == "voice_off":
        db.update_setting(user_id, "voice_on", 0)
        await query.edit_message_text("🔇 Голосовые ответы выключены.")

    elif data == "morning_on":
        db.update_setting(user_id, "morning_on", 1)
        s = db.get_settings(user_id)
        sched.schedule_morning_digest(user_id, s["morning_h"], s["morning_m"])
        await query.edit_message_text("☀️ Утренний дайджест включён!")

    elif data == "morning_off":
        db.update_setting(user_id, "morning_on", 0)
        try:
            sched.scheduler.remove_job(f"morning_{user_id}")
        except Exception:
            pass
        await query.edit_message_text("🌙 Утренний дайджест выключен.")

    elif data.startswith("morning_"):
        time_str = data.replace("morning_", "")
        h = int(time_str[:-2])
        m = int(time_str[-2:])
        db.update_setting(user_id, "morning_h", h)
        db.update_setting(user_id, "morning_m", m)
        db.update_setting(user_id, "morning_on", 1)
        sched.schedule_morning_digest(user_id, h, m)
        await query.edit_message_text(f"⏰ Дайджест переставлен на {h:02d}:{m:02d}")

    elif data == "set_tz":
        await query.message.reply_text(
            "Напиши таймзону:\n`Europe/Moscow` · `Asia/Almaty` · `Asia/Novosibirsk`\n\n"
            "Список: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones",
            parse_mode="Markdown"
        )


# ── Сборка приложения ─────────────────────────────────────────────────────────

def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("list",     cmd_list))
    app.add_handler(CommandHandler("today",    cmd_today))
    app.add_handler(CommandHandler("habits",   cmd_habits))
    app.add_handler(CommandHandler("notes",    cmd_notes))
    app.add_handler(CommandHandler("stats",    cmd_stats))
    app.add_handler(CommandHandler("digest",   cmd_digest))
    app.add_handler(CommandHandler("voice",    cmd_voice))
    app.add_handler(CommandHandler("things",   cmd_things))
    app.add_handler(CommandHandler("settings", cmd_settings))

    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Глобальный обработчик ошибок — логирует все необработанные исключения
    app.add_error_handler(error_handler)

    return app

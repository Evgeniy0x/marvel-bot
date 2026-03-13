"""
ai_parser.py — GPT-4o (OpenRouter) разбирает сообщения пользователя.

Функции:
  detect_intent()   — определяет что хочет пользователь
  parse_reminder()  — извлекает дату/время и детали напоминания
  parse_habit()     — извлекает данные для новой привычки
  chat_with_ai()    — обычный AI-чат по управлению временем
  smart_morning()   — умный утренний брифинг с анализом задач
  weekly_review()   — AI-анализ прошедшей недели
"""
import json
import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_BASE_URL, AI_MODEL, TIMEZONE

logger = logging.getLogger(__name__)

# OpenRouter: обязательные заголовки
client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    default_headers={
        "HTTP-Referer": "https://github.com/marvel-bot",
        "X-Title": "Marvel AI Assistant",
    }
)

# ── Системные промпты ─────────────────────────────────────────────────────────

INTENT_SYSTEM = """Определи намерение пользователя. Верни ТОЛЬКО JSON:
{"intent": "reminder"|"habit"|"note"|"things"|"crypto"|"search"|"question"|"stats"|"list"|"habits_list"|"notes_list"|"help"}

Правила (читай внимательно):

- crypto: ПЕРВЫЙ ПРИОРИТЕТ когда речь идёт о крипте, DeFi, блокчейне, токенах.
  Триггеры: любые тикеры (btc, eth, sol, bnb, xrp, ton, ada, doge, usdt...),
  названия монет (биткоин, эфир, эфириум, солана, рипл, тезер, догикоин, шиба...),
  "крипта", "криптовалюта", "crypto", "defi", "дефи", "tvl", "блокчейн",
  "uniswap", "aave", "curve", "lido", "maker", "curve", "arbitrum", "optimism",
  "страх жадность", "fear greed", "индекс страха", "рынок крипты", "капитализация",
  "доминирование биткоина", "btc dom", "топ монет", "трендовые монеты",
  "курс биткоина", "цена эфира", "стоимость", "сколько стоит btc/eth/sol",
  "токен", "альткоин", "мем-коин", "стейблкоин", "nft", "web3"
  ЛЮБОЙ запрос про крипту или DeFi → crypto!

- things: ПРИОРИТЕТ для задач и напоминаний с конкретным временем/датой.
  Триггеры: "напомни", "напомни мне", "не забудь", "создай напоминание", "поставь напоминание",
  "добавь задачу", "новая задача", "создай задачу", "запиши задачу", "добавь в Things",
  "в Things", "Things 3", "финкс", "сфинкс", "тинги", "gtd", "в задачник",
  "запланируй", "поставь встречу", "добавь встречу", "занеси", "внеси",
  "нужно сделать", "надо сделать", "не забыть", "за час до", "за 30 минут до",
  "напомни за", "поставь напоминание за", "предупреди за".
  ЛЮБАЯ задача с датой/временем → things!

- reminder: ТОЛЬКО повторяющиеся Telegram-уведомления без Things: "каждый день напоминай мне",
  "каждое утро присылай", "еженедельно напоминай". Разовые напоминания → things!

- habit: регулярная привычка для трекинга ("хочу привычку", "трекай привычку", "добавь привычку")
- note: сохранить мысль БЕЗ времени ("запомни", "заметка", "сохрани идею", "запиши мысль")
- search: нужна актуальная информация из интернета — новости, погода, факты (НЕ крипта!)
- question: вопрос по продуктивности — НЕ требует интернета и НЕ задача
- stats: статистика/отчёт ("статистика", "итоги", "как я справляюсь")
- list: список напоминаний Марвела
- habits_list: список привычек
- notes_list: список заметок
- help: просит помощи

Примеры → crypto:
"курс биткоина" → crypto
"сколько стоит eth" → crypto
"btc цена" → crypto
"топ монет сегодня" → crypto
"индекс страха и жадности" → crypto
"tvl uniswap" → crypto
"топ defi протоколы" → crypto
"доминирование биткоина" → crypto
"трендовые монеты" → crypto
"крипто рынок" → crypto
"солана сейчас" → crypto

Примеры → things:
"напомни мне массаж завтра в 12" → things
"добавь задачу контер-страйк в 15:00" → things
"не забудь про встречу в пятницу" → things

Примеры → reminder (только повторяющиеся):
"каждое утро присылай мне мотивацию" → reminder
"каждую пятницу напоминай сдать отчёт" → reminder

Отвечай ТОЛЬКО JSON, без пояснений."""

PARSE_SYSTEM = """Ты парсер напоминаний. Извлеки из сообщения:
- text: текст напоминания (что нужно сделать)
- remind_at: дата и время "YYYY-MM-DD HH:MM" (локальное время)
- recurrence: null / "daily" / "weekly" / "weekdays" / "monthly"
- category: "work" / "personal" / "health" / "finance" / "general"
- priority: "low" / "normal" / "high" / "urgent"
- project: название проекта или null

Сейчас: {now} ({weekday})

Правила:
- "завтра" = следующий день, "послезавтра" = через 2 дня
- "через N часов/минут" = от текущего момента
- "вечером"=19:00, "утром"=08:00, "днём"=13:00, "ночью"=23:00
- "в понедельник/..." = ближайший такой день
- "срочно"/"важно" → priority: "urgent"/"high"
- "каждый день"/"ежедневно" → recurrence: "daily"
- "каждый [день недели]" → recurrence: "weekly"
- "по будням" → recurrence: "weekdays"

Верни ТОЛЬКО JSON без markdown."""

HABIT_SYSTEM = """Извлеки данные для создания привычки. Верни ТОЛЬКО JSON:
{"title": "название привычки", "frequency": "daily"|"weekly", "emoji": "подходящий эмодзи"}

Примеры:
"хочу каждый день делать зарядку" → {"title":"Зарядка","frequency":"daily","emoji":"🏃"}
"читать по 30 минут в день" → {"title":"Читать 30 минут","frequency":"daily","emoji":"📚"}
"пить воду каждые 2 часа" → {"title":"Выпить воду","frequency":"daily","emoji":"💧"}"""

CHAT_SYSTEM = """Ты Марвел — профессиональный AI-ассистент по управлению временем.
Помогаешь планировать день, расставлять приоритеты, не забывать важное.
Отвечаешь кратко, по делу, дружелюбно. Только на русском.
Не расписывай лишнего — ценишь время пользователя.
Текущее время: {now}"""

MORNING_SYSTEM = """Ты Марвел — AI-ассистент. Сделай краткий утренний брифинг.

Список задач на сегодня:
{tasks}

Напиши:
1. Одну мотивирующую фразу (1 строка)
2. Топ-3 приоритета на день (выбери из списка самые важные)
3. Одну конкретную рекомендацию по планированию

Отвечай на русском, кратко (максимум 10 строк). Используй эмодзи."""

WEEKLY_SYSTEM = """Ты Марвел — AI-коуч по продуктивности. Проанализируй неделю пользователя.

Статистика:
- Выполнено задач: {done}
- Пропущено: {missed}
- Процент выполнения: {rate}%
- Активные привычки: {habits}

Напиши:
1. Честную оценку недели (2-3 предложения)
2. Главный паттерн/проблему если есть
3. Одну конкретную рекомендацию на следующую неделю

Тон: дружелюбный коуч, не критикуй жёстко. Максимум 8 строк. На русском."""


# ── Функции ───────────────────────────────────────────────────────────────────

async def detect_intent(text: str) -> str:
    """Определяет что хочет пользователь. Быстрый вызов с temperature=0."""
    try:
        raw = await _call_ai(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": INTENT_SYSTEM},
                {"role": "user",   "content": text},
            ],
            temperature=0,
            max_tokens=30,
            response_format={"type": "json_object"}
        )
        data = json.loads(raw)
        return data.get("intent", "question")
    except Exception as e:
        logger.error(f"detect_intent error: {e}")
        return "question"


async def parse_reminder(text: str, user_tz: str = TIMEZONE) -> dict:
    """Парсит напоминание из текста. Возвращает dict с remind_at_dt или error."""
    tz = ZoneInfo(user_tz)
    now = datetime.now(tz)
    weekdays = ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"]

    system = PARSE_SYSTEM.format(
        now=now.strftime("%Y-%m-%d %H:%M"),
        weekday=weekdays[now.weekday()]
    )
    try:
        raw = await _call_ai(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": text},
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        data = json.loads(raw)

        if not data.get("remind_at"):
            return {"error": "time_not_found", "raw": data}

        remind_dt = datetime.strptime(data["remind_at"], "%Y-%m-%d %H:%M")
        remind_dt = remind_dt.replace(tzinfo=tz)

        if remind_dt < now and not data.get("recurrence"):
            return {"error": "time_in_past", "parsed_time": data["remind_at"]}

        data["remind_at_dt"] = remind_dt
        return data

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        return {"error": "parse_failed"}
    except Exception as e:
        logger.error(f"parse_reminder error: {e}")
        return {"error": str(e)}


async def parse_habit(text: str) -> dict:
    """Парсит данные новой привычки из текста."""
    try:
        raw = await _call_ai(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": HABIT_SYSTEM},
                {"role": "user",   "content": text},
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        return json.loads(raw)
    except Exception as e:
        logger.error(f"parse_habit error: {e}")
        return {"title": text[:50], "frequency": "daily", "emoji": "✅"}


async def _call_ai(model: str, messages: list, temperature: float = 0.7,
                   max_tokens: int = 500, response_format=None) -> str:
    """
    Универсальный вызов OpenRouter с фолбэком на бесплатную модель.
    Если основная модель недоступна — пробует llama-3.1-8b бесплатно.
    """
    FALLBACK_MODEL = "meta-llama/llama-3.1-8b-instruct:free"

    kwargs = dict(
        temperature=temperature,
        max_tokens=max_tokens,
        messages=messages
    )
    if response_format:
        kwargs["response_format"] = response_format

    # Попытка с основной моделью
    try:
        response = await client.chat.completions.create(model=model, **kwargs)
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Основная модель ({model}) недоступна: {e}")

    # Фолбэк на бесплатную модель
    if model != FALLBACK_MODEL:
        try:
            logger.info(f"Пробую фолбэк модель: {FALLBACK_MODEL}")
            response = await client.chat.completions.create(
                model=FALLBACK_MODEL, **kwargs
            )
            return response.choices[0].message.content
        except Exception as e2:
            logger.error(f"Фолбэк модель тоже недоступна: {e2}")
            raise e2
    raise Exception("All models failed")


async def chat_with_ai(messages: list, user_tz: str = TIMEZONE) -> str:
    """Обычный AI-чат — советы по продуктивности и планированию."""
    tz = ZoneInfo(user_tz)
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M %Z")
    system = CHAT_SYSTEM.format(now=now)
    try:
        return await _call_ai(
            model=AI_MODEL,
            messages=[{"role": "system", "content": system}] + messages,
            temperature=0.7,
            max_tokens=500
        )
    except Exception as e:
        logger.error(f"chat_with_ai полностью провалился: {e}")
        return f"❌ AI недоступен: {type(e).__name__}. Проверь API ключ и баланс OpenRouter."


async def smart_morning_briefing(tasks_text: str, user_tz: str = TIMEZONE) -> str:
    """Умный утренний брифинг с AI-анализом задач на день."""
    if not tasks_text.strip():
        return "☀️ Доброе утро! Сегодня список задач пуст — отличный день для новых планов!"
    try:
        return await _call_ai(
            model=AI_MODEL,
            messages=[{"role": "user", "content": MORNING_SYSTEM.format(tasks=tasks_text)}],
            temperature=0.6,
            max_tokens=400
        )
    except Exception as e:
        logger.error(f"smart_morning error: {e}")
        return f"☀️ Доброе утро! Твои задачи на сегодня:\n\n{tasks_text}"


async def weekly_ai_review(done: int, missed: int, total: int,
                           habits_summary: str) -> str:
    """AI-анализ прошедшей недели."""
    rate = round(done / total * 100) if total > 0 else 0
    try:
        return await _call_ai(
            model=AI_MODEL,
            messages=[{"role": "user", "content": WEEKLY_SYSTEM.format(
                done=done, missed=missed, rate=rate, habits=habits_summary
            )}],
            temperature=0.7,
            max_tokens=300
        )
    except Exception as e:
        logger.error(f"weekly_review error: {e}")
        return f"📊 За неделю: выполнено {done}, пропущено {missed} ({rate}%)."


async def suggest_priority(task_text: str) -> str:
    """AI предлагает приоритет для задачи."""
    try:
        raw = await _call_ai(
            model=AI_MODEL,
            messages=[{"role": "user", "content":
                f'Приоритет задачи: "{task_text}". '
                f'JSON: {{"priority":"low"|"normal"|"high"|"urgent"}}'
            }],
            temperature=0,
            max_tokens=50,
            response_format={"type": "json_object"}
        )
        data = json.loads(raw)
        return data.get("priority", "normal")
    except Exception:
        return "normal"

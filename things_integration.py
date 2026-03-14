"""
things_integration.py — Интеграция с Things 3 через URL Scheme.

Метод: open "things:///add?title=...&when=...&reminder=...&notes=...&tags=..."
  Работает напрямую на Mac где установлен Things 3.
  Не требует паролей и авторизации — только things:// URL.

Документация Things 3 URL Scheme:
  https://culturedcode.com/things/support/articles/2803573/
"""

import json as _json
import logging
import re
import subprocess
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

from config import TIMEZONE


# ── Создание задачи через JSON API ────────────────────────────────────────────

async def create_things_task(
    title: str,
    notes: str = "",
    due_date: Optional[datetime] = None,
    reminder_minutes: Optional[int] = None,
    tags: list = None,
    user_tz: str = TIMEZONE
) -> dict:
    """
    Создаёт задачу в Things 3 через JSON API (things:///json).
    JSON API поддерживает все параметры: when, reminder, tags, notes.
    """
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _create_via_json_api(title, notes, due_date, reminder_minutes, tags, user_tz)
        )
        return result
    except Exception as e:
        logger.error(f"create_things_task error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _remind_str(reminder_minutes: int) -> str:
    """Форматирует время напоминания для отображения пользователю."""
    if reminder_minutes == 0:
        return "в момент задачи"
    h = reminder_minutes // 60
    m = reminder_minutes % 60
    if h > 0 and m > 0:
        return f"{h}ч {m}мин"
    elif h > 0:
        return f"{h}ч"
    return f"{m}мин"


def _create_via_json_api(
    title: str,
    notes: str,
    due_date: Optional[datetime],
    reminder_minutes: Optional[int],
    tags: Optional[list],
    user_tz: str
) -> dict:
    """
    Использует things:///json API — поддерживает reminder с точным временем.
    Формат reminder: ISO 8601 "YYYY-MM-DDTHH:MM:SS"
    """
    tz = ZoneInfo(user_tz)
    now = datetime.now(tz)

    attributes: dict = {"title": title}

    if notes:
        attributes["notes"] = notes

    due_str = "не указан"
    remind_str_display = None
    remind_time_display = None  # точное время напоминания, напр. "14:00"

    if due_date:
        if due_date.tzinfo is None:
            due_date = due_date.replace(tzinfo=tz)
        local_dt = due_date.astimezone(tz)
        due_str = local_dt.strftime("%d.%m.%Y %H:%M")

        # Добавляем время прямо в название задачи: "Массаж" → "Массаж в 12:00"
        time_suffix = f" в {local_dt.strftime('%H:%M')}"
        if time_suffix not in title:  # не дублируем, если время уже есть в названии
            title = title + time_suffix
            attributes["title"] = title

        # when: "today@HH:MM" / "tomorrow@HH:MM" / "YYYY-MM-DD@HH:MM"
        if local_dt.date() == now.date():
            attributes["when"] = f"today@{local_dt.strftime('%H:%M')}"
        elif local_dt.date() == (now + timedelta(days=1)).date():
            attributes["when"] = f"tomorrow@{local_dt.strftime('%H:%M')}"
        else:
            attributes["when"] = local_dt.strftime("%Y-%m-%d") + f"@{local_dt.strftime('%H:%M')}"

        # Если пользователь не указал время напоминания — ставим напоминание на момент задачи
        if reminder_minutes is None:
            reminder_minutes = 0

        # reminder: формат "YYYY-MM-DD@HH:MM" — тот же что и when, Things трактует как локальное время
        if reminder_minutes >= 0:
            remind_dt = local_dt - timedelta(minutes=reminder_minutes)
            attributes["reminder"] = remind_dt.strftime("%Y-%m-%d") + "@" + remind_dt.strftime("%H:%M")
            remind_str_display = _remind_str(reminder_minutes)
            remind_time_display = remind_dt.strftime("%H:%M")  # точное время напоминания, напр. "14:00"
            logger.info(f"Reminder: {remind_time_display} (за {remind_str_display} до {local_dt.strftime('%H:%M')})")

    if tags:
        attributes["tags"] = tags  # JSON API принимает массив тегов

    # Собираем JSON payload
    payload = [{"type": "to-do", "attributes": attributes}]
    json_str = _json.dumps(payload, ensure_ascii=False)
    url = f"things:///json?data={quote(json_str)}"

    logger.info(f"Things JSON API: {json_str}")

    result = subprocess.run(
        ["open", url],
        capture_output=True,
        text=True,
        timeout=10
    )

    if result.returncode != 0:
        err = result.stderr.strip() or "Не удалось открыть things:// URL. Убедись что Things 3 установлен."
        logger.error(f"open things:// error: {err}")
        raise RuntimeError(err)

    logger.info(f"Things 3: задача создана «{title}»")
    return {
        "success":     True,
        "title":       title,
        "notes":       notes,
        "due":         due_str,
        "tags":        tags or [],
        "remind_str":  remind_str_display,   # "1ч", "30мин", "2ч 15мин" и т.д.
        "remind_time": remind_time_display,  # "14:00", "09:30" и т.д.
    }


# ── Очистка триггерных слов ────────────────────────────────────────────────────

# Всё что нужно убрать из текста перед парсингом — служебные команды
_TRIGGER_PATTERNS = [
    # "добавь в Things/Финкс/Сфинкс/GTD ..."
    r"добавь\s+в\s+(things\s*3?|финкс|сфинкс|тинги|задачник|менеджер\s+задач|gtd)\s*[:\-–]?\s*",
    # "в Things/Финкс ..." в начале
    r"^в\s+(things\s*3?|финкс|сфинкс|тинги|gtd)\s*[:\-–,]?\s*",
    # "добавь это/его в Финкс" → убираем всю фразу
    r"добавь\s+(это|его|её|их|то)\s+в\s+(things\s*3?|финкс|сфинкс|тинги|gtd)\s*[!\.]?",
    # "создай/добавь/запиши/новая задачу ..."
    r"(создай|добавь|запиши|внеси|занеси)\s+задачу\s*[:\-–]?\s*",
    r"новая\s+задача\s*[:\-–]?\s*",
    # "запланируй ..."
    r"^запланируй\s+",
    # "поставь встречу/задачу ..."
    r"^поставь\s+(встречу|задачу)\s*",
    # "добавь встречу ..."
    r"^добавь\s+встречу\s+",
    # "нужно/надо сделать ..."
    r"^(нужно|надо)\s+сделать\s+",
    # Просто "добавь это/то"
    r"^добавь\s+(это|то|его|её)\s*[!\.]?$",
]

def _clean_trigger(text: str) -> str:
    """Убирает служебные слова-триггеры, оставляя суть задачи."""
    result = text.strip()
    for pattern in _TRIGGER_PATTERNS:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE).strip()
    # Убираем лишние знаки препинания в начале
    result = re.sub(r"^[:\-–,!\.]+\s*", "", result).strip()
    return result if result else text


# ── AI-парсинг задачи ──────────────────────────────────────────────────────────

THINGS_PARSE_PROMPT = """Ты парсер задач для менеджера Things 3. Извлеки из текста:

- title: суть задачи кратко (до 60 символов)
  Правила для title:
  • Убери все слова-триггеры: "напомни", "добавь", "создай", "запланируй", "поставь", "не забудь"
  • Убери временны́е маркеры из названия (время/дату)
  • Оставь только суть: ЧТО нужно сделать
  • Первая буква заглавная
  Примеры: "напомни про массаж" → "Массаж", "добавь встречу с врачом" → "Встреча с врачом"

- notes: дополнительные детали (если есть, иначе "")

- due_date: дата и время задачи "YYYY-MM-DD HH:MM" или null
  • "сегодня" = {today}
  • "завтра" = {tomorrow}
  • "вечером" = 19:00, "утром" = 09:00, "днём" = 13:00, "ночью" = 22:00
  • "в пятницу" = ближайшая пятница

- reminder_minutes: за сколько МИНУТ до задачи поставить напоминание
  • "напомни", "напомни мне", "не забудь напомнить" без "до/за" → 0
  • "за час до" / "предупреди за час" → 60
  • "за полчаса" / "за 30 минут" → 30
  • "за 2 часа" → 120
  • "за 15 минут" → 15
  • "за день" / "за сутки" → 1440
  • задача без упоминания напоминания → null

- tags: список подходящих тегов (только из: работа, личное, здоровье, финансы, покупки, звонки, учёба, спорт, семья)

Контекст: сейчас {now} ({weekday})

Верни ТОЛЬКО JSON:
{{"title":"...","notes":"...","due_date":"YYYY-MM-DD HH:MM или null","reminder_minutes":число или null,"tags":["..."]}}"""


async def parse_things_task(text: str, user_tz: str = TIMEZONE) -> dict:
    """
    Парсит задачу из произвольного текста через AI.
    Возвращает title, notes, due_date, reminder_minutes, tags.
    """
    import json
    from ai_parser import _call_ai
    from config import AI_MODEL

    # Очищаем триггерные слова
    cleaned = _clean_trigger(text)
    logger.debug(f"parse_things_task: '{text}' → '{cleaned}'")

    tz = ZoneInfo(user_tz)
    now = datetime.now(tz)
    weekdays = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    tomorrow = (now + timedelta(days=1)).date()

    system = THINGS_PARSE_PROMPT.format(
        now=now.strftime("%Y-%m-%d %H:%M"),
        weekday=weekdays[now.weekday()],
        today=now.strftime("%Y-%m-%d"),
        tomorrow=tomorrow.strftime("%Y-%m-%d"),
    )

    try:
        raw = await _call_ai(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": cleaned},
            ],
            temperature=0,
            max_tokens=250,
            response_format={"type": "json_object"}
        )
        data = json.loads(raw)

        # Парсим due_date
        due_dt = None
        due_raw = str(data.get("due_date") or "").strip()
        if due_raw and due_raw.lower() not in ("null", "none", ""):
            try:
                due_dt = datetime.strptime(due_raw, "%Y-%m-%d %H:%M")
                due_dt = due_dt.replace(tzinfo=ZoneInfo(user_tz))
            except ValueError:
                logger.warning(f"Не удалось распарсить due_date: {due_raw!r}")

        # Парсим reminder_minutes
        reminder_minutes = None
        rm_raw = data.get("reminder_minutes")
        if rm_raw is not None and str(rm_raw).lower() not in ("null", "none", ""):
            try:
                reminder_minutes = int(rm_raw)
                if reminder_minutes < 0:
                    reminder_minutes = 0
            except (ValueError, TypeError):
                pass

        # Если title пустой — используем очищенный текст
        title = (data.get("title") or cleaned or text)[:80].strip()
        if not title:
            title = text[:80]

        return {
            "title":            title,
            "notes":            data.get("notes", ""),
            "due_date":         due_dt,
            "reminder_minutes": reminder_minutes,
            "tags":             data.get("tags", []),
        }

    except Exception as e:
        logger.error(f"parse_things_task error: {e}")
        return {
            "title":            cleaned[:80] or text[:80],
            "notes":            "",
            "due_date":         None,
            "reminder_minutes": None,
            "tags":             [],
        }


# ── Чтение задач из Things 3 (AppleScript) ────────────────────────────────────
# Работает без токена — напрямую через приложение Things 3 на Mac.

_THINGS_SCRIPT_TODAY = '''
tell application "Things3"
    set output to ""
    try
        set todayTasks to to dos of list "Today"
        repeat with t in todayTasks
            set tName to name of t
            set tStatus to (status of t) as text
            set tTimeStr to ""
            try
                set tAct to activation date of t
                set tH to hours of tAct
                set tM to minutes of tAct
                if tH < 10 then
                    set tTimeStr to "0" & (tH as text)
                else
                    set tTimeStr to (tH as text)
                end if
                set tTimeStr to tTimeStr & ":"
                if tM < 10 then
                    set tTimeStr to tTimeStr & "0" & (tM as text)
                else
                    set tTimeStr to tTimeStr & (tM as text)
                end if
            end try
            set tProject to ""
            try
                set tProject to (name of project of t) as text
            end try
            set tArea to ""
            try
                set tArea to (name of area of t) as text
            end try
            set output to output & tName & "|||" & tStatus & "|||" & tTimeStr & "|||" & tProject & "|||" & tArea & (ASCII character 10)
        end repeat
    end try
    return output
end tell
'''

_THINGS_SCRIPT_UPCOMING = '''
tell application "Things3"
    set output to ""
    try
        set upcomingTasks to to dos of list "Upcoming"
        repeat with t in upcomingTasks
            set tName to name of t
            set tStatus to (status of t) as text
            set tDue to ""
            try
                set tDue to (due date of t) as text
            end try
            set tProject to ""
            try
                set tProject to (name of project of t) as text
            end try
            set output to output & tName & "|||" & tStatus & "|||" & tDue & "|||" & tProject & (ASCII character 10)
        end repeat
    end try
    return output
end tell
'''


def _run_applescript(script: str) -> Optional[str]:
    """Запускает AppleScript через stdin (надёжнее чем -e для многострочных скриптов)."""
    try:
        result = subprocess.run(
            ["osascript"],
            input=script,
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return result.stdout
        logger.warning(f"AppleScript stderr: {result.stderr[:300]}")
        return None
    except FileNotFoundError:
        logger.error("osascript не найден — не macOS?")
        return None
    except subprocess.TimeoutExpired:
        logger.error("AppleScript timeout")
        return None
    except Exception as e:
        logger.error(f"AppleScript error: {e}")
        return None


def _parse_things_output(raw: str) -> list:
    """Парсит вывод AppleScript в список задач."""
    tasks = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("|||")
        if not parts[0].strip():
            continue

        title    = parts[0].strip()
        status   = parts[1].strip() if len(parts) > 1 else ""
        reminder = parts[2].strip() if len(parts) > 2 else ""
        project  = parts[3].strip() if len(parts) > 3 else ""
        area     = parts[4].strip() if len(parts) > 4 else ""

        # "missing value" — заглушка AppleScript для пустых значений
        project = "" if project == "missing value" else project
        area    = "" if area    == "missing value" else area
        reminder= "" if reminder== "missing value" else reminder

        tasks.append({
            "title":     title,
            "completed": "completed" in status.lower(),
            "canceled":  "canceled"  in status.lower(),
            "reminder":  reminder,   # "HH:MM" или ""
            "project":   {"title": project} if project else {},
            "area":      {"title": area}    if area    else {},
        })
    return tasks


async def get_things_today() -> Optional[list]:
    """
    Читает задачи на сегодня из Things 3 через AppleScript.
    Не требует токена — Things 3 должен быть запущен на Mac.
    """
    loop = asyncio.get_running_loop()
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as ex:
        raw = await loop.run_in_executor(
            ex, lambda: _run_applescript(_THINGS_SCRIPT_TODAY)
        )
    if raw is None:
        return None
    return _parse_things_output(raw)


async def get_things_upcoming(days: int = 7) -> Optional[list]:
    """Задачи на ближайшее время из Things 3 через AppleScript."""
    loop = asyncio.get_running_loop()
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as ex:
        raw = await loop.run_in_executor(
            ex, lambda: _run_applescript(_THINGS_SCRIPT_UPCOMING)
        )
    if raw is None:
        return None
    return _parse_things_output(raw)


def format_things_tasks(tasks: list, tz_str: str = TIMEZONE) -> str:
    """Форматирует задачи Things 3 для красивого отображения в Telegram."""
    from zoneinfo import ZoneInfo

    tz  = ZoneInfo(tz_str)
    now = datetime.now(tz)

    todo = [t for t in tasks if not t.get("completed") and not t.get("canceled")]
    done = [t for t in tasks if t.get("completed")]

    if not todo and not done:
        return (
            "🎉 *В Things 3 на сегодня задач нет!*\n"
            "_Можешь добавить: «Встреча завтра в 10:00»_"
        )

    lines = [
        f"📋 *Задачи на сегодня* — {now.strftime('%d.%m.%Y')}",
        "_Things 3 · " + str(len(todo)) + " активных"
        + (f" · {len(done)} выполнено" if done else "") + "_",
        "",
    ]

    for t in todo:
        title    = t.get("title") or "Без названия"
        project  = (t.get("project") or {}).get("title", "")
        area     = (t.get("area")    or {}).get("title", "")
        reminder = t.get("reminder", "")

        # AppleScript возвращает время как "HH:MM"
        time_str = f" ⏰ {reminder}" if reminder else ""
        context  = project or area
        ctx_str  = f"  _· {context}_" if context else ""

        lines.append(f"⬜ *{title}*{time_str}{ctx_str}")

    if done:
        lines.append("")
        lines.append("_Выполнено сегодня:_")
        for t in done[:5]:
            lines.append(f"✅ {t.get('title', '?')}")
        if len(done) > 5:
            lines.append(f"_...и ещё {len(done) - 5}_")

    lines.append(f"\n_Things 3 · {now.strftime('%H:%M')}_")
    return "\n".join(lines)

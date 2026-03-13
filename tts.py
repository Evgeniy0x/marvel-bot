"""
tts.py — Преобразование текста в голос через OpenAI TTS.

Умно подготавливает текст перед озвучкой:
- убирает Markdown-разметку
- конвертирует $, %, +/- в читаемый русский текст
- убирает URL и citation-цифры
- обрезает до лимита TTS
"""
import logging
import os
import re
import tempfile

from openai import AsyncOpenAI
from config import WHISPER_API_KEY, WHISPER_BASE_URL, TTS_VOICE, TTS_MODEL

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(api_key=WHISPER_API_KEY, base_url=WHISPER_BASE_URL)

MAX_TTS_LENGTH = 900   # оставляем запас до лимита TTS (4096)


def _prepare_text(text: str) -> str:
    """
    Превращает текст в «говоримый» вид для TTS:
    1. Убирает Markdown
    2. Убирает URL
    3. Конвертирует финансовые/числовые обозначения → русский текст
    4. Убирает citation-цифры Perplexity
    5. Очищает лишние пробелы
    6. Обрезает до MAX_TTS_LENGTH
    """
    # ── Убираем citation-числа Perplexity (.123, .1234)
    text = re.sub(r'(\w)\.\d{1,4}(?=[\s,\n]|$)', r'\1.', text)
    text = re.sub(r'\s+\d{1,4}(?=[\s\n]|$)', '', text)

    # ── Убираем Markdown
    text = re.sub(r'\*+(.+?)\*+', r'\1', text)       # **bold** / *italic*
    text = re.sub(r'`+[^`]*`+', '', text)             # `code`
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)  # # заголовки
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)       # [ссылка](url)
    text = re.sub(r'_{1,2}(.+?)_{1,2}', r'\1', text)            # _курсив_

    # ── Убираем URL полностью
    text = re.sub(r'https?://\S+', '', text)

    # ── Конвертируем финансовые обозначения → читаемый текст
    # $1,234,567 → 1 234 567 долларов
    def money_large(m):
        digits = m.group(1).replace(',', '')
        n = int(digits)
        if n >= 1_000_000_000_000:
            return f"{n / 1_000_000_000_000:.1f} триллионов долларов".replace('.', ',')
        elif n >= 1_000_000_000:
            return f"{n / 1_000_000_000:.1f} миллиардов долларов".replace('.', ',')
        elif n >= 1_000_000:
            return f"{n / 1_000_000:.1f} миллионов долларов".replace('.', ',')
        elif n >= 1_000:
            return f"{n // 1_000} тысяч долларов"
        return f"{n} долларов"

    text = re.sub(r'\$(\d{1,3}(?:,\d{3})*)', money_large, text)
    text = re.sub(r'\$(\d+[\.,]\d+)\s*трлн', lambda m: f"{m.group(1)} триллионов долларов", text)
    text = re.sub(r'\$(\d+)\s*трлн', lambda m: f"{m.group(1)} триллионов долларов", text)
    text = re.sub(r'\$(\d+[\.,]\d+)\s*млрд', lambda m: f"{m.group(1)} миллиардов долларов", text)
    text = re.sub(r'\$(\d+)\s*млрд', lambda m: f"{m.group(1)} миллиардов долларов", text)
    text = re.sub(r'\$(\d+[\.,]\d+)', lambda m: f"{m.group(1)} доллара", text)
    text = re.sub(r'\$(\d+)', lambda m: f"{m.group(1)} долларов", text)

    # ₿ Bitcoin
    text = re.sub(r'₿\s*(\d[\d,\.]*)', lambda m: f"{m.group(1)} биткоин", text)

    # Проценты: +4,10% → плюс 4,10 процента
    text = re.sub(r'\+(\d+[\.,]\d+)%', lambda m: f"плюс {m.group(1)} процента", text)
    text = re.sub(r'\+(\d+)%', lambda m: f"плюс {m.group(1)} процентов", text)
    text = re.sub(r'[−-](\d+[\.,]\d+)%', lambda m: f"минус {m.group(1)} процента", text)
    text = re.sub(r'[−-](\d+)%', lambda m: f"минус {m.group(1)} процентов", text)
    text = re.sub(r'(\d+[\.,]\d+)%', lambda m: f"{m.group(1)} процента", text)
    text = re.sub(r'(\d+)%', lambda m: f"{m.group(1)} процентов", text)

    # Числа с пробелами-разделителями: 73 000 → 73 тысячи
    # (оставляем как есть — TTS сам читает числа)

    # ── Убираем спецсимволы и лишние пробелы
    text = text.replace('▸', '').replace('📌', '').replace('🔗', '')
    text = text.replace('•', '').replace('—', ',')
    text = re.sub(r'\n+', ' ', text)    # переносы → пробел
    text = re.sub(r'\s{2,}', ' ', text) # двойные пробелы → одинарный
    text = text.strip()

    # ── Обрезаем до лимита
    if len(text) > MAX_TTS_LENGTH:
        # Обрезаем по последнему предложению перед лимитом
        cut = text[:MAX_TTS_LENGTH]
        last_dot = max(cut.rfind('. '), cut.rfind('! '), cut.rfind('? '))
        if last_dot > MAX_TTS_LENGTH // 2:
            text = cut[:last_dot + 1] + " Ответ обрезан."
        else:
            text = cut + "..."

    return text


async def synthesize(text: str) -> str | None:
    """
    Синтезирует речь из текста.
    Возвращает путь к временному MP3 файлу или None при ошибке.
    Файл нужно удалить после отправки!
    """
    if not WHISPER_API_KEY:
        logger.warning("TTS: OPENAI_WHISPER_KEY не задан")
        return None

    clean_text = _prepare_text(text)
    if not clean_text:
        return None

    logger.info(f"TTS синтез: {len(clean_text)} символов")

    try:
        response = await _client.audio.speech.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            input=clean_text,
            response_format="mp3"
        )

        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.write(response.content)
        tmp.close()
        logger.info(f"TTS сгенерирован: {tmp.name} ({len(response.content)} байт)")
        return tmp.name

    except Exception as e:
        logger.error(f"TTS ошибка: {e}")
        return None


async def send_voice_reply(message, text: str):
    """Отправляет голосовой ответ. При недоступности TTS — только текст."""
    audio_path = await synthesize(text)
    if audio_path:
        try:
            with open(audio_path, "rb") as f:
                await message.reply_voice(voice=f)
        except Exception as e:
            logger.error(f"send_voice_reply ошибка: {e}")
            await message.reply_text(text)
        finally:
            if os.path.exists(audio_path):
                os.unlink(audio_path)
    else:
        await message.reply_text(text)

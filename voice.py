"""
voice.py — Транскрипция голосовых сообщений через OpenAI Whisper.

Telegram присылает голосовое → скачиваем .ogg → Whisper переводит в текст
→ дальше обрабатываем как обычное текстовое сообщение.
"""
import os
import logging
import tempfile

from openai import AsyncOpenAI
from config import WHISPER_API_KEY, WHISPER_BASE_URL

logger = logging.getLogger(__name__)

# Whisper работает только через прямой OpenAI API (OpenRouter не поддерживает audio)
whisper_client = AsyncOpenAI(
    api_key=WHISPER_API_KEY,
    base_url=WHISPER_BASE_URL,
)


async def transcribe_voice(bot, file_id: str) -> str:
    """
    Скачивает голосовое сообщение и транскрибирует через Whisper.
    Возвращает текст или пустую строку при ошибке.
    """
    tmp_path = None
    try:
        # Получаем файл от Telegram
        tg_file = await bot.get_file(file_id)

        # Сохраняем во временный файл
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name

        await tg_file.download_to_drive(tmp_path)
        logger.info(f"Голосовое скачано: {tmp_path}")

        # Отправляем в Whisper
        with open(tmp_path, "rb") as audio_file:
            transcript = await whisper_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru",          # подсказка — в основном русский
                response_format="text"
            )

        text = transcript.strip() if isinstance(transcript, str) else transcript
        logger.info(f"Транскрипция: «{text}»")
        return text

    except Exception as e:
        logger.error(f"Ошибка транскрипции: {e}")
        return ""
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

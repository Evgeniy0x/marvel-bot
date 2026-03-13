"""
search.py — Поиск в интернете через Perplexity API (sonar-pro).
"""
import logging
import re
from openai import AsyncOpenAI
from config import PERPLEXITY_API_KEY

logger = logging.getLogger(__name__)

PERPLEXITY_BASE_URL = "https://api.perplexity.ai"
SEARCH_MODEL        = "sonar-pro"

_client = AsyncOpenAI(
    api_key=PERPLEXITY_API_KEY or "placeholder",
    base_url=PERPLEXITY_BASE_URL,
)

SEARCH_SYSTEM = """Ты умный поисковый ассистент.
Отвечай на русском языке. Будь конкретным и точным.
Если это вопрос о текущих событиях, ценах, погоде или новостях — дай актуальный ответ.
Структурируй ответ: сначала главное, потом детали.
Не пиши «по состоянию на...» — просто отвечай по делу.
Если даёшь список — используй дефис «-» в начале каждого пункта."""


def _extract_citations(response) -> list:
    """Извлекает citations из ответа Perplexity несколькими способами."""
    for getter in [
        lambda r: getattr(r, "citations", None),
        lambda r: (getattr(r, "model_extra", None) or {}).get("citations"),
        lambda r: r.__dict__.get("citations"),
    ]:
        try:
            result = getter(response)
            if result and isinstance(result, list):
                return result
        except Exception:
            pass
    return []


def _clean_text(text: str) -> str:
    """
    Очищает текст от артефактов Perplexity:
    — убирает inline-цитаты (.123, .1234)
    — убирает одиночные числа в конце предложений (артефакты citation ref)
    — конвертирует markdown-заголовки в Telegram Bold
    """
    # Убираем inline цифры-цитаты: "текст.123" → "текст" и "текст .123" → "текст"
    text = re.sub(r'(\w)\.\d{1,4}(?=[\s,\n]|$)', r'\1.', text)
    text = re.sub(r'\s+\d{1,4}(?=[\s\n]|$)', '', text)

    # Конвертируем markdown заголовки → жирный текст Telegram
    text = re.sub(r'^#{1,3}\s+(.+)$', r'*\1*', text, flags=re.MULTILINE)

    # Убираем **, оставляем только одиночные *
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)

    # Убираем лишние пустые строки (больше 2 подряд)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def _format_beautiful(text: str, citations: list) -> str:
    """
    Форматирует результат поиска красиво для Telegram.
    Разбивает текст на блоки, добавляет эмодзи, оформляет источники.
    """
    lines = text.strip().split('\n')
    result_lines = []
    in_list = False

    for line in lines:
        line = line.strip()
        if not line:
            if in_list:
                in_list = False
                result_lines.append('')
            else:
                result_lines.append('')
            continue

        # Заголовки (уже сконвертированы в *bold*)
        if line.startswith('*') and line.endswith('*') and len(line) > 2:
            result_lines.append('')
            result_lines.append(f'📌 {line}')
            result_lines.append('')
            in_list = False

        # Элементы списка (- или •)
        elif line.startswith('- ') or line.startswith('• '):
            content = line[2:].strip()
            result_lines.append(f'  ▸ {content}')
            in_list = True

        # Числа в начале строки (нумерованный список)
        elif re.match(r'^\d+[\.\)]\s', line):
            content = re.sub(r'^\d+[\.\)]\s+', '', line)
            result_lines.append(f'  ▸ {content}')
            in_list = True

        # Обычный текст
        else:
            result_lines.append(line)
            in_list = False

    body = '\n'.join(result_lines).strip()
    # Убираем тройные переносы
    body = re.sub(r'\n{3,}', '\n\n', body)

    # Блок источников
    sources_block = ''
    if citations:
        sources_block = '\n\n🔗 *Источники:*\n'
        for i, url in enumerate(citations[:3], 1):
            # Сокращаем длинные URL до домена
            domain = re.sub(r'https?://(www\.)?([^/]+).*', r'\2', url)
            sources_block += f'  {i}\\. [{domain}]({url})\n'

    return f'🔍 {body}{sources_block}'.strip()


async def search_web(query: str) -> dict:
    """Выполняет поиск через Perplexity и возвращает ответ с источниками."""
    if not PERPLEXITY_API_KEY:
        return {"answer": "", "citations": [], "error": "PERPLEXITY_API_KEY не задан"}

    try:
        response = await _client.chat.completions.create(
            model=SEARCH_MODEL,
            messages=[
                {"role": "system", "content": SEARCH_SYSTEM},
                {"role": "user",   "content": query},
            ],
            max_tokens=1000,
            temperature=0.2,
            extra_body={"return_citations": True},
        )

        answer    = response.choices[0].message.content
        citations = _extract_citations(response)

        logger.info(f"Поиск: «{query[:50]}» → {len(answer)} символов, {len(citations)} источников")
        return {"answer": answer, "citations": citations, "error": None}

    except Exception as e:
        logger.error(f"search_web ошибка: {e}")
        return {"answer": "", "citations": [], "error": str(e)}


def format_search_result(result: dict) -> str:
    """Форматирует результат поиска красиво для Telegram."""
    if result.get("error"):
        return f"❌ *Ошибка поиска*\n\n{result['error']}"

    if not result.get("answer"):
        return "🔍 Поиск не дал результатов. Попробуй перефразировать запрос."

    clean = _clean_text(result["answer"])
    return _format_beautiful(clean, result.get("citations", []))


def format_for_tts(result: dict) -> str:
    """
    Готовит текст поиска для озвучки (TTS).
    Убирает всё лишнее, конвертирует финансовые обозначения в читаемый текст.
    """
    if result.get("error") or not result.get("answer"):
        return ""

    text = result["answer"]

    # Убираем citation-числа
    text = re.sub(r'(\w)\.\d{1,4}(?=[\s,\n]|$)', r'\1.', text)
    text = re.sub(r'\s+\d{1,4}(?=[\s\n]|$)', '', text)

    # Убираем markdown
    text = re.sub(r'^#{1,3}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'`+', '', text)

    # Убираем URLs
    text = re.sub(r'https?://\S+', '', text)

    # Конвертируем финансовые обозначения в читаемые
    # $73,000 → 73 тысячи долларов
    text = re.sub(r'\$(\d{1,3}),(\d{3})', lambda m: f"{m.group(1)} {m.group(2)} долларов", text)
    text = re.sub(r'\$(\d+)\s*трлн', lambda m: f"{m.group(1)} триллионов долларов", text)
    text = re.sub(r'\$(\d+[\.,]\d+)\s*трлн', lambda m: f"{m.group(1)} триллионов долларов", text)
    text = re.sub(r'\$(\d+)\s*млрд', lambda m: f"{m.group(1)} миллиардов долларов", text)
    text = re.sub(r'\$(\d+)', lambda m: f"{m.group(1)} долларов", text)

    # +X% → плюс X процентов
    text = re.sub(r'\+(\d+[\.,]\d+)%', lambda m: f"плюс {m.group(1).replace(',','.')} процента", text)
    text = re.sub(r'\+(\d+)%', lambda m: f"плюс {m.group(1)} процентов", text)
    # -X% → минус X процентов
    text = re.sub(r'−(\d+[\.,]\d+)%', lambda m: f"минус {m.group(1).replace(',','.')} процента", text)
    text = re.sub(r'-(\d+[\.,]\d+)%', lambda m: f"минус {m.group(1).replace(',','.')} процента", text)

    # Убираем лишние пустые строки
    text = re.sub(r'\n{2,}', ' ', text)
    text = re.sub(r'\s{2,}', ' ', text)

    return text.strip()

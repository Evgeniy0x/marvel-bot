"""
config.py — Все настройки Марвела
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ───────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USERS    = [
    int(x) for x in os.getenv("ALLOWED_TELEGRAM_USERS", "").split(",")
    if x.strip().isdigit()
]

# ── AI (OpenRouter) — чат, парсинг, намерения ──
OPENAI_API_KEY   = os.getenv("OPENROUTER_API_KEY", "")
OPENAI_BASE_URL  = "https://openrouter.ai/api/v1"
AI_MODEL         = "openai/gpt-4o"

# ── Whisper + TTS (прямой OpenAI) ─────────────
WHISPER_API_KEY  = os.getenv("OPENAI_WHISPER_KEY", "")
WHISPER_BASE_URL = "https://api.openai.com/v1"
WHISPER_ENABLED  = bool(WHISPER_API_KEY)

TTS_MODEL        = "tts-1"          # tts-1 быстрее, tts-1-hd качественнее
TTS_VOICE        = "nova"           # alloy / echo / fable / onyx / nova / shimmer
TTS_ENABLED      = bool(WHISPER_API_KEY)   # тот же ключ что и Whisper

# ── Perplexity — поиск в интернете ────────────
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
SEARCH_ENABLED     = bool(PERPLEXITY_API_KEY)

# ── Часовой пояс ──────────────────────────────
TIMEZONE         = os.getenv("TIMEZONE", "Europe/Moscow")

# ── База данных ───────────────────────────────
DB_PATH          = os.getenv("DB_PATH", "marvel.db")

# ── Утренний дайджест ─────────────────────────
MORNING_HOUR     = int(os.getenv("MORNING_HOUR", "8"))
MORNING_MINUTE   = int(os.getenv("MORNING_MINUTE", "0"))

# ── Things 3 ──────────────────────────────────────────
# URL Scheme (запись задач) — работает без токена
THINGS_ENABLED     = True
# Локальный REST API (чтение задач) — нужен токен
# Things 3 → Настройки → Основные → Things URLs → Управлять → Скопировать токен
THINGS_AUTH_TOKEN  = os.getenv("THINGS_AUTH_TOKEN", "")
THINGS_READ_ENABLED = bool(THINGS_AUTH_TOKEN)

# ── Крипто API (опциональные ключи — базовые функции работают без них) ──────
# CoinGecko Pro: https://www.coingecko.com/en/api — бесплатно до 10k запросов/мес
COINGECKO_API_KEY  = os.getenv("COINGECKO_API_KEY", "")
# CryptoPanic: https://cryptopanic.com/developers/api/ — крипто новости
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")
# Без ключей работают: CoinGecko free, DeFiLlama, Binance public, Fear&Greed
CRYPTO_ENABLED     = True   # всегда включено — базовые API бесплатны

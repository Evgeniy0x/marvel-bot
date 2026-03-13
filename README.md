# 🦁 Марвел — AI Telegram Bot

Персональный AI-ассистент для управления временем, задачами и крипто-рынком.

## ✨ Возможности

- **🗓 Things 3** — создаёт задачи и напоминания через URL Scheme
- **⏰ Напоминания** — разовые и повторяющиеся через Telegram
- **💪 Привычки** — трекинг ежедневных и еженедельных привычек
- **📝 Заметки** — быстрое сохранение идей
- **₿ Крипто** — цены, топ-10, Fear & Greed, DeFi TVL через CoinGecko / DeFiLlama
- **🔍 Поиск** — актуальные новости через Perplexity
- **🎙 Голос** — Whisper STT + OpenAI TTS
- **☀️ Утренний дайджест** — AI-брифинг в заданное время
- **📊 Аналитика** — еженедельный AI-обзор продуктивности

## 🛠 Стек

- **Python 3.10+** + `python-telegram-bot` v21+
- **OpenRouter** (GPT-4o) — AI-чат, парсинг намерений
- **OpenAI** — Whisper (STT) + TTS
- **SQLite** — локальное хранилище
- **APScheduler** — планировщик задач
- **Requests** — крипто API (CoinGecko, DeFiLlama, Binance, Alternative.me)

## 🚀 Установка

```bash
# 1. Клонируй репозиторий
git clone https://github.com/YOUR_USERNAME/marvel-bot.git
cd marvel-bot

# 2. Создай виртуальное окружение
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# 3. Установи зависимости
pip install -r requirements.txt

# 4. Настрой переменные окружения
cp .env.example .env
# Заполни .env своими ключами

# 5. Запусти бота
python main.py
```

## ⚙️ Настройка (.env)

Скопируй `.env.example` в `.env` и заполни:

```env
# Обязательные
TELEGRAM_BOT_TOKEN=your_bot_token
ALLOWED_TELEGRAM_USERS=123456789
OPENROUTER_API_KEY=your_openrouter_key

# Опциональные
OPENAI_WHISPER_KEY=your_openai_key  # для голоса
PERPLEXITY_API_KEY=your_perplexity_key  # для поиска
COINGECKO_API_KEY=your_coingecko_key   # Pro API

TIMEZONE=Europe/Moscow
MORNING_HOUR=8
MORNING_MINUTE=0
```

## 📡 Подключённые Крипто API

| API | Данные | Ключ |
|-----|--------|------|
| CoinGecko | Цены, топ-10, trending, global | Нет (free tier) |
| DeFiLlama | TVL протоколов, топ DeFi, сети | Нет |
| Binance | Realtime цены | Нет |
| Alternative.me | Fear & Greed Index | Нет |

## 📁 Структура

```
marvel-bot/
├── main.py              # Точка входа
├── bot.py               # Telegram хендлеры
├── ai_parser.py         # GPT-4o — парсинг намерений
├── config.py            # Настройки
├── crypto.py            # Крипто API + форматирование
├── database.py          # SQLite операции
├── scheduler.py         # Планировщик напоминаний
├── things_integration.py # Things 3 URL Scheme
├── tts.py               # Text-to-Speech
├── voice.py             # Обработка голосовых
├── search.py            # Perplexity поиск
├── analytics.py         # Статистика и отчёты
├── requirements.txt     # Зависимости
└── .env.example         # Шаблон конфига
```

## 📄 Лицензия

MIT

"""
crypto.py — Крипто и DeFi данные для Марвела.

Подключённые API (все бесплатные, без ключей):
  • CoinGecko      — цены, market cap, объёмы, trending coins
  • DeFiLlama      — TVL протоколов, топ DeFi, данные по сетям
  • Binance        — реалтайм цены и 24h изменения
  • Alternative.me — Индекс страха и жадности (Fear & Greed)
  • CoinPaprika    — дополнительные данные по монетам

Опционально (если задан ключ в .env):
  • CoinGecko Pro  — COINGECKO_API_KEY
  • CryptoPanic    — CRYPTOPANIC_API_KEY (крипто новости)
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Пул потоков для синхронных HTTP запросов (requests — не async)
_executor = ThreadPoolExecutor(max_workers=4)

# ── Базовые URL ───────────────────────────────────────────────────────────────

COINGECKO_URL   = "https://api.coingecko.com/api/v3"
DEFILLAMA_URL   = "https://api.llama.fi"
DEFI_COINS_URL  = "https://coins.llama.fi"
BINANCE_URL     = "https://api.binance.com/api/v3"
FEARGREED_URL   = "https://api.alternative.me/fng"
COINPAPRIKA_URL = "https://api.coinpaprika.com/v1"
CRYPTOPANIC_URL = "https://cryptopanic.com/api/v1"

# ── Маппинг популярных тикеров → CoinGecko ID ─────────────────────────────────

COIN_ID_MAP = {
    # Bitcoin и форки
    "btc": "bitcoin", "биткоин": "bitcoin", "bitcoin": "bitcoin",
    "bch": "bitcoin-cash",
    # Ethereum
    "eth": "ethereum", "эфир": "ethereum", "эфириум": "ethereum", "ethereum": "ethereum",
    "eth2": "ethereum",
    # Stablecoins
    "usdt": "tether", "тезер": "tether",
    "usdc": "usd-coin",
    "dai": "dai",
    "busd": "binance-usd",
    # Top L1
    "sol": "solana", "солана": "solana", "solana": "solana",
    "ada": "cardano", "кардано": "cardano",
    "dot": "polkadot", "полкадот": "polkadot",
    "avax": "avalanche-2", "лавина": "avalanche-2",
    "matic": "matic-network", "матик": "matic-network",
    "pol": "matic-network",
    "near": "near", "нир": "near",
    "atom": "cosmos", "космос": "cosmos",
    "icp": "internet-computer",
    "apt": "aptos",
    "sui": "sui",
    "sei": "sei-network",
    "ton": "the-open-network", "тон": "the-open-network",
    # BNB Chain
    "bnb": "binancecoin", "бнб": "binancecoin",
    # DeFi токены
    "uni": "uniswap", "uniswap": "uniswap",
    "aave": "aave",
    "link": "chainlink", "линк": "chainlink", "chainlink": "chainlink",
    "crv": "curve-dao-token", "curve": "curve-dao-token",
    "mkr": "maker", "maker": "maker",
    "snx": "havven",
    "comp": "compound-governance-token",
    "ldo": "lido-dao", "lido": "lido-dao",
    "arb": "arbitrum", "арбитрум": "arbitrum",
    "op": "optimism", "оптимизм": "optimism",
    "gmx": "gmx",
    "pendle": "pendle",
    "jup": "jupiter-ag",
    "jito": "jito-governance-token",
    # L2
    "zk": "zkync", "zksync": "zkync",
    "stx": "blockstack",
    # Meme
    "doge": "dogecoin", "догикоин": "dogecoin", "дог": "dogecoin",
    "shib": "shiba-inu", "шиба": "shiba-inu",
    "pepe": "pepe",
    "wif": "dogwifcoin",
    "bonk": "bonk",
    # Others
    "xrp": "ripple", "рипл": "ripple",
    "ltc": "litecoin", "лайткоин": "litecoin",
    "xlm": "stellar",
    "algo": "algorand",
    "vet": "vechain",
    "fil": "filecoin",
    "sand": "the-sandbox",
    "mana": "decentraland",
    "axs": "axie-infinity",
    "grt": "the-graph",
    "trx": "tron", "трон": "tron", "tron": "tron",
    "wbtc": "wrapped-bitcoin",
    "steth": "staked-ether",
    "hbar": "hedera-hashgraph",
    "mkr": "maker",
    "xmr": "monero", "монеро": "monero",
}

# ── Маппинг тикеров → Binance пары ────────────────────────────────────────────

BINANCE_PAIRS = {
    "bitcoin": "BTCUSDT", "ethereum": "ETHUSDT", "solana": "SOLUSDT",
    "binancecoin": "BNBUSDT", "ripple": "XRPUSDT", "cardano": "ADAUSDT",
    "dogecoin": "DOGEUSDT", "shiba-inu": "SHIBUSDT", "avalanche-2": "AVAXUSDT",
    "polkadot": "DOTUSDT", "matic-network": "MATICUSDT", "near": "NEARUSDT",
    "chainlink": "LINKUSDT", "uniswap": "UNIUSDT", "lido-dao": "LDOUSDT",
    "arbitrum": "ARBUSDT", "optimism": "OPUSDT", "the-open-network": "TONUSDT",
    "pepe": "PEPEUSDT", "sui": "SUIUSDT", "aptos": "APTUSDT",
    "cosmos": "ATOMUSDT", "curve-dao-token": "CRVUSDT", "aave": "AAVEUSDT",
}


# ── HTTP хелпер ───────────────────────────────────────────────────────────────

# Заголовки чтобы API не блокировал как бота
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _get_sync(url: str, params: dict = None, timeout: int = 20) -> Optional[dict | list]:
    """Синхронный GET-запрос через requests с User-Agent."""
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"HTTP {resp.status_code} для {url}: {resp.text[:200]}")
        return None
    except requests.Timeout:
        logger.error(f"Timeout ({timeout}s) для {url}")
        return None
    except Exception as e:
        logger.error(f"HTTP error {url}: {e}")
        return None


async def _get(url: str, params: dict = None, timeout: int = 20) -> Optional[dict | list]:
    """Async обёртка — используем get_running_loop() для Python 3.10+."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, lambda: _get_sync(url, params, timeout))


def _resolve_coin_id(query: str) -> str:
    """Преобразует тикер или название монеты в CoinGecko ID."""
    q = query.lower().strip()
    return COIN_ID_MAP.get(q, q)


# ── 1. CoinGecko — цена монеты ────────────────────────────────────────────────

async def get_coin_price(coin_query: str, currency: str = "usd") -> Optional[dict]:
    """
    Получает полные данные о монете: цена, изменение, объём, market cap.
    coin_query: тикер (btc, eth), русское название (биткоин) или CoinGecko ID
    """
    coin_id = _resolve_coin_id(coin_query)
    data = await _get(
        f"{COINGECKO_URL}/coins/markets",
        params={
            "vs_currency": currency,
            "ids": coin_id,
            "order": "market_cap_desc",
            "per_page": 1,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "1h,24h,7d"
        }
    )
    if data and len(data) > 0:
        return data[0]
    return None


# ── 2. CoinGecko — несколько монет сразу ─────────────────────────────────────

async def get_top_coins(limit: int = 10, currency: str = "usd") -> Optional[list]:
    """Возвращает топ N монет по капитализации."""
    return await _get(
        f"{COINGECKO_URL}/coins/markets",
        params={
            "vs_currency": currency,
            "order": "market_cap_desc",
            "per_page": limit,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h"
        }
    )


# ── 3. CoinGecko — трендовые монеты ──────────────────────────────────────────

async def get_trending_coins() -> Optional[dict]:
    """Возвращает топ-7 трендовых монет по поиску за последние 24 часа."""
    return await _get(f"{COINGECKO_URL}/search/trending")


# ── 4. CoinGecko — глобальная статистика рынка ───────────────────────────────

async def get_global_market() -> Optional[dict]:
    """Глобальные данные: total market cap, BTC dominance, 24h volume."""
    data = await _get(f"{COINGECKO_URL}/global")
    return data.get("data") if data else None


# ── 5. Binance — реалтайм цена ────────────────────────────────────────────────

async def get_binance_ticker(coin_id: str) -> Optional[dict]:
    """Получает 24h данные с Binance (быстро, реалтайм)."""
    pair = BINANCE_PAIRS.get(coin_id)
    if not pair:
        return None
    return await _get(f"{BINANCE_URL}/ticker/24hr", params={"symbol": pair})


# ── 6. DeFiLlama — топ протоколы по TVL ──────────────────────────────────────

async def get_defi_top_protocols(limit: int = 10) -> Optional[list]:
    """Топ DeFi протоколов по Total Value Locked. timeout=30s — ответ большой."""
    data = await _get(f"{DEFILLAMA_URL}/protocols", timeout=30)
    if not data or not isinstance(data, list):
        return None
    # Фильтруем нулевые TVL и сортируем
    valid = [p for p in data if isinstance(p.get("tvl"), (int, float)) and p["tvl"] > 0]
    sorted_data = sorted(valid, key=lambda x: x.get("tvl", 0), reverse=True)
    return sorted_data[:limit]


# ── 7. DeFiLlama — TVL конкретного протокола ─────────────────────────────────

async def get_protocol_tvl(protocol_name: str) -> Optional[dict]:
    """Данные TVL для конкретного DeFi протокола."""
    return await _get(f"{DEFILLAMA_URL}/protocol/{protocol_name.lower()}", timeout=20)


# ── 8. DeFiLlama — TVL по сетям (chains) ─────────────────────────────────────

async def get_chains_tvl() -> Optional[list]:
    """TVL по блокчейн-сетям: Ethereum, BSC, Solana, etc."""
    return await _get(f"{DEFILLAMA_URL}/v2/chains", timeout=20)


# ── 9. DeFiLlama — общий TVL DeFi рынка ─────────────────────────────────────

async def get_total_defi_tvl() -> Optional[dict]:
    """Суммарный TVL всего DeFi рынка."""
    return await _get(f"{DEFILLAMA_URL}/v2/historicalChainTvl")


# ── 10. Alternative.me — Fear & Greed Index ──────────────────────────────────

async def get_fear_greed() -> Optional[dict]:
    """Индекс страха и жадности крипторынка (0=max страх, 100=max жадность)."""
    data = await _get(FEARGREED_URL, params={"limit": 2, "format": "json"})
    if data and data.get("data"):
        return data["data"][0]
    return None


# ── 11. DeFiLlama — цены через coins API ─────────────────────────────────────

async def get_llama_prices(coins: list[str]) -> Optional[dict]:
    """
    Получает цены через DeFiLlama Coins API.
    coins: список в формате ["coingecko:bitcoin", "coingecko:ethereum"]
    """
    coins_str = ",".join(coins)
    return await _get(f"{DEFI_COINS_URL}/prices/current/{coins_str}")


# ── 12. CoinPaprika — обзор монеты ───────────────────────────────────────────

async def get_coinpaprika_coin(coin_query: str) -> Optional[dict]:
    """Дополнительные данные по монете через CoinPaprika."""
    # Для простоты маппим через популярные ID CoinPaprika
    paprika_map = {
        "bitcoin": "btc-bitcoin", "ethereum": "eth-ethereum",
        "solana": "sol-solana", "binancecoin": "bnb-binance-coin",
        "ripple": "xrp-xrp", "cardano": "ada-cardano",
        "dogecoin": "doge-dogecoin", "the-open-network": "ton-toncoin",
    }
    coin_id = _resolve_coin_id(coin_query)
    paprika_id = paprika_map.get(coin_id)
    if not paprika_id:
        return None
    return await _get(f"{COINPAPRIKA_URL}/coins/{paprika_id}")


# ── Форматирование ────────────────────────────────────────────────────────────

# Иконки для популярных монет
COIN_ICONS = {
    # Топ-10 по капитализации — всегда должны иметь иконку
    "bitcoin":          "₿",
    "ethereum":         "Ξ",
    "tether":           "💵",
    "binancecoin":      "🔶",
    "ripple":           "✕",
    "usd-coin":         "🔵",
    "solana":           "◎",
    "tron":             "🔴",
    "dogecoin":         "Ð",
    "cardano":          "₳",
    # Следующий уровень
    "shiba-inu":        "🐕",
    "avalanche-2":      "🔺",
    "matic-network":    "🟣",
    "the-open-network": "💎",
    "near":             "🌐",
    "cosmos":           "⚛️",
    "litecoin":         "Ł",
    "stellar":          "⭐",
    "monero":           "ɱ",
    "polkadot":         "⬤",
    # Wrapped / staked
    "wrapped-bitcoin":  "₿",
    "staked-ether":     "Ξ",
    "wrapped-ether":    "Ξ",
    "dai":              "◈",
    # DeFi токены
    "chainlink":        "🔗",
    "uniswap":          "🦄",
    "aave":             "👻",
    "lido-dao":         "🔷",
    "maker":            "🏭",
    "curve-dao-token":  "〰️",
    "compound-governance-token": "🏦",
    "havven":           "🌀",
    # L2 и мосты
    "arbitrum":         "🔵",
    "optimism":         "🔴",
    "aptos":            "🅐",
    "sui":              "💧",
    "internet-computer":"∞",
    # Meme coins
    "pepe":             "🐸",
    "dogwifcoin":       "🐶",
    "bonk":             "🦴",
}

# Числовые эмодзи для топ-10
NUM_EMOJI = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]

# Разделитель для красивого оформления
SEP = "─" * 22


def _fmt_price(price: float) -> str:
    """Форматирует цену с правильным количеством знаков."""
    if price >= 1000:
        return f"${price:,.0f}"
    elif price >= 1:
        return f"${price:,.2f}"
    elif price >= 0.01:
        return f"${price:.4f}"
    else:
        return f"${price:.8f}"


def _fmt_volume(vol: float) -> str:
    """Форматирует объём: $1.2B, $500M, $10K."""
    if vol >= 1_000_000_000_000:
        return f"${vol/1_000_000_000_000:.2f}T"
    elif vol >= 1_000_000_000:
        return f"${vol/1_000_000_000:.2f}B"
    elif vol >= 1_000_000:
        return f"${vol/1_000_000:.1f}M"
    elif vol >= 1_000:
        return f"${vol/1_000:.1f}K"
    return f"${vol:.0f}"


def _fmt_pct(pct: Optional[float], compact: bool = False) -> str:
    """Форматирует процент с цветной стрелкой."""
    if pct is None:
        return "—"
    icon = "🟢" if pct >= 0 else "🔴"
    sign = "+" if pct >= 0 else ""
    if compact:
        return f"{icon} {sign}{pct:.1f}%"
    return f"{icon} {sign}{pct:.2f}%"


def _fear_greed_label(value: int) -> tuple[str, str]:
    """Возвращает (эмодзи, метка) для индекса страха/жадности."""
    if value <= 20:   return "😱", "Экстремальный страх"
    elif value <= 40: return "😨", "Страх"
    elif value <= 60: return "😐", "Нейтрально"
    elif value <= 80: return "😏", "Жадность"
    else:             return "🤑", "Экстремальная жадность"


def _fear_greed_bar(value: int) -> str:
    """Визуальная шкала Fear & Greed из цветных блоков."""
    bars = []
    for i in range(10):
        threshold = (i + 1) * 10
        if value >= threshold - 5:
            if threshold <= 20: bars.append("🟥")
            elif threshold <= 40: bars.append("🟧")
            elif threshold <= 60: bars.append("🟨")
            elif threshold <= 80: bars.append("🟩")
            else: bars.append("💚")
        else:
            bars.append("⬜")
    return "".join(bars)


# ── Умное голосовое озвучивание ──────────────────────────────────────────────

def make_tts_voice(result_text: str, query_type: str = "general") -> str:
    """
    Преобразует крипто-ответ в естественную речь для TTS.
    Убирает markdown, таблицы, эмодзи — оставляет только цифры и факты.
    """
    import re

    # 1. Сначала заменяем числа с суффиксами ПЕРЕД удалением символов
    #    "$2.45B" → "2 целых 45 миллиарда долларов"
    text = re.sub(r"\$(\d+)[\.,](\d+)T", r"\1 целых \2 триллиона долларов", result_text)
    text = re.sub(r"\$(\d+)[\.,](\d+)B", r"\1 целых \2 миллиарда долларов", text)
    text = re.sub(r"\$(\d+)[\.,](\d+)M", r"\1 целых \2 миллиона долларов", text)
    text = re.sub(r"\$(\d+)[\.,](\d+)K", r"\1 целых \2 тысячи долларов", text)
    text = re.sub(r"\$(\d+)T", r"\1 триллионов долларов", text)
    text = re.sub(r"\$(\d+)B", r"\1 миллиардов долларов", text)
    text = re.sub(r"\$(\d+)M", r"\1 миллионов долларов", text)
    text = re.sub(r"\$(\d+)K", r"\1 тысяч долларов", text)
    # Оставшиеся цены: $85,432 → "85 432 долларов"
    text = re.sub(r"\$([\d,]+)", lambda m: m.group(1).replace(",", " ") + " долларов", text)

    # 2. Убираем markdown-разметку и спецсимволы
    text = re.sub(r"[*_`]", "", text)
    text = re.sub(r"─+", " ", text)

    # 3. Убираем все эмодзи (включая блочные квадраты шкалы)
    text = re.sub(r"[^\x00-\x7F\u0400-\u04FF\u0020-\u007E]", " ", text)

    # 4. Убираем технические строки
    for pattern in [r"Источник[^\n]*", r"CoinGecko[^\n]*", r"DeFiLlama[^\n]*",
                    r"Alternative\.me[^\n]*", r"\d{2}:\d{2} UTC", r"\d{2}\.\d{2}\.\d{4}"]:
        text = re.sub(pattern, "", text)

    # 5. Убираем лишние пробелы и чистим
    text = re.sub(r"\s+", " ", text).strip()
    return text[:700]


# ── Главная функция: умный ответ на крипто-запрос ────────────────────────────

async def handle_crypto_query(text: str) -> str:
    """
    Анализирует запрос и возвращает красиво отформатированный ответ.
    Автоматически определяет тип запроса:
      - конкретная монета → цена + данные
      - "топ монет" / "рынок" → топ 10
      - "defi" / "tvl" → DeFiLlama данные
      - "страх жадность" / "f&g" → Fear & Greed
      - "тренды" / "trending" → трендовые монеты
    """
    text_l = text.lower()

    # ── Fear & Greed ──────────────────────────────────────────────────────────
    if any(w in text_l for w in ["страх", "жадность", "fear", "greed", "f&g", "фнг"]):
        return await _format_fear_greed()

    # ── DeFi / TVL ────────────────────────────────────────────────────────────
    if any(w in text_l for w in ["defi", "дефи", "tvl", "тvl", "протокол", "ликвидность"]):
        # Проверяем конкретный протокол
        for proto in ["uniswap", "aave", "curve", "lido", "maker", "compound", "gmx", "pendle"]:
            if proto in text_l:
                return await _format_protocol_tvl(proto)
        # Иначе топ DeFi
        return await _format_defi_top()

    # ── Топ монет / рынок ─────────────────────────────────────────────────────
    if any(w in text_l for w in ["топ", "top", "рынок", "market", "все монеты", "обзор"]):
        return await _format_top_coins()

    # ── Глобальный рынок ──────────────────────────────────────────────────────
    if any(w in text_l for w in ["глобал", "global", "капитализация", "доминирование", "btc dom"]):
        return await _format_global_market()

    # ── Трендовые монеты ──────────────────────────────────────────────────────
    if any(w in text_l for w in ["тренд", "trend", "хайп", "популярн", "trending"]):
        return await _format_trending()

    # ── Конкретная монета ─────────────────────────────────────────────────────
    # Ищем известный тикер или название в тексте
    for key in COIN_ID_MAP:
        if key in text_l:
            coin_id = COIN_ID_MAP[key]
            return await _format_coin_price(coin_id)

    # ── Дефолт: топ-10 монет ─────────────────────────────────────────────────
    return await _format_top_coins()


# ── Форматировщики ────────────────────────────────────────────────────────────

async def _format_coin_price(coin_id: str) -> str:
    """Красивая карточка монеты — премиальный дизайн для мобильного Telegram."""
    try:
        cg = await get_coin_price(coin_id)
    except Exception as e:
        logger.error(f"get_coin_price error: {e}")
        cg = None
    try:
        fg = await get_fear_greed()
    except Exception as e:
        logger.error(f"get_fear_greed error: {e}")
        fg = None

    if not cg:
        return f"❌ Монета *{coin_id}* не найдена.\nПроверь тикер и попробуй снова."

    name    = cg.get("name", coin_id) or coin_id
    sym     = (cg.get("symbol") or "").upper().replace("_", "")
    icon    = COIN_ICONS.get(coin_id, "🪙")
    price   = cg.get("current_price") or 0
    cap     = cg.get("market_cap") or 0
    vol     = cg.get("total_volume") or 0
    rank    = cg.get("market_cap_rank") or "—"
    h1h     = cg.get("price_change_percentage_1h_in_currency")
    h24     = cg.get("price_change_percentage_24h")
    h7d     = cg.get("price_change_percentage_7d_in_currency")
    high24  = cg.get("high_24h") or 0
    low24   = cg.get("low_24h") or 0
    ath     = cg.get("ath") or 0
    ath_pct = cg.get("ath_change_percentage") or 0

    # Главная цена крупно
    lines = [
        f"{icon} *{name}* ({sym})",
        f"_#{rank} по капитализации_",
        f"",
        f"💵 *{_fmt_price(price)}*",
        f"",
        f"`{SEP}`",
        f"📊 *Динамика*",
        f"  1ч  →  {_fmt_pct(h1h)}",
        f"  24ч →  {_fmt_pct(h24)}",
        f"  7д  →  {_fmt_pct(h7d)}",
        f"",
        f"📈 *Диапазон 24ч*  {_fmt_price(low24)} — {_fmt_price(high24)}",
        f"",
        f"🏆 ATH: *{_fmt_price(ath)}*  _{abs(ath_pct):.1f}% {'ниже' if ath_pct < 0 else 'выше'}_",
        f"",
        f"`{SEP}`",
        f"💰 Капитализация: *{_fmt_volume(cap)}*",
        f"📦 Объём 24ч: {_fmt_volume(vol)}",
    ]

    if fg:
        val  = int(fg.get("value") or 50)
        e, l = _fear_greed_label(val)
        bar  = _fear_greed_bar(val)
        lines += [
            f"",
            f"`{SEP}`",
            f"🌡 *Fear & Greed Index*",
            f"{bar}",
            f"  {val}/100 — {e} {l}",
        ]

    lines.append(f"\n_Источник: CoinGecko · {datetime.utcnow().strftime('%H:%M UTC')}_")
    return "\n".join(lines)


async def _format_top_coins(limit: int = 10) -> str:
    """Топ-10 монет — чистый мобильный список с иконками и цветными индикаторами."""
    try:
        coins = await get_top_coins(limit)
    except Exception as e:
        logger.error(f"_format_top_coins error: {e}")
        return "❌ Не удалось получить данные рынка. Попробуй позже."

    if not coins:
        return "❌ Не удалось получить данные рынка."

    lines = [
        "🏆 *Топ-10 крипторынок*",
        f"_по капитализации · {datetime.utcnow().strftime('%H:%M UTC')}_",
        "",
    ]

    for i, c in enumerate(coins[:10]):
        coin_id = c.get("id") or ""
        # Экранируем _ чтобы не ломать Markdown v1 (FIGR_HELOC → FIGRHELOC)
        sym     = (c.get("symbol") or "").upper()[:8].replace("_", "")
        icon    = COIN_ICONS.get(coin_id, "●")
        price   = c.get("current_price") or 0
        h24     = c.get("price_change_percentage_24h")
        sign    = "+" if (h24 or 0) >= 0 else ""
        pct_str = f"{sign}{h24:.1f}%" if h24 is not None else "—"
        color   = "🟢" if (h24 or 0) >= 0 else "🔴"
        num     = NUM_EMOJI[i] if i < 10 else f"{i+1}."

        lines.append(f"{num} {icon} *{sym}* — {_fmt_price(price)}  {color} {pct_str}")

    lines.append(f"\n_CoinGecko · {datetime.utcnow().strftime('%H:%M UTC')}_")
    return "\n".join(lines)


async def _format_global_market() -> str:
    """Глобальная статистика рынка — премиальное оформление."""
    try:
        gm = await get_global_market()
    except Exception as e:
        logger.error(f"get_global_market error: {e}")
        gm = None
    try:
        fg = await get_fear_greed()
    except Exception as e:
        logger.error(f"get_fear_greed error: {e}")
        fg = None

    if not gm:
        return "❌ Не удалось получить глобальные данные."

    total_cap  = (gm.get("total_market_cap") or {}).get("usd") or 0
    total_vol  = (gm.get("total_volume") or {}).get("usd") or 0
    btc_dom    = (gm.get("market_cap_percentage") or {}).get("btc") or 0
    eth_dom    = (gm.get("market_cap_percentage") or {}).get("eth") or 0
    num_coins  = gm.get("active_cryptocurrencies") or 0
    cap_change = gm.get("market_cap_change_percentage_24h_usd") or 0

    lines = [
        "🌍 *Глобальный крипторынок*",
        f"_Обзор · {datetime.utcnow().strftime('%d.%m.%Y %H:%M UTC')}_",
        f"",
        f"`{SEP}`",
        f"💰 *Общая капитализация*",
        f"  {_fmt_volume(total_cap)}   {_fmt_pct(cap_change, compact=True)}",
        f"",
        f"📦 *Объём торгов 24ч*",
        f"  {_fmt_volume(total_vol)}",
        f"",
        f"`{SEP}`",
        f"👑 *Доминирование*",
        f"  ₿ Bitcoin:  {btc_dom:.1f}%",
        f"  Ξ Ethereum: {eth_dom:.1f}%",
        f"",
        f"🪙 Активных монет: *{num_coins:,}*",
    ]

    if fg:
        val  = int(fg.get("value") or 50)
        e, l = _fear_greed_label(val)
        bar  = _fear_greed_bar(val)
        lines += [
            f"",
            f"`{SEP}`",
            f"🌡 *Fear & Greed Index*",
            f"{bar}",
            f"  *{val}/100* — {e} {l}",
        ]

    lines.append(f"\n_CoinGecko + Alternative.me_")
    return "\n".join(lines)


async def _format_fear_greed() -> str:
    """Fear & Greed — красивый визуальный индекс."""
    try:
        fg = await get_fear_greed()
    except Exception as e:
        logger.error(f"_format_fear_greed error: {e}")
        return "❌ Не удалось получить индекс страха и жадности."

    if not fg:
        return "❌ Не удалось получить индекс страха и жадности."

    val  = int(fg.get("value") or 50)
    e, l = _fear_greed_label(val)
    bar  = _fear_greed_bar(val)

    lines = [
        "🌡 *Индекс Страха и Жадности*",
        f"_Fear & Greed Index · {datetime.utcnow().strftime('%d.%m.%Y %H:%M UTC')}_",
        f"",
        f"{bar}",
        f"",
        f"  {e} *{l}* — *{val} / 100*",
        f"",
        f"`{SEP}`",
        f"📖 *Шкала:*",
        f"  🟥 0–20   Экстремальный страх",
        f"  🟧 21–40  Страх",
        f"  🟨 41–60  Нейтрально",
        f"  🟩 61–80  Жадность",
        f"  💚 81–100 Экстремальная жадность",
        f"",
        f"_Страх = возможность покупки. Жадность = осторожность._",
        f"\n_Alternative.me · {datetime.utcnow().strftime('%H:%M UTC')}_",
    ]
    return "\n".join(lines)


async def _format_defi_top(limit: int = 10) -> str:
    """Топ DeFi протоколов — красивый список с TVL и сетями."""
    try:
        protocols = await get_defi_top_protocols(limit)
    except Exception as e:
        logger.error(f"get_defi_top_protocols error: {e}")
        protocols = None
    try:
        chains = await get_chains_tvl()
    except Exception as e:
        logger.error(f"get_chains_tvl error: {e}")
        chains = None

    if not protocols and not chains:
        return "❌ Не удалось получить DeFi данные. Попробуй позже."

    lines = [
        "🏦 *Топ DeFi протоколов*",
        f"_по TVL (Total Value Locked) · {datetime.utcnow().strftime('%H:%M UTC')}_",
        f"",
    ]

    if protocols:
        for i, p in enumerate(protocols[:10]):
            name     = (p.get("name") or "Unknown")[:20]
            tvl      = p.get("tvl") or 0
            change1d = p.get("change_1d")
            chain    = (p.get("chain") or "Multi")[:14]
            num      = NUM_EMOJI[i] if i < 10 else f"{i+1}."
            color    = "🟢" if (change1d or 0) >= 0 else "🔴"
            sign     = "+" if (change1d or 0) >= 0 else ""
            pct_str  = f"{color} {sign}{change1d:.1f}%" if change1d is not None else "—"

            # Одна строка на протокол — компактно для мобильного
            lines.append(f"{num} *{name}* — {_fmt_volume(tvl)}  {pct_str}")
            lines.append(f"   🔗 {chain}")
            lines.append("")
    else:
        lines.append("⚠️ Данные протоколов недоступны")

    if chains:
        sorted_chains = sorted(chains, key=lambda x: x.get("tvl") or 0, reverse=True)[:6]
        lines += [
            f"`{SEP}`",
            f"🔗 *Топ блокчейнов по TVL*",
            f"",
        ]
        chain_icons = {
            "Ethereum": "Ξ", "BSC": "🔶", "Solana": "◎", "Tron": "🔴",
            "Arbitrum": "🔵", "Base": "🔵", "Polygon": "🟣", "Avalanche": "🔺",
            "Optimism": "🔴", "Bitcoin": "₿",
        }
        for ch in sorted_chains:
            name = ch.get("name") or "Unknown"
            tvl  = ch.get("tvl") or 0
            ico  = chain_icons.get(name, "🔗")
            lines.append(f"  {ico} *{name}*: {_fmt_volume(tvl)}")

    lines.append(f"\n_Источник: DeFiLlama · {datetime.utcnow().strftime('%H:%M UTC')}_")
    return "\n".join(lines)


async def _format_protocol_tvl(protocol: str) -> str:
    """TVL данные конкретного протокола — детальная карточка."""
    try:
        data = await get_protocol_tvl(protocol)
    except Exception as e:
        logger.error(f"_format_protocol_tvl error: {e}")
        return f"❌ Ошибка получения данных для {protocol}."

    if not data:
        return f"❌ Протокол *{protocol}* не найден в DeFiLlama."

    name   = data.get("name") or protocol
    desc   = (data.get("description") or "")[:180]
    chains = (data.get("chains") or [])[:5]
    cat    = data.get("category") or ""

    tvl_data = data.get("tvl")
    if isinstance(tvl_data, list) and tvl_data:
        current_tvl = tvl_data[-1].get("totalLiquidityUSD") or 0
        prev_tvl    = tvl_data[-2].get("totalLiquidityUSD") or current_tvl if len(tvl_data) > 1 else current_tvl
        change      = ((current_tvl - prev_tvl) / prev_tvl * 100) if prev_tvl else 0
    elif isinstance(tvl_data, (int, float)):
        current_tvl, change = tvl_data, 0
    else:
        current_tvl, change = 0, 0

    lines = [
        f"🏦 *{name}*",
        f"_Категория: {cat}_" if cat else "",
        f"",
        f"`{SEP}`",
        f"💰 *TVL: {_fmt_volume(current_tvl)}*",
        f"📊 Изменение 24ч: {_fmt_pct(change)}",
    ]
    if chains:
        lines.append(f"🔗 Сети: {' · '.join(chains)}")
    if desc:
        lines += [f"", f"_{desc}_"]

    lines.append(f"\n_DeFiLlama · {datetime.utcnow().strftime('%H:%M UTC')}_")
    return "\n".join(filter(lambda x: x is not None, lines))


async def _format_trending() -> str:
    """Трендовые монеты — хайп-лист с ценами и изменениями."""
    try:
        data = await get_trending_coins()
    except Exception as e:
        logger.error(f"_format_trending error: {e}")
        return "❌ Не удалось получить трендовые монеты."

    if not data or "coins" not in data:
        return "❌ Не удалось получить трендовые монеты."

    lines = [
        "🔥 *Трендовые монеты*",
        f"_Топ поисков за 24ч · {datetime.utcnow().strftime('%H:%M UTC')}_",
        f"",
    ]

    for i, item in enumerate((data.get("coins") or [])[:7]):
        coin   = item.get("item") or {}
        # Экранируем _ чтобы не ломать Markdown v1
        name   = (coin.get("name") or "Unknown")[:16].replace("_", " ")
        symbol = (coin.get("symbol") or "").upper()[:8].replace("_", "")
        rank   = coin.get("market_cap_rank") or "—"
        price  = (coin.get("data") or {}).get("price") or 0
        pct_d  = (coin.get("data") or {}).get("price_change_percentage_24h") or {}
        pct    = pct_d.get("usd") if isinstance(pct_d, dict) else None
        color  = "🟢" if (pct or 0) >= 0 else "🔴"
        sign   = "+" if (pct or 0) >= 0 else ""
        p_str  = _fmt_price(float(price)) if price else "—"
        pct_str = f"{color} {sign}{pct:.1f}%" if pct is not None else "—"
        num    = NUM_EMOJI[i] if i < 7 else f"{i+1}."

        # Одна строка на монету — компактно, читабельно на мобильном
        lines.append(f"{num} *{name}* ({symbol}) — {p_str}  {pct_str}  _#{rank}_")

    lines.append(f"\n_CoinGecko · {datetime.utcnow().strftime('%H:%M UTC')}_")
    return "\n".join(lines)

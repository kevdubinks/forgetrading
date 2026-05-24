# binance_provider.py - Remplace CoinGecko par Binance (gratuit, 1200 req/min)
# FORGE Trading Agent Phase 3.1
import json, urllib.request
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from utils import setup_logging, load_settings

logger = setup_logging("binance")
UA = "TradingAgent/2.0"
BASE = "https://api.binance.com/api/v3"

# Symbol mapping
COIN_TO_SYMBOL = {
    "bitcoin": "BTCUSDT", "ethereum": "ETHUSDT", "solana": "SOLUSDT",
    "near": "NEARUSDT", "chainlink": "LINKUSDT", "polymath": "POLYUSDT"
}
SYMBOL_TO_COIN = {v: k for k, v in COIN_TO_SYMBOL.items()}

def get_all_tickers():
    """Get 24h price change for ALL USDT pairs in 1 API call."""
    try:
        url = f"{BASE}/ticker/24hr"
        r = urllib.request.Request(url, headers={"User-Agent": UA})
        data = json.loads(urllib.request.urlopen(r, timeout=15).read())
        return data
    except Exception as e:
        logger.error(f"Binance ticker error: {e}")
        return []

def get_prices_binance(coin_ids=None):
    """Get price and 24h change for tracked coins."""
    if coin_ids is None:
        settings = load_settings()
        coin_ids = settings.get("price_tracking", {}).get("coins", ["bitcoin", "ethereum"])

    tickers = get_all_tickers()
    if not tickers: return {}

    symbols_wanted = set()
    for cid in coin_ids:
        sym = COIN_TO_SYMBOL.get(cid)
        if sym: symbols_wanted.add(sym)

    result = {}
    for t in tickers:
        sym = t.get("symbol", "")
        if sym in symbols_wanted:
            coin_id = SYMBOL_TO_COIN.get(sym, sym)
            result[coin_id] = {
                "price": float(t.get("lastPrice", 0)),
                "change_24h": float(t.get("priceChangePercent", 0)),
                "volume_24h": float(t.get("quoteVolume", 0)),
                "high_24h": float(t.get("highPrice", 0)),
                "low_24h": float(t.get("lowPrice", 0))
            }

    logger.info(f"Binance: {len(result)} coins prices (1 call)")
    return result

def get_klines(symbol, interval="1d", limit=14):
    """Get OHLCV candles for RSI calculation."""
    try:
        url = f"{BASE}/klines?symbol={symbol}&interval={interval}&limit={limit}"
        r = urllib.request.Request(url, headers={"User-Agent": UA})
        data = json.loads(urllib.request.urlopen(r, timeout=10).read())
        closes = [float(k[4]) for k in data]
        return closes
    except Exception as e:
        logger.warning(f"Klines {symbol}: {e}")
        return []

def compute_rsi(prices, period=14):
    """Pure Python RSI, no dependency needed."""
    if len(prices) < period + 1: return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(diff if diff > 0 else 0)
        losses.append(abs(diff) if diff < 0 else 0)
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)

def get_rsi_all(coin_ids=None):
    """Get RSI for all tracked coins (1 call per coin = ~4-6 calls)."""
    if coin_ids is None:
        settings = load_settings()
        coin_ids = settings.get("price_tracking", {}).get("coins", ["bitcoin", "ethereum"])[:4]

    result = {}
    for cid in coin_ids:
        sym = COIN_TO_SYMBOL.get(cid)
        if not sym: continue
        closes = get_klines(sym, "1d", 15)
        if len(closes) >= 14:
            rsi = compute_rsi(closes, 14)
            result[cid] = {"rsi": rsi, "price": closes[-1]}
        else:
            result[cid] = {"rsi": None, "price": None}

    logger.info(f"Binance RSI: {len(result)} coins")
    return result

def get_btc_dominance_binance():
    """Approximate BTC dominance from BTC + top alts market cap * prices."""
    try:
        url = f"{BASE}/ticker/price"
        r = urllib.request.Request(url, headers={"User-Agent": UA})
        prices = json.loads(urllib.request.urlopen(r, timeout=10).read())
        price_map = {p["symbol"]: float(p["price"]) for p in prices}

        # Approx market caps (in crypto units * price)
        # These are rough estimates - update periodically
        approx_supply = {
            "BTCUSDT": 19_800_000, "ETHUSDT": 120_000_000,
            "BNBUSDT": 150_000_000, "SOLUSDT": 580_000_000,
            "XRPUSDT": 58_000_000_000, "ADAUSDT": 35_000_000_000,
            "DOGEUSDT": 148_000_000_000, "DOTUSDT": 1_500_000_000
        }

        total_mcap = 0
        btc_mcap = 0
        for sym, supply in approx_supply.items():
            price = price_map.get(sym, 0)
            mcap = supply * price
            total_mcap += mcap
            if sym == "BTCUSDT":
                btc_mcap = mcap

        if total_mcap > 0 and btc_mcap > 0:
            dom = (btc_mcap / total_mcap) * 100
            return round(dom, 1)
    except Exception as e:
        logger.warning(f"BTC.D calc error: {e}")
    return None

def get_enhanced_signals_binance(settings=None):
    """All signals from Binance + alternative.me (no CoinGecko)."""
    if settings is None: settings = load_settings()
    coins = settings.get("price_tracking", {}).get("coins", ["bitcoin", "ethereum"])

    # Fear & Greed (alternative.me - different API, no rate limit conflict)
    import urllib.request as ur
    fg = None
    try:
        r = ur.Request("https://api.alternative.me/fng/?limit=1", headers={"User-Agent": UA})
        d = json.loads(ur.urlopen(r, timeout=10).read())
        data = d.get("data", [])
        if data:
            fg = {"current": {"value": int(data[0]["value"]), "class": data[0]["value_classification"]}}
            logger.info(f"Fear/Greed: {fg['current']['value']} ({fg['current']['class']})")
    except Exception as e:
        logger.warning(f"FG error: {e}")

    # Prices (1 Binance call for ALL coins)
    prices = get_prices_binance(coins)

    # RSI (1 call per coin - Binance has 1200/min, no problem)
    rsi_data = get_rsi_all(coins)  # tous les coins trackes

    # BTC Dominance (computed from Binance prices)
    btc_dom = get_btc_dominance_binance()
    if btc_dom:
        logger.info(f"BTC Dominance: {btc_dom}%")

    # Volume ratio from price data
    cs = {}
    for c in coins:  # tous les coins trackes
        p = prices.get(c, {})
        r = rsi_data.get(c, {})
        vol24 = p.get("volume_24h", 0)
        cs[c] = {
            "rsi": r.get("rsi"),
            "price": p.get("price", r.get("price")),
            "vr": round(vol24 / 1e9, 2) if vol24 else None,  # in billions
            "change_24h": p.get("change_24h")
        }

    fg_val = fg["current"]["value"] if fg else "?"
    logger.info(f"Signals (Binance): FG={fg_val} BTC.D={btc_dom}% {len(cs)}coins")
    return {"fear_greed": fg, "btc_dominance": btc_dom, "coins": cs, "prices": prices}


if __name__ == "__main__":
    s = get_enhanced_signals_binance()
    D = chr(36)
    if s.get("fear_greed"):
        f = s["fear_greed"]["current"]
        print(f"Fear & Greed: {f['value']} ({f['class']})")
    print(f"BTC Dominance: {s.get('btc_dominance', '?')}%")
    print(f"\nCoins:")
    for c, cs in s.get("coins", {}).items():
        print(f"  {c:12s} RSI={cs.get('rsi', '?')} Price={D}{cs.get('price', '?'):,.2f} Chg={cs.get('change_24h', '?'):+.2f}% Vol={cs.get('vr', '?')}B")

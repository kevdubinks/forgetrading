# signals_enhanced.py - Fear/Greed, RSI, BTC Dominance, Volume Ratio
# FORGE Trading Agent Phase 3.1
import json, urllib.request, time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from utils import setup_logging, load_settings

logger = setup_logging("signals")
UA = "TradingAgent/2.0"

# === 1. Fear and Greed Index ===
def get_fear_greed():
    try:
        r = urllib.request.Request("https://api.alternative.me/fng/?limit=7", headers={"User-Agent": UA})
        d = json.loads(urllib.request.urlopen(r, timeout=10).read())
        data = d.get("data", [])
        if not data: return None
        cur = {"value": int(data[0]["value"]), "class": data[0]["value_classification"]}
        hist = [{"v": int(x["value"]), "ts": x["timestamp"]} for x in data]
        logger.info(f"Fear/Greed: {cur['value']} ({cur['class']})")
        return {"current": cur, "history": hist}
    except Exception as e:
        logger.warning(f"FG error: {e}")
        return None

# === 2. RSI Calculator (local) ===
def compute_rsi(prices, period=14):
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

def get_coin_rsi(coin_id):
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days=14"
        r = urllib.request.Request(url, headers={"User-Agent": UA})
        d = json.loads(urllib.request.urlopen(r, timeout=15).read())
        prices = [p[1] for p in d.get("prices", [])]
        if len(prices) < 14: return None
        rsi = compute_rsi(prices, 14)
        return {"price": prices[-1], "rsi": rsi}
    except Exception as e:
        logger.warning(f"RSI {coin_id}: {e}")
        return None

# === 3. BTC Dominance ===
def get_btc_dominance():
    try:
        r = urllib.request.Request("https://api.coingecko.com/api/v3/global", headers={"User-Agent": UA})
        d = json.loads(urllib.request.urlopen(r, timeout=10).read())
        dom = d.get("data", {}).get("market_cap_percentage", {}).get("btc", 0)
        logger.info(f"BTC Dominance: {dom:.1f}%")
        return round(dom, 1)
    except Exception as e:
        logger.warning(f"BTC.D error: {e}")
        return None

# === 4. Volume Ratio ===
def get_volume_ratio(coin_id):
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}?localization=false&tickers=false&community_data=false&developer_data=false"
        r = urllib.request.Request(url, headers={"User-Agent": UA})
        d = json.loads(urllib.request.urlopen(r, timeout=10).read())
        md = d.get("market_data", {})
        v24 = md.get("total_volume", {}).get("usd", 0) or 0
        mc = md.get("market_cap", {}).get("usd", 0) or 0
        ratio = (v24 / mc * 100) if mc > 0 else 0
        return {"vol24": v24, "ratio": round(ratio, 2)}
    except Exception as e:
        logger.warning(f"Vol {coin_id}: {e}")
        return None

# === 5. Combined Signals ===
def get_enhanced_signals(settings=None):
    if settings is None: settings = load_settings()
    coins = settings.get("price_tracking", {}).get("coins", ["bitcoin", "ethereum"])

    fg = get_fear_greed()
    btc_dom = get_btc_dominance()

    cs = {}
    for c in coins[:4]:
        time.sleep(1.5)  # Rate limit protection
        r = get_coin_rsi(c)
        v = get_volume_ratio(c)
        cs[c] = {"rsi": r["rsi"] if r else None, "price": r["price"] if r else None, "vr": v["ratio"] if v else None}

    fg_val = fg["current"]["value"] if fg else "?"
    logger.info(f"Signals: FG={fg_val} BTC.D={btc_dom}% {len(cs)}coins")
    return {"fear_greed": fg, "btc_dominance": btc_dom, "coins": cs}

if __name__ == "__main__":
    s = get_enhanced_signals()
    D = chr(36)
    if s.get("fear_greed"):
        f = s["fear_greed"]["current"]
        print(f"Fear & Greed: {f['value']} ({f['class']})")
    print(f"BTC Dominance: {s.get('btc_dominance', '?')}%")
    for c, cs in s.get("coins", {}).items():
        print(f"  {c:12s} RSI={cs.get('rsi', '?')} Vol={cs.get('vr', '?')}")

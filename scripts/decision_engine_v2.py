# decision_engine_v2.py - Matrice de confluence 4 criteres
# FORGE Trading Agent Phase 3.1
import json
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from utils import setup_logging, load_settings, load_json, save_json, DATA_DIR, now_iso
from binance_provider import get_enhanced_signals_binance as get_enhanced_signals

logger = setup_logging("decision_v2")
DECISION_LOG = DATA_DIR / "decisions_v2.json"
DOL = chr(36)

def score_fear_greed(fg_value):
    """Fear & Greed: <40 = opportunite, >75 = danger"""
    if fg_value is None: return 0
    if fg_value <= 25: return 25       # Extreme fear = max points
    elif fg_value <= 40: return 20     # Fear
    elif fg_value <= 60: return 10     # Neutral
    elif fg_value <= 75: return 5      # Greed
    else: return 0                      # Extreme greed = 0

def score_rsi(rsi):
    """RSI: 30-50 = zone d'achat, >70 = surchauffe"""
    if rsi is None: return 0
    if rsi < 20: return 25              # Extreme oversold
    elif rsi < 30: return 20            # Oversold
    elif rsi < 50: return 15            # Neutral-bearish
    elif rsi < 70: return 5             # Neutral-bullish
    else: return 0                       # Overbought

def score_btc_dominance(btc_dom):
    """BTC.D > 55% = alts sous-valorises, opportunite alts"""
    if btc_dom is None: return 0
    if btc_dom > 60: return 10          # Alt season signal
    elif btc_dom > 55: return 5
    elif btc_dom < 45: return -5        # BTC weak, caution
    return 0

def score_momentum(change_24h, rsi=None, vol_ratio=None):
    """Momentum + volume: surge avec volume = fort. Cap si RSI > 70 (surachat)."""
    if change_24h is None: return 0
    score = 0
    if change_24h > 10: score = 25
    elif change_24h > 5: score = 15
    elif change_24h > 2: score = 10
    elif change_24h < -10: score = 10   # Oversold bounce potential
    elif change_24h < -5: score = 5
    # Cap momentum if overbought: entering after surge = late
    if rsi and rsi > 70:
        score = score * 0.5
    return score

def generate_conviction_v2(articles, price_data, wallet_alerts, enhanced_signals, settings=None):
    """Matrice 4 criteres: Fear/Greed + RSI + BTC.D + Momentum"""
    fg = enhanced_signals.get("fear_greed", {})
    btc_dom = enhanced_signals.get("btc_dominance")
    coins = enhanced_signals.get("coins", {})

    fg_value = fg["current"]["value"] if fg else None
    fg_score = score_fear_greed(fg_value)

    # Aggregate RSI across tracked coins
    rsi_values = [cs["rsi"] for cs in coins.values() if cs.get("rsi")]
    avg_rsi = sum(rsi_values) / len(rsi_values) if rsi_values else None
    rsi_score = score_rsi(avg_rsi)

    btc_score = score_btc_dominance(btc_dom)

    # Momentum from price data
    momentum_score = 0
    surge_coins = []
    for a in price_data.get("alerts", []):
        coin_data = coins.get(a["coin"].lower(), {})
        vol_ratio = coin_data.get("vr")
        coin_rsi = coin_data.get("rsi")
        ms = score_momentum(a["change_24h"], coin_rsi, vol_ratio)
        momentum_score = max(momentum_score, ms)
        if ms >= 15:
            surge_coins.append({"coin": a["coin"], "change": a["change_24h"]})

    total = fg_score + rsi_score + btc_score + momentum_score
    reasons = []

    if fg_score >= 20:
        reasons.append(f"[SENTIMENT] Fear & Greed: {fg_value} ({fg.get('current',{}).get('class','?')})")
    if avg_rsi and avg_rsi < 40:
        reasons.append(f"[RSI] RSI moyen: {avg_rsi} (survente)")
    if btc_score >= 5:
        reasons.append(f"[MACRO] BTC Dominance: {btc_dom}%")
    for sc in surge_coins[:3]:
        reasons.append(f"[MOMENTUM] {sc['coin']}: {sc['change']:+.1f}%")

    if total >= 75:
        level = "STRONG"
        action = "CONSIDER_BUY"
    elif total >= 50:
        level = "MODERATE"
        action = "MONITOR_CLOSELY"
    elif total >= 30:
        level = "WEAK"
        action = "WATCH"
    else:
        level = "CALM"
        action = "HOLD"

    conviction = {
        "score": total,
        "level": level,
        "action": action,
        "components": {
            "sentiment": fg_score,
            "rsi": rsi_score,
            "btc_dominance": btc_score,
            "momentum": momentum_score
        },
        "details": {
            "fear_greed": fg_value,
            "avg_rsi": avg_rsi,
            "btc_dominance": btc_dom
        },
        "reasons": reasons,
        "surge_coins": surge_coins,
        "timestamp": now_iso()
    }

    logger.info(f"Conviction V2: {level} ({total}/100) FG={fg_score} RSI={rsi_score} BTC={btc_score} MOM={momentum_score}")
    return conviction

def get_decision_v2(articles, price_data, wallet_alerts, enhanced_signals, settings=None):
    conv = generate_conviction_v2(articles, price_data, wallet_alerts, enhanced_signals, settings)
    history = load_json(DECISION_LOG) or []
    history.append(conv)
    if len(history) > 90:
        history = history[-90:]
    save_json(DECISION_LOG, history)
    return conv

if __name__ == "__main__":
    from news_collector import collect_all_news
    from wallet_tracker import track_all_wallets
    from price_tracker import get_price_data

    s = load_settings()
    articles = collect_all_news(s)
    wallets = track_all_wallets(s)
    prices = get_price_data(s)
    signals = get_enhanced_signals(s)

    conv = get_decision_v2(articles, prices, wallets, signals, s)

    print(f"\n=== Decision Engine V2 ===")
    print(f"Conviction: {conv['level']} ({conv['score']}/100)")
    print(f"Action: {conv['action']}")
    print(f"\nBreakdown:")
    comp = conv["components"]
    print(f"  Sentiment (FG):  {comp['sentiment']}/25")
    print(f"  RSI:             {comp['rsi']}/25")
    print(f"  BTC Dominance:   {comp['btc_dominance']}/10")
    print(f"  Momentum:        {comp['momentum']}/25")
    print(f"\nDetails: {conv['details']}")
    print(f"\nSignaux:")
    for r in conv["reasons"]:
        print(f"  {r}")

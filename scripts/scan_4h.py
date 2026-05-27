# scan_4h.py — Scan d'entree toutes les 4 heures
# FORGE Trading Agent
# Lance par cron 6x/jour (00h, 4h, 8h, 12h, 16h, 20h Paris)
# Recalcule la matrice conviction sans executer de trades.
# Met a jour briefing_gerard.json pour Gerard.

import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import setup_logging, load_settings, save_json, load_json, DATA_DIR

logger = setup_logging("scan_4h")

def run_scan():
    """Recalcule le score de conviction et met a jour le briefing."""
    from decision_engine_v2 import get_decision_v2
    from binance_provider import get_enhanced_signals_binance, get_prices_binance

    settings = load_settings()
    enhanced_signals = get_enhanced_signals_binance(settings)

    # Construire price_data avec alerts
    prices = get_prices_binance()
    alerts = []
    for coin_id, data in prices.items():
        chg = data.get("change_24h", 0)
        if abs(chg) >= 5:
            alerts.append({
                "coin": coin_id.upper(),
                "change_24h": chg,
                "price": data.get("price"),
                "volume_24h": data.get("volume_24h")
            })
    price_data = {"alerts": alerts, "coins": prices}

    conviction = get_decision_v2([], price_data, [], enhanced_signals, settings)
    
    score = conviction.get("score", 0)
    level = conviction.get("level", "?")
    comp = conviction.get("components", {})
    
    logger.info(f"Scan 4h: {level} ({score}/100) FG={comp.get('sentiment')} RSI={comp.get('rsi')} BTC={comp.get('btc_dominance')} MOM={comp.get('momentum')}")

    # Mettre a jour le briefing Gerard avec la nouvelle conviction
    try:
        briefing = load_json(DATA_DIR / "briefing_gerard.json") or {}
        briefing["conviction"] = {
            "score": score,
            "level": level,
            "action": conviction.get("action", "?"),
            "components": comp,
            "details": conviction.get("details", {}),
            "reasons": conviction.get("reasons", [])[:5],
            "surge_coins": conviction.get("surge_coins", [])[:5],
            "last_scan": datetime.now(timezone.utc).isoformat()
        }
        save_json(DATA_DIR / "briefing_gerard.json", briefing)
    except Exception as e:
        logger.warning(f"Briefing update failed: {e}")

    # Alerter si STRONG
    if score >= 75:
        logger.warning(f"STRONG SIGNAL {level} ({score}/100) — ALERTE")
        try:
            from send_alert import send_alert
            send_alert(conviction, conviction.get("surge_coins", []))
        except Exception as e:
            logger.warning(f"Alert failed: {e}")

    return {"score": score, "level": level, "timestamp": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    r = run_scan()
    print(f"Scan 4h: {r['level']} ({r['score']}/100)")

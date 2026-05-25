# send_alert.py — Systeme d'alerte STRONG (conviction >= 75)
# FORGE Trading Agent
# Envoie une notification immediate quand un signal fort est detecte.
# Support: Discord webhook (si DISCORD_WEBHOOK_URL configure) + fichier local.

import sys, os, json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import setup_logging, DATA_DIR

logger = setup_logging("alerts")
ALERT_FILE = DATA_DIR / "last_alert.json"

# =====================================================================
# FORMATS
# =====================================================================

def _now():
    return datetime.now(timezone.utc).isoformat()

def format_webchat(conviction, surge_coins=None):
    """Format lisible pour webchat/telegram."""
    score = conviction.get("score", 0)
    level = conviction.get("level", "?")
    comps = conviction.get("components", {})
    reasons = conviction.get("reasons", [])
    details = conviction.get("details", {})

    lines = [
        f"SIGNAL FORT — {level} ({score}/100)",
        f"Action recommandee: {conviction.get('action', '?')}",
        "",
        f"Sentiment:  {comps.get('sentiment', 0)}/25 | FG={details.get('fear_greed', '?')}",
        f"RSI:        {comps.get('rsi', 0)}/25 | moy={details.get('avg_rsi', '?')}",
        f"BTC Domin:  {comps.get('btc_dominance', 0)}/10",
        f"Momentum:   {comps.get('momentum', 0)}/25",
        "",
    ]
    if reasons:
        lines.append("Signaux declencheurs:")
        for r in reasons[:5]:
            lines.append(f"  {r}")
    if surge_coins:
        lines.append(f"\nCoins en surge: {', '.join(c['coin'] for c in surge_coins[:3])}")

    return "\n".join(lines)


def send_discord(conviction, surge_coins=None):
    """Envoie un embed Discord colore."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        logger.info("Discord webhook non configure, skip")
        return None

    try:
        import requests
        score = conviction.get("score", 0)
        level = conviction.get("level", "?")
        comps = conviction.get("components", {})
        details = conviction.get("details", {})
        reasons = conviction.get("reasons", [])

        color = 0xFF0000 if score >= 85 else 0xFFA500  # rouge si >=85, orange si >=75

        fields = [
            {"name": "Conviction", "value": f"**{level}** ({score}/100)", "inline": True},
            {"name": "Sentiment", "value": f"FG={details.get('fear_greed','?')}\n{comps.get('sentiment',0)}/25", "inline": True},
            {"name": "RSI", "value": f"moy={details.get('avg_rsi','?')}\n{comps.get('rsi',0)}/25", "inline": True},
            {"name": "BTC Dominance", "value": f"{details.get('btc_dominance','?')}%\n{comps.get('btc_dominance',0)}/10", "inline": True},
            {"name": "Momentum", "value": f"{comps.get('momentum',0)}/25", "inline": True},
            {"name": "Action", "value": conviction.get("action", "?"), "inline": True},
        ]

        if surge_coins:
            fields.append({
                "name": "Surge Coins",
                "value": ", ".join(f"{c['coin']} ({c['change']:+.1f}%)" for c in surge_coins[:5]),
                "inline": False
            })

        embed = {
            "title": f"FORGE — SIGNAL FORT ({level})",
            "description": " ".join(reasons[:3]) if reasons else "Aucun detail",
            "color": color,
            "fields": fields,
            "footer": {"text": "Confirmation humaine requise avant execution"},
            "timestamp": _now()
        }

        resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
        if resp.status_code in (200, 204):
            logger.info("Discord alert envoyee")
            return {"status": "sent", "fields": len(fields)}
        logger.warning(f"Discord: HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"Discord send failed: {e}")
    return None


def save_alert_file(conviction, surge_coins=None):
    """Sauvegarde l'alerte dans last_alert.json (fallback)."""
    data = {
        "timestamp": _now(),
        "type": "STRONG_SIGNAL",
        "score": conviction.get("score", 0),
        "level": conviction.get("level", "?"),
        "action": conviction.get("action", "?"),
        "components": conviction.get("components", {}),
        "details": conviction.get("details", {}),
        "reasons": conviction.get("reasons", []),
        "surge_coins": surge_coins or []
    }
    ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"Alerte sauvegardee: {ALERT_FILE}")


# =====================================================================
# POINT D'ENTREE
# =====================================================================

def send_alert(conviction, surge_coins=None):
    """Envoie l'alerte STRONG via tous les canaux disponibles.
    Retourne un dict avec le statut de chaque canal."""
    score = conviction.get("score", 0)
    if score < 75:
        logger.info(f"Alerte ignoree: score {score} < 75")
        return {"sent": False, "reason": f"score {score} < 75"}

    level = conviction.get("level", "?")
    logger.info(f"ALERTE STRONG: {level} ({score}/100)")

    result = {"sent": True, "score": score, "level": level}

    # Canal 1: Discord
    result["discord"] = send_discord(conviction, surge_coins)

    # Canal 2: Fichier local (toujours)
    save_alert_file(conviction, surge_coins)
    result["file"] = str(ALERT_FILE)

    # Canal 3: Console (pour cron delivery webchat)
    msg = format_webchat(conviction, surge_coins)
    print("\n" + "=" * 50)
    print(msg)
    print("=" * 50 + "\n")

    return result


if __name__ == "__main__":
    # Test: envoyer une alerte factice
    test_conviction = {
        "score": 80,
        "level": "STRONG",
        "action": "CONSIDER_BUY",
        "components": {"sentiment": 25, "rsi": 20, "btc_dominance": 10, "momentum": 25},
        "details": {"fear_greed": 15, "avg_rsi": 28.5, "btc_dominance": 58},
        "reasons": ["Extreme Fear", "RSI survendu", "BTC.D > 55%", "ETH +8%"]
    }
    r = send_alert(test_conviction, [{"coin": "ETH", "change": 8.2}])
    print(json.dumps(r, indent=2, default=str))

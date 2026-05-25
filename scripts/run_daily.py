# run_daily.py — Pipeline quotidien FORGE
# Appele par Render Cron: python scripts/run_daily.py
# 14h30 Paris = 12h30 UTC (ete)
#
# Etapes:
#   1. Decision Engine V2 (score conviction + surge_coins)
#   1.5. STRONG Alert (si >= 75, envoi Discord + fichier + console)
#   2. Trade Executor (market buy + exit checks)
#   3. Report Generator (rapport Markdown)
#   4. Dashboard Generator (dashboard.html)
#   5. Telegram Notification (si TELEGRAM_BOT_TOKEN configure)

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

# === Paths ===
ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
sys.path.insert(0, str(SCRIPTS))

# === Logging ===
log_file = ROOT / "data" / "cron.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("forge-cron")


def _now_iso():
    """Timestamp ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def step(label, fn):
    """Execute une etape avec gestion d'erreur."""
    logger.info(f"=== STEP: {label} ===")
    try:
        result = fn()
        logger.info(f"=== {label}: OK ===")
        return result
    except Exception as e:
        logger.error(f"=== {label}: FAILED — {e} ===")
        return None


def run_decision():
    """Etape 1: Generer le score de conviction."""
    from decision_engine_v2 import get_decision_v2
    from binance_provider import get_enhanced_signals_binance, get_prices_binance
    from utils import load_settings

    settings = load_settings()
    enhanced_signals = get_enhanced_signals_binance(settings)

    # Construire price_data avec alerts (pour le scoring momentum)
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

    articles = []   # News non-critiques pour le score
    wallet_alerts = []  # Optionnel, couteux

    conviction = get_decision_v2(articles, price_data, wallet_alerts, enhanced_signals, settings)
    logger.info(f"Conviction: {conviction.get('level')} ({conviction.get('score')}/100)")
    return conviction


def run_trade_executor(conviction):
    """Etape 2: Executer les trades selon le score de la decision."""
    from trade_executor import execute_trades
    from utils import load_settings

    settings = load_settings()
    result = execute_trades(settings, conviction=conviction)

    logger.info(f"Trades: {result['action']} | New: {result['new_trades']} | "
                f"Exits: {result['triggered_exits']} | Open: {result['positions_open']}")

    summary = result.get("summary", {})
    logger.info(f"PnL: ${summary.get('cumulative_pnl', 0):+,.2f} | "
                f"WR: {summary.get('win_rate', 0):.1f}% | "
                f"R:R: {summary.get('r_r_ratio', 0):.2f}")
    return result


def run_report():
    """Etape 3: Generer le rapport Markdown quotidien."""
    from report_generator import generate_daily_report

    result = generate_daily_report()
    # generate_daily_report retourne (path, article_count, wallet_alert_count)
    report_path = result[0] if isinstance(result, tuple) else result
    if report_path:
        logger.info(f"Report: {report_path}")

        # Lire le contenu pour Telegram
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"path": str(report_path), "content": content}
    return None


def run_dashboard():
    """Etape 4: Generer le dashboard HTML."""
    from dashboard import generate_dashboard
    
    try:
        generate_dashboard()
        dash_path = ROOT / "dashboard.html"
        if dash_path.exists():
            logger.info(f"Dashboard: {dash_path} ({dash_path.stat().st_size:,} bytes)")
            return str(dash_path)
    except Exception as e:
        logger.error(f"Dashboard generation failed: {e}")
    return None


def run_notification(report_data, conviction, trade_result):
    """Etape 5: Envoyer resume Discord via webhook.
    Format: embed colore (vert=STRONG, orange=MODERATE, rouge=alertes)."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

    if not webhook_url:
        # Fallback: ecrire last_alert.json
        alert_file = DATA_DIR / "last_alert.json"
        alert_file.parent.mkdir(parents=True, exist_ok=True)
        with open(alert_file, "w", encoding="utf-8") as f:
            json.dump({"timestamp": _now_iso(), "status": "no_webhook"}, f)
        logger.info("Notification: no webhook configured — skipped")
        return None

    try:
        import requests

        score = conviction.get("score", 0) if conviction else 0
        level = conviction.get("level", "?") if conviction else "?"
        action = conviction.get("action", "?") if conviction else "?"
        trade_action = trade_result.get("action", "?") if trade_result else "?"
        summary = trade_result.get("summary", {}) if trade_result else {}
        pnl = summary.get("cumulative_pnl", 0)
        wr = summary.get("win_rate", 0)

        # Couleur embed
        if score >= 75:
            color = 0x00FF00  # vert
        elif score >= 50:
            color = 0xFFA500  # orange
        else:
            color = 0x808080  # gris

        # Champs
        fields = [
            {"name": "Conviction", "value": f"**{level}** ({score}/100)\n{action}", "inline": True},
            {"name": "Trades", "value": f"Action: **{trade_action}**\nNouveaux: {trade_result.get('new_trades', 0) if trade_result else 0}\nSorties: {trade_result.get('triggered_exits', 0) if trade_result else 0}", "inline": True},
            {"name": "Performance", "value": f"PnL: **${pnl:+,.2f}**\nWR: {wr:.1f}%\nR:R: {summary.get('r_r_ratio', 0):.2f}", "inline": True},
        ]

        # Alertes en footer
        alerts = []
        if score >= 85:
            alerts.append("SIGNAL FORT >= 85")
        if pnl < -10000:
            alerts.append(f"DRAWDOWN ${pnl:,.0f}")
        footer = " | ".join(alerts) if alerts else "Aucune alerte"

        embed = {
            "title": f"FORGE Rapport — {datetime.now().strftime('%d/%m/%Y')}",
            "description": f"Pipeline 14h30 terminé en {datetime.now().strftime('%H:%M')}",
            "color": color,
            "fields": fields,
            "footer": {"text": footer},
            "timestamp": _now_iso()
        }

        resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
        if resp.status_code in (200, 204):
            logger.info(f"Discord: embed sent ({len(fields)} fields, {len(alerts)} alerts)")
            return {"status": "sent", "fields": len(fields)}
        else:
            logger.warning(f"Discord: HTTP {resp.status_code} — {resp.text}")
    except Exception as e:
        logger.error(f"Discord send failed: {e}")
    return None


# =====================================================================
# MAIN
# =====================================================================

if __name__ == "__main__":
    start_time = datetime.now(timezone.utc)
    logger.info(f"===== FORGE DAILY PIPELINE START: {start_time.isoformat()} =====")

    # 1. Decision
    conviction = step("Decision Engine V2", run_decision)

    # 1.5. Alerte STRONG (avant execution, pour confirmation humaine)
    def _alert_if_strong():
        if not conviction:
            return None
        score = conviction.get("score", 0)
        if score >= 75:
            from send_alert import send_alert
            surge = conviction.get("surge_coins", [])
            return send_alert(conviction, surge)
        logger.info(f"No STRONG alert (score={score})")
        return None
    step("STRONG Alert Check", _alert_if_strong)

    # 2. Trade Executor (passe la conviction directement, pas de re-lecture fichier)
    trade_result = step("Trade Executor", lambda: run_trade_executor(conviction))

    # 3. Report
    report_data = step("Report Generator", run_report)

    # 4. Dashboard
    step("Dashboard Generator", run_dashboard)

    # 5. Notification (Discord + Gerard briefing)
    step("Notification", lambda: run_notification(report_data, conviction, trade_result))

    # 6. Briefing Gerard (donnees structurees pour l'Agent Finance)
    def _brief_gerard():
        from briefing_gerard import build_briefing
        return build_briefing(conviction, trade_result, report_data)
    step("Gerard Briefing", _brief_gerard)

    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    logger.info(f"===== FORGE DAILY PIPELINE END: {duration:.1f}s =====")

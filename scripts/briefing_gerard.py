# briefing_gerard.py — Briefing quotidien pour Gerard (Agent Finance)
# FORGE Trading Agent
# Lance apres le pipeline quotidien. Prepare un resume structure
# que Gerard peut analyser a chaque cycle.

import sys, json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import setup_logging, load_json, save_json, DATA_DIR, now_iso

logger = setup_logging("briefing_gerard")
BRIEFING_FILE = DATA_DIR / "briefing_gerard.json"

def build_briefing(conviction=None, trade_result=None, report_data=None):
    """
    Construit le briefing quotidien pour Gerard.
    Inclut: conviction, prix, trades, perfs, signaux.
    """
    briefing = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "timestamp": now_iso(),
        "generated_by": "pipeline_14h30"
    }

    # 1. Conviction
    if conviction:
        briefing["conviction"] = {
            "score": conviction.get("score", 0),
            "level": conviction.get("level", "?"),
            "action": conviction.get("action", "?"),
            "components": conviction.get("components", {}),
            "details": conviction.get("details", {}),
            "reasons": conviction.get("reasons", [])[:5],
            "surge_coins": conviction.get("surge_coins", [])[:5]
        }

    # 2. Trades
    if trade_result:
        summary = trade_result.get("summary", {})
        briefing["trades"] = {
            "action": trade_result.get("action", "?"),
            "new_trades": trade_result.get("new_trades", 0),
            "triggered_exits": trade_result.get("triggered_exits", 0),
            "positions_open": trade_result.get("positions_open", 0),
            "performance": {
                "cumulative_pnl": summary.get("cumulative_pnl", 0),
                "win_rate": summary.get("win_rate", 0),
                "r_r_ratio": summary.get("r_r_ratio", 0),
                "avg_win": summary.get("avg_win", 0),
                "avg_loss": summary.get("avg_loss", 0),
                "total_trades": summary.get("total_trades", 0),
                "expected_value": summary.get("expected_value", 0)
            }
        }

    # 3. Positions ouvertes
    try:
        pos_file = DATA_DIR / "open_positions.json"
        if pos_file.exists():
            with open(pos_file, "r") as f:
                positions = json.load(f)
            briefing["open_positions"] = []
            for p in positions:
                if p.get("status") == "OPEN":
                    briefing["open_positions"].append({
                        "coin": p.get("coin"),
                        "entry": p.get("entry_price"),
                        "qty": p.get("quantity"),
                        "value": p.get("position_value_usd"),
                        "tp": p.get("tp_price"),
                        "sl": p.get("sl_price"),
                        "score": p.get("conviction_score"),
                        "since": p.get("entry_time")
                    })
    except Exception as e:
        logger.warning(f"Open positions read error: {e}")
        briefing["open_positions"] = []

    # 4. Dernieres decisions
    try:
        decisions = load_json(DATA_DIR / "decisions_v2.json") or []
        briefing["last_decisions"] = decisions[-5:] if decisions else []
    except Exception:
        briefing["last_decisions"] = []

    # Sauvegarder
    BRIEFING_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BRIEFING_FILE, "w", encoding="utf-8") as f:
        json.dump(briefing, f, indent=2, ensure_ascii=False, default=str)

    logger.info(f"Briefing Gerard sauvegarde: {BRIEFING_FILE} ({len(json.dumps(briefing))} bytes)")
    return briefing


if __name__ == "__main__":
    # Test standalone
    r = build_briefing()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str)[:500])

# check_positions.py — Verification horaire TP/SL
# FORGE Trading Agent
# Lance par cron toutes les heures. Verifie les positions ouvertes
# contre les prix Binance en temps reel. Ferme si TP ou SL touche.
# Independance: peut tourner sans le pipeline quotidien.

import sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import setup_logging

logger = setup_logging("check_positions")

# === Charger les modules trading uniquement si necessaire ===

def run_check():
    """Point d'entree principal. Verifie les positions et ferme si TP/SL touche."""
    
    # Eviter les imports couteux au demarrage
    from trade_executor import _check_existing_positions
    from utils import load_settings

    settings = load_settings()
    
    logger.info("Check TP/SL horaire...")
    open_positions, triggered = _check_existing_positions(settings)
    
    if not open_positions and not triggered:
        logger.info("Aucune position ouverte, rien a verifier.")
        return {"positions_checked": 0, "exits": 0}

    result = {
        "positions_checked": len(open_positions) + len(triggered),
        "positions_open": len(open_positions),
        "exits": len(triggered),
        "details": []
    }

    for t in triggered:
        detail = {
            "coin": t.get("coin"),
            "reason": t.get("exit_reason"),
            "pnl": t.get("pnl"),
            "pnl_pct": t.get("pnl_pct")
        }
        result["details"].append(detail)
        logger.info(
            f"  SORTIE: {detail['coin']} {detail['reason']} "
            f"PnL: ${detail['pnl']:+,.2f} ({detail['pnl_pct']:+.2f}%)"
        )

    if not triggered:
        logger.info(f"  {len(open_positions)} position(s) ouverte(s), pas de TP/SL touche.")

    return result


if __name__ == "__main__":
    r = run_check()
    print(f"\nCheck TP/SL termine: {r['positions_checked']} positions, {r['exits']} sorties")

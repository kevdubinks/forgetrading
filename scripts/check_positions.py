# check_positions.py — Verification horaire TP/SL + Correlation + Stop mental
# FORGE Trading Agent
# Lance par cron toutes les heures. Verifie:
#   - TP/SL: ferme si prix atteint
#   - Stop mental -15%: alerte si drawdown severe
#   - Correlation ETH/SOL: alerte si beta > 0.95 + positions simultanees

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

    # Stop mental -15%: alerter si une position est en drawdown severe
    for pos in open_positions:
        if pos.get("status") != "OPEN":
            continue
        entry = pos.get("entry_price", 0)
        coin = pos.get("coin", "?")
        if entry <= 0:
            continue
        # Recuperer le prix actuel
        from binance_provider import get_prices_binance
        prices = get_prices_binance()
        current = prices.get(coin, {}).get("price", 0)
        if current <= 0:
            continue
        pnl_pct = ((current - entry) / entry) * 100
        if pnl_pct <= -15:
            logger.warning(
                f"STOP MENTAL -15%: {coin} est a {pnl_pct:.1f}% "
                f"(entry=${entry:.2f}, now=${current:.2f}). "
                f"Coupure manuelle recommandee."
            )
            result["intraday_warnings"] = result.get("intraday_warnings", []) + [{
                "coin": coin, "pnl_pct": round(pnl_pct, 1),
                "entry": entry, "current": current
            }]

    # Alerte correlation: beta ETH/SOL > 0.95 + positions ETH+SOL ouvertes
    try:
        open_coins = [p.get("coin", "") for p in open_positions if p.get("status") == "OPEN"]
        if "ethereum" in open_coins and "solana" in open_coins:
            from binance_provider import get_correlation_signals
            corr = get_correlation_signals()
            eth_sol = corr.get("ETH_SOL", {})
            beta = eth_sol.get("beta_30j", 0)
            if beta > 0.95:
                logger.warning(
                    f"CORRELATION RISK: beta ETH/SOL={beta:.3f} > 0.95. "
                    f"Positions ETH+SOL ouvertes simultanement. "
                    f"Gerard recommande: exposition combinee <= 150% sizing normal."
                )
                result["correlation_warnings"] = result.get("correlation_warnings", []) + [{
                    "pair": "ETH_SOL",
                    "beta_30j": round(beta, 3),
                    "threshold": 0.95,
                    "action": "reduire exposition combinee"
                }]
    except Exception as e:
        logger.warning(f"Correlation check failed: {e}")

    return result


if __name__ == "__main__":
    r = run_check()
    print(f"\nCheck TP/SL termine: {r['positions_checked']} positions, {r['exits']} sorties")

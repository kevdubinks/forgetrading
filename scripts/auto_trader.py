# auto_trader.py - Module 1+2: Auto-trader dry-run + Trade Journal
# FORGE Trading Agent Phase 4 | Dry-run 22 mai → 5 juin 2026
import json, os, sys
from datetime import datetime, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils import setup_logging, load_settings, load_json, save_json, DATA_DIR, now_iso

logger = setup_logging("auto_trader")
DOL = chr(36)

TRADE_JOURNAL = DATA_DIR / "trades" / "journal.json"
DRY_RUN_END = "2026-06-05"
TRADING_HOURS_START = time(8, 0)
TRADING_HOURS_END = time(22, 0)

# === Garde-fous ===
MAX_POSITIONS = 3
MAX_SIZE_PCT = 5
STOP_LOSS_PCT = 0.95
TAKE_PROFIT_PCT = 1.10
ALERT_CONVICTION = 85
ALERT_SIZE = 8000
MAX_DRAWDOWN_PCT = -15

def load_journal():
    return load_json(TRADE_JOURNAL) or []

def save_journal(journal):
    Path(TRADE_JOURNAL).parent.mkdir(parents=True, exist_ok=True)
    save_json(TRADE_JOURNAL, journal)

def get_open_positions():
    journal = load_journal()
    return [t for t in journal if t.get("outcome") is None]

def get_next_trade_id():
    journal = load_journal()
    return f"trade_{len(journal)+1:04d}"

def is_trading_hours():
    now = datetime.now().time()
    return TRADING_HOURS_START <= now <= TRADING_HOURS_END

def get_portfolio_value(alpaca_data):
    if alpaca_data and alpaca_data.get("account"):
        return alpaca_data["account"]["portfolio_value"]
    return 100000

def compute_simulated_drawdown(journal, portfolio_value):
    total_pnl = sum(t.get("pnl", 0) or 0 for t in journal if t.get("pnl") is not None)
    if portfolio_value + total_pnl > 0:
        return (total_pnl / (portfolio_value + total_pnl)) * 100
    return 0

def generate_flags(conviction, signals, price_data):
    """Determine structured flags from trade context."""
    flags = []
    avg_rsi = conviction.get("details", {}).get("avg_rsi", 50)
    btc_dom = conviction.get("details", {}).get("btc_dominance", 50) or 50
    fg = conviction.get("details", {}).get("fear_greed", 50) or 50
    momentum = conviction.get("components", {}).get("momentum", 0)
    
    if avg_rsi and avg_rsi > 70:
        flags.append("rsi_overbought_entry")
    elif avg_rsi and avg_rsi < 30:
        flags.append("rsi_oversold_entry")
    if btc_dom and btc_dom > 72:
        flags.append("high_btc_dominance")
    if fg and fg < 25:
        flags.append("low_fear_greed")
    if momentum and momentum > 15:
        flags.append("strong_momentum_late")
    if not flags:
        flags.append("no_flag")
    return flags

def execute_dry_run_trade(asset, entry_price, conviction, signals_data, alpaca_data, settings=None):
    """Module 1: Simulate a trade. Returns log entry."""
    journal = load_journal()
    portfolio = get_portfolio_value(alpaca_data)
    score = conviction.get("score", 0)
    level = conviction.get("level", "CALM")
    
    # Check conviction threshold
    if score < 50:
        logger.info(f"[SKIP] Conviction {score} < 50 for {asset}")
        return None
    
    # Check position limits
    open_positions = [t for t in journal if t.get("outcome") is None]
    if len(open_positions) >= MAX_POSITIONS:
        logger.info(f"[SKIP] Max {MAX_POSITIONS} positions ({len(open_positions)} open)")
        return None
    
    # Check already holding this asset
    if any(t["asset"] == asset for t in open_positions):
        logger.info(f"[SKIP] Already holding {asset}")
        return None
    
    # Check trading hours
    if not is_trading_hours():
        logger.info(f"[SKIP] Outside trading hours (08:00-22:00)")
        return None
    
    # Calculate position size
    size_pct = MAX_SIZE_PCT
    if score >= 75:
        size_pct = min(MAX_SIZE_PCT, MAX_SIZE_PCT * (score / 75))
    size = round(portfolio * (size_pct / 100), 2)
    
    # Guardrails (alert, don't block during dry-run)
    guardrails = []
    if score >= ALERT_CONVICTION and size > ALERT_SIZE:
        guardrails.append("ALERTE CRITIQUE: conviction >= 85 + taille > $8000")
    drawdown = compute_simulated_drawdown(journal, portfolio)
    if drawdown <= MAX_DRAWDOWN_PCT:
        guardrails.append(f"STOP SYSTEME: drawdown {drawdown:.1f}%")
    previously_traded = [t for t in journal if t["asset"] == asset]
    if not previously_traded:
        guardrails.append("AVERTISSEMENT: nouvel actif sans historique")
    
    if guardrails:
        logger.warning(f"[GARDE-FOU] {asset}: {' | '.join(guardrails)}")
    
    # Build trade entry
    trade_id = get_next_trade_id()
    flags = generate_flags(conviction, signals_data, {})
    
    trade = {
        "id": trade_id,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "asset": asset,
        "entry": round(entry_price, 4),
        "stop_loss": round(entry_price * STOP_LOSS_PCT, 4),
        "take_profit": round(entry_price * TAKE_PROFIT_PCT, 4),
        "size_usd": size,
        "conviction_score": score,
        "conviction_level": level,
        "signals": {
            "fear_greed": conviction.get("details", {}).get("fear_greed"),
            "rsi": conviction.get("details", {}).get("avg_rsi"),
            "btc_dom": conviction.get("details", {}).get("btc_dominance"),
            "momentum": conviction.get("components", {}).get("momentum")
        },
        "flags": flags,
        "guardrails": guardrails,
        "exit_price": None,
        "exit_date": None,
        "pnl": None,
        "outcome": None,
        "lesson": None,
        "status": "DRY_RUN"
    }
    
    journal.append(trade)
    save_journal(journal)
    
    # Log dry-run
    flag_str = f"[STRONG]" if score >= 75 else ""
    sl = trade["stop_loss"]
    tp = trade["take_profit"]
    logger.info(f"[DRY-RUN] {flag_str} BUY {asset} {DOL}{entry_price} | size {DOL}{size} | SL {DOL}{sl} | TP {DOL}{tp} | conviction {score}")
    logger.info(f"[DRY-RUN] Ordre NON envoye - phase test jusqu'au {DRY_RUN_END}")
    
    return trade

def auto_trade_from_conviction(conviction, price_data, signals_data, alpaca_data, settings=None):
    """Main entry point: check conviction and execute dry-run trades."""
    if settings is None:
        settings = load_settings()
    
    score = conviction.get("score", 0)
    level = conviction.get("level", "CALM")
    
    # Find best asset from surge coins
    surge_coins = conviction.get("surge_coins", [])
    if not surge_coins:
        logger.info("[AUTO-TRADER] No surge coins, no trade")
        return None
    
    # Execute trade on highest conviction surge coin
    best = surge_coins[0]
    asset = best["coin"].upper()
    entry_price = signals_data.get("coins", {}).get(best["coin"].lower(), {}).get("price")
    if not entry_price:
        # Fallback to price data
        for a in price_data.get("alerts", []):
            if a["coin"] == best["coin"]:
                entry_price = a["price"]
                break
    
    if not entry_price:
        logger.warning(f"[AUTO-TRADER] No price for {asset}")
        return None
    
    return execute_dry_run_trade(asset, entry_price, conviction, signals_data, alpaca_data, settings)

def get_dry_run_summary(journal=None):
    """Module 2 helper: compute dry-run statistics."""
    if journal is None:
        journal = load_journal()
    
    if not journal:
        return {"total": 0, "pnl_total": 0, "win_rate": 0, "best_asset": None, "avg_conviction": 0}
    
    simulated = journal  # All are simulated during dry-run
    closed = [t for t in simulated if t.get("outcome") is not None]
    wins = [t for t in closed if t.get("outcome") == "WIN"]
    
    pnl_total = sum(t.get("pnl", 0) or 0 for t in closed)
    wr = (len(wins) / len(closed) * 100) if closed else 0
    avg_conv = sum(t["conviction_score"] for t in simulated) / len(simulated) if simulated else 0
    
    # Best asset by PnL
    asset_pnl = {}
    for t in closed:
        asset_pnl[t["asset"]] = asset_pnl.get(t["asset"], 0) + (t.get("pnl", 0) or 0)
    best_asset = max(asset_pnl, key=asset_pnl.get) if asset_pnl else None
    
    return {
        "total": len(simulated),
        "closed": len(closed),
        "open": len(simulated) - len(closed),
        "pnl_total": round(pnl_total, 2),
        "win_rate": round(wr, 1),
        "best_asset": best_asset,
        "avg_conviction": round(avg_conv, 1),
        "day_count": len(set(t["date"] for t in simulated))
    }

def generate_daily_dryrun_block(journal=None):
    """Generate the daily dry-run block for the report."""
    if journal is None:
        journal = load_journal()
    
    summary = get_dry_run_summary(journal)
    today = datetime.now().strftime("%Y-%m-%d")
    today_trades = [t for t in journal if t["date"] == today]
    start_date = journal[0]["date"] if journal else today
    day_count = summary.get("day_count", 0) or 1
    
    lines = []
    lines.append(f"## DRY-RUN (J+{day_count} / J+14)")
    lines.append(f"Trades simules aujourd'hui : {len(today_trades)}")
    lines.append(f"Trades cumules : {summary['total']}")
    lines.append(f"PnL simule cumule : {DOL}{summary['pnl_total']:+,.2f}")
    lines.append(f"Meilleur actif : {summary['best_asset'] or 'N/A'}")
    lines.append(f"Conviction moyenne : {summary['avg_conviction']}/100")
    lines.append(f"Taux WIN simule : {summary['win_rate']}%")
    
    # List today's trades
    if today_trades:
        lines.append("")
        for t in today_trades:
            flag = "STRONG" if t["conviction_score"] >= 75 else ""
            lines.append(f"- [DRY-RUN] {flag} {t['asset']} @ {DOL}{t['entry']} | size {DOL}{t['size_usd']} | SL {DOL}{t['stop_loss']} | TP {DOL}{t['take_profit']}")
    
    return "\n".join(lines)

if __name__ == "__main__":
    # Test: show journal and dry-run block
    journal = load_journal()
    if journal:
        print(f"Journal: {len(journal)} trades")
        print(f"Open: {len([t for t in journal if t.get('outcome') is None])}")
        print(f"Closed: {len([t for t in journal if t.get('outcome') is not None])}")
    else:
        print("Journal empty - no trades yet")
    
    print()
    print(generate_daily_dryrun_block(journal))

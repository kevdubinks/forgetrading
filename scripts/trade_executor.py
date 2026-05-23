# trade_executor.py — Execution paper trading Alpaca + gestion positions
# ⚙️ FORGE | Projet: Trading Agent Phase 4 — Mode B (full paper auto)
# Seuils: >= 50 MODERATE (3% portfolio), >= 75 STRONG (5% portfolio)
# Stop-loss: -10%, Take-profit: +20%
# Met a jour trade_history.json + dry_run_summary.json a chaque execution

import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils import setup_logging, load_settings, load_json, save_json, DATA_DIR, now_iso
from binance_provider import get_prices_binance
from alpaca_tracker import get_alpaca_client

logger = setup_logging("trade_executor")

# === Fichiers de donnees ===
TRADE_HISTORY = DATA_DIR / "trade_history.json"
OPEN_POSITIONS = DATA_DIR / "open_positions.json"
DRY_RUN_SUMMARY = DATA_DIR / "dry_run_summary.json"
DECISION_LOG = DATA_DIR / "decisions_v2.json"

# === Configuration trading ===
MAX_POSITIONS = 3         # Max positions simultanees
STOP_LOSS_PCT = -0.10     # -10%
TAKE_PROFIT_PCT = 0.20    # +20%
MIN_CONVICTION = 50       # Seuil minimum pour trader

# Symbol mapping coin_id -> Alpaca symbol
COIN_TO_ALPACA = {
    "bitcoin":   "BTC/USD",
    "ethereum":  "ETH/USD",
    "solana":    "SOL/USD",
    "near":      "NEAR/USD",
    "chainlink": "LINK/USD",
    "polymath":  "POLY/USD"
}

# === 1. GESTION DES RISQUES ===

def calculate_position_size(portfolio_value, conviction_score):
    """
    Calcule la taille de position selon le niveau de conviction.
    MODERATE (50-74): 3% du portfolio
    STRONG (75+):     5% du portfolio
    """
    if conviction_score >= 75:
        pct = 0.05
        level = "STRONG"
    elif conviction_score >= 50:
        pct = 0.03
        level = "MODERATE"
    else:
        return 0, "WEAK"

    size = round(portfolio_value * pct, 2)
    logger.info(f"Position size: ${size:,.2f} ({pct*100:.0f}% portfolio, {level})")
    return size, level

def calculate_quantity(position_value_usd, current_price):
    """
    Convertit la valeur USD en quantite de crypto.
    Arrondi adaptatif selon le prix de l'actif.
    """
    if current_price <= 0:
        return 0
    qty = position_value_usd / current_price
    if current_price > 1000:
        return round(qty, 4)   # BTC: 4 decimales
    elif current_price > 10:
        return round(qty, 2)   # ETH, SOL: 2 decimales
    else:
        return round(qty, 1)   # NEAR, LINK, POLY: 1 decimale

def validate_trade(settings, portfolio_value, current_positions, proposed_coin):
    """
    Verifie les regles de risque avant d'ouvrir une position.
    Retourne (True, "") si OK, (False, reason) si refuse.
    """
    rules = settings.get("risk_rules", {})
    max_pos_pct = rules.get("max_position_pct", 5)
    max_risk_pct = rules.get("max_portfolio_risk_pct", 20)

    # Check nombre max de positions
    open_count = len([p for p in current_positions if p.get("status") == "OPEN"])
    if open_count >= MAX_POSITIONS:
        return False, f"Max {MAX_POSITIONS} positions simultanees atteint"

    # Check pas de doublon
    for p in current_positions:
        if p.get("coin") == proposed_coin and p.get("status") == "OPEN":
            return False, f"Position deja ouverte sur {proposed_coin}"

    # Check risque total portfolio
    total_at_risk = sum(
        p.get("position_value_usd", 0) for p in current_positions
        if p.get("status") == "OPEN"
    )
    risk_pct = (total_at_risk / portfolio_value) * 100 if portfolio_value > 0 else 0
    if risk_pct >= max_risk_pct:
        return False, f"Risque total portfolio ({risk_pct:.1f}%) >= limite ({max_risk_pct}%)"

    return True, ""


# === 2. EXECUTION ALPACA ===

def place_market_buy(client, symbol, quantity, conviction_level):
    """
    Place un ordre market buy sur Alpaca Paper.
    Retourne l'order object ou None si echec.
    """
    try:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        order_req = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC
        )
        order = client.submit_order(order_req)
        logger.info(f"ORDER BUY: {symbol} x{quantity} [{conviction_level}] -> id={order.id}")
        return order
    except ImportError:
        logger.warning("alpaca-py not available — trade simule uniquement")
        return None
    except Exception as e:
        logger.error(f"Order failed {symbol}: {e}")
        return None

def place_take_profit(client, symbol, quantity, tp_price):
    """
    Place un ordre limit sell pour take-profit (+20%).
    """
    try:
        from alpaca.trading.requests import LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        order_req = LimitOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=OrderSide.SELL,
            limit_price=round(tp_price, 2),
            time_in_force=TimeInForce.GTC
        )
        order = client.submit_order(order_req)
        logger.info(f"TAKE-PROFIT: {symbol} @ ${tp_price:,.2f} -> id={order.id}")
        return order
    except Exception as e:
        logger.warning(f"TP order failed {symbol}: {e}")
        return None

def place_stop_loss(client, symbol, quantity, sl_price):
    """
    Place un ordre stop pour stop-loss (-10%).
    """
    try:
        from alpaca.trading.requests import StopOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        order_req = StopOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=OrderSide.SELL,
            stop_price=round(sl_price, 2),
            time_in_force=TimeInForce.GTC
        )
        order = client.submit_order(order_req)
        logger.info(f"STOP-LOSS: {symbol} @ ${sl_price:,.2f} -> id={order.id}")
        return order
    except Exception as e:
        logger.warning(f"SL order failed {symbol}: {e}")
        return None


# === 3. GESTION DES POSITIONS EXISTANTES ===

def check_position_exits(positions, current_prices):
    """
    Verifie si des positions ouvertes ont atteint TP ou SL.
    Met a jour les positions en consequence.
    Retourne (updated_positions, triggered_exits).
    """
    triggered = []
    updated = []

    for pos in positions:
        if pos.get("status") != "OPEN":
            updated.append(pos)
            continue

        coin = pos["coin"]
        entry_price = pos["entry_price"]
        current_price = current_prices.get(coin, {}).get("price")

        if not current_price:
            updated.append(pos)
            continue

        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        # Check Take-Profit
        if pnl_pct >= TAKE_PROFIT_PCT * 100:
            pos["status"] = "CLOSED"
            pos["exit_price"] = current_price
            pos["exit_time"] = now_iso()
            pos["exit_reason"] = "TAKE_PROFIT"
            pos["pnl"] = round(pos["position_value_usd"] * TAKE_PROFIT_PCT, 2)
            pos["pnl_pct"] = round(pnl_pct, 2)
            logger.info(f"TAKE-PROFIT HIT: {coin} +{pnl_pct:.1f}% -> +${pos['pnl']:,.2f}")
            triggered.append(pos)

        # Check Stop-Loss
        elif pnl_pct <= STOP_LOSS_PCT * 100:
            pos["status"] = "CLOSED"
            pos["exit_price"] = current_price
            pos["exit_time"] = now_iso()
            pos["exit_reason"] = "STOP_LOSS"
            pos["pnl"] = round(pos["position_value_usd"] * STOP_LOSS_PCT, 2)
            pos["pnl_pct"] = round(pnl_pct, 2)
            logger.info(f"STOP-LOSS HIT: {coin} {pnl_pct:.1f}% -> ${pos['pnl']:,.2f}")
            triggered.append(pos)

        updated.append(pos)

    return updated, triggered


# === 4. HISTORIQUE ET STATISTIQUES ===

def load_trade_history():
    """Charge l'historique des trades."""
    return load_json(TRADE_HISTORY) or []

def save_trade_history(history):
    """Sauvegarde l'historique des trades."""
    save_json(TRADE_HISTORY, history)

def load_open_positions():
    """Charge les positions ouvertes."""
    return load_json(OPEN_POSITIONS) or []

def save_open_positions(positions):
    """Sauvegarde les positions ouvertes."""
    save_json(OPEN_POSITIONS, positions)

def generate_dry_run_summary(history):
    """
    Genere le resume des performances depuis l'historique.
    Calcule: total trades, PnL cumule, WR, best/worst trade, R:R, EV.
    """
    closed = [t for t in history if t.get("status") == "CLOSED"]
    open_trades = [t for t in history if t.get("status") == "OPEN"]

    if not closed:
        summary = {
            "total_trades": len(history),
            "open_trades": len(open_trades),
            "closed_trades": 0,
            "cumulative_pnl": 0.0,
            "cumulative_pnl_pct": 0.0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
            "best_trade": None,
            "worst_trade": None,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "r_r_ratio": 0.0,
            "expected_value": 0.0,
            "last_updated": now_iso()
        }
    else:
        wins = [t for t in closed if t.get("pnl", 0) > 0]
        losses = [t for t in closed if t.get("pnl", 0) <= 0]
        cumulative_pnl = sum(t.get("pnl", 0) for t in closed)
        total_value = sum(t.get("position_value_usd", 0) for t in closed)
        cumulative_pnl_pct = (cumulative_pnl / total_value * 100) if total_value > 0 else 0

        # Best / Worst
        best = max(closed, key=lambda t: t.get("pnl_pct", -999))
        worst = min(closed, key=lambda t: t.get("pnl_pct", 999))
        avg_win = sum(t.get("pnl", 0) for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.get("pnl", 0) for t in losses) / len(losses) if losses else 0

        # R:R ratio
        r_r = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        # Expected Value
        wr = len(wins) / len(closed) if closed else 0
        ev = (wr * avg_win) + ((1 - wr) * avg_loss)

        summary = {
            "total_trades": len(history),
            "open_trades": len(open_trades),
            "closed_trades": len(closed),
            "cumulative_pnl": round(cumulative_pnl, 2),
            "cumulative_pnl_pct": round(cumulative_pnl_pct, 2),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": round(wr * 100, 1),
            "best_trade": {
                "coin": best["coin"],
                "pnl_pct": best.get("pnl_pct", 0),
                "pnl_usd": best.get("pnl", 0),
                "entry_date": best.get("entry_time", "")[:10],
                "exit_reason": best.get("exit_reason", "?")
            } if best else None,
            "worst_trade": {
                "coin": worst["coin"],
                "pnl_pct": worst.get("pnl_pct", 0),
                "pnl_usd": worst.get("pnl", 0),
                "entry_date": worst.get("entry_time", "")[:10],
                "exit_reason": worst.get("exit_reason", "?")
            } if worst else None,
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "r_r_ratio": round(r_r, 2),
            "expected_value": round(ev, 2),
            "last_updated": now_iso()
        }

    save_json(DRY_RUN_SUMMARY, summary)
    return summary


# === 5. ORCHESTRATION PRINCIPALE ===

def execute_trades(settings=None):
    """
    Point d'entree principal — appele par le cron chaque jour.
    1. Lit la derniere decision
    2. Verifie les positions existantes (TP/SL)
    3. Si conviction >= 50, ouvre de nouvelles positions
    4. Met a jour l'historique et les stats
    """
    if settings is None:
        settings = load_settings()

    # Lire la derniere decision
    decisions = load_json(DECISION_LOG) or []
    if not decisions:
        logger.info("Aucune decision disponible — skip trading")
        return None

    last_decision = decisions[-1]
    score = last_decision.get("score", 0)
    level = last_decision.get("level", "CALM")
    surge_coins = last_decision.get("surge_coins", [])

    logger.info(f"=== Trade Executor: {level} ({score}/100) ===")
    logger.info(f"Seuil minimum: {MIN_CONVICTION}, Score actuel: {score}")

    if score < MIN_CONVICTION:
        logger.info(f"Conviction {score} < {MIN_CONVICTION} — Aucun trade. HOLD.")
        # Quand meme verifier les positions existantes pour TP/SL
        _check_existing_positions(settings)
        return {"action": "HOLD", "reason": f"Conviction {score} < {MIN_CONVICTION}"}

    # === Verifier les positions existantes ===
    current_positions, triggered = _check_existing_positions(settings)

    # === Determiner la taille de position ===
    client = get_alpaca_client(settings)
    if not client:
        logger.warning("Alpaca client indisponible — trades simules uniquement")
        portfolio_value = 100000  # fallback
    else:
        try:
            account = client.get_account()
            portfolio_value = float(account.portfolio_value)
        except Exception as e:
            logger.error(f"Alpaca account error: {e}")
            portfolio_value = 100000

    position_size, conv_level = calculate_position_size(portfolio_value, score)
    logger.info(f"Portfolio: ${portfolio_value:,.0f} | Position: ${position_size:,.0f}")

    # === Selectionner les coins a trader ===
    prices = get_prices_binance()
    history = load_trade_history()
    new_trades = []

    # Construire la liste de candidats
    candidates = []

    # Candidats momentum (surge_coins du decision engine)
    for sc in surge_coins:
        coin_id = sc.get("coin", "").lower()
        if coin_id and coin_id in prices:
            candidates.append({
                "coin": coin_id,
                "change": sc.get("change", 0),
                "source": "momentum"
            })

    # Fallback: si pas de surge, chercher des coins survendus (RSI < 40)
    if not candidates:
        try:
            from binance_provider import get_rsi_all
            rsi_data = get_rsi_all()
            for coin_id, data in rsi_data.items():
                rsi = data.get("rsi")
                if rsi and rsi < 40:
                    chg = prices.get(coin_id, {}).get("change_24h", 0)
                    candidates.append({
                        "coin": coin_id,
                        "change": chg,
                        "rsi": rsi,
                        "source": "oversold"
                    })
            # Trier par RSI croissant (plus survendu = meilleur candidat)
            candidates.sort(key=lambda c: c.get("rsi", 999))
            if candidates:
                logger.info(f"Fallback oversold: {len(candidates)} candidats tries par RSI")
        except Exception as e:
            logger.warning(f"RSI fallback error: {e}")

    # Fallback 2: si toujours rien, prendre le coin avec le meilleur ratio
    if not candidates and score >= 60:
        sorted_by_change = sorted(
            [(cid, cs.get("change_24h", 0)) for cid, cs in prices.items()],
            key=lambda x: x[1], reverse=True
        )
        if sorted_by_change:
            best_coin, best_chg = sorted_by_change[0]
            candidates.append({
                "coin": best_coin,
                "change": best_chg,
                "source": "best_performer"
            })
            logger.info(f"Fallback best performer: {best_coin} ({best_chg:+.1f}%)")

    for cand in candidates[:MAX_POSITIONS]:
        coin_id = cand.get("coin", "").lower()
        if not coin_id:
            continue

        # Valider les regles de risque
        ok, reason = validate_trade(settings, portfolio_value, current_positions, coin_id)
        if not ok:
            logger.info(f"Trade refuse - {coin_id}: {reason}")
            continue

        # Calculer la quantite
        current_price = prices.get(coin_id, {}).get("price", 0)
        if current_price <= 0:
            logger.warning(f"Prix indisponible pour {coin_id} — skip")
            continue

        quantity = calculate_quantity(position_size, current_price)
        symbol = COIN_TO_ALPACA.get(coin_id, f"{coin_id.upper()}/USD")

        # Calculer les niveaux TP/SL
        tp_price = round(current_price * (1 + TAKE_PROFIT_PCT), 2)
        sl_price = round(current_price * (1 + STOP_LOSS_PCT), 2)

        # === EXECUTER SUR ALPACA ===
        # Note: Alpaca crypto ne supporte pas les stop orders ni les bracket orders.
        # On place uniquement le market buy. TP/SL sont geres dans _check_existing_positions()
        # qui verifie les prix a chaque execution cron.
        order = None
        if client:
            order = place_market_buy(client, symbol, quantity, conv_level)
        else:
            logger.info(f"PAPER SIM: {symbol} x{quantity} @ ${current_price:,.2f} [{conv_level}]")

        # === ENREGISTRER LE TRADE ===
        trade_id = f"trade-{len(history)+1:04d}"
        trade = {
            "id": trade_id,
            "coin": coin_id,
            "symbol": symbol,
            "direction": "LONG",
            "source": cand.get("source", "momentum"),
            "entry_price": current_price,
            "entry_time": now_iso(),
            "quantity": quantity,
            "conviction_score": score,
            "conviction_level": conv_level,
            "position_size_pct": 3.0 if conv_level == "MODERATE" else 5.0,
            "position_value_usd": round(quantity * current_price, 2),
            "tp_price": tp_price,
            "sl_price": sl_price,
            "alpaca_order_id": str(order.id) if order else None,
            "exit_price": None,
            "exit_time": None,
            "pnl": None,
            "pnl_pct": None,
            "exit_reason": None,
            "status": "OPEN"
        }
        history.append(trade)
        current_positions.append(trade)
        new_trades.append(trade)

        logger.info(f"TRADE OPENED: {trade_id} {coin_id.upper()} x{quantity} @ ${current_price:,.2f} "
                     f"TP=${tp_price:,.2f} SL=${sl_price:,.2f} [{conv_level}]")

    # Sauvegarder
    save_trade_history(history)
    save_open_positions(current_positions)

    # Generer le resume
    summary = generate_dry_run_summary(history)

    result = {
        "action": "TRADED" if new_trades else "MONITORED",
        "conviction": {"score": score, "level": level},
        "new_trades": len(new_trades),
        "triggered_exits": len(triggered),
        "positions_open": len([p for p in current_positions if p.get("status") == "OPEN"]),
        "summary": summary
    }

    logger.info(f"=== Trade Executor: {result['action']} | "
                f"New: {result['new_trades']} | Exits: {result['triggered_exits']} | "
                f"Open: {result['positions_open']} | PnL: ${summary.get('cumulative_pnl', 0):+,.2f} ===")

    return result


def _check_existing_positions(settings):
    """
    Verifie les positions ouvertes pour TP/SL.
    Met a jour open_positions.json et trade_history.json.
    """
    positions = load_open_positions()
    history = load_trade_history()
    prices = get_prices_binance()

    if not positions:
        return [], []

    updated_positions, triggered = check_position_exits(positions, prices)

    # Mettre a jour l'historique avec les sorties
    if triggered:
        for trig in triggered:
            for i, t in enumerate(history):
                if t.get("id") == trig.get("id"):
                    history[i] = trig
                    break
        save_trade_history(history)
        generate_dry_run_summary(history)

    # Nettoyer: garder seulement les OPEN
    open_only = [p for p in updated_positions if p.get("status") == "OPEN"]
    save_open_positions(open_only)

    return open_only, triggered


# === 6. POINT D'ENTREE ===

if __name__ == "__main__":
    s = load_settings()
    result = execute_trades(s)

    D = "$"
    print(f"\n=== Trade Executor Result ===")
    print(f"Action:       {result['action']}")
    print(f"Conviction:   {result['conviction']['level']} ({result['conviction']['score']}/100)")
    print(f"New trades:   {result['new_trades']}")
    print(f"Exits:        {result['triggered_exits']}")
    print(f"Positions:    {result['positions_open']} open")

    summary = result["summary"]
    print(f"\nPerformance Summary:")
    print(f"  PnL cumule:  {D}{summary.get('cumulative_pnl', 0):+,.2f}")
    print(f"  Win Rate:    {summary.get('win_rate', 0):.1f}%")
    print(f"  Trades:      {summary.get('closed_trades', 0)} fermes / {summary.get('total_trades', 0)} total")
    if summary.get("best_trade"):
        bt = summary["best_trade"]
        print(f"  Best:        {bt['coin']} {bt['pnl_pct']:+.1f}% ({D}{bt['pnl_usd']:+.2f})")
    if summary.get("worst_trade"):
        wt = summary["worst_trade"]
        print(f"  Worst:       {wt['coin']} {wt['pnl_pct']:+.1f}% ({D}{wt['pnl_usd']:+.2f})")
    print(f"  R:R Ratio:   {summary.get('r_r_ratio', 0):.2f}")
    print(f"  EV:          {D}{summary.get('expected_value', 0):+.2f}/trade")
    print(f"\nFiles:")
    print(f"  History:  {TRADE_HISTORY}")
    print(f"  Summary:  {DRY_RUN_SUMMARY}")
    print(f"  Open:     {OPEN_POSITIONS}")

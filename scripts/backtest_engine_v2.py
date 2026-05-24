# backtest_engine_v2.py — Backtest matrice 4 criteres avec FG historique reel
# FORGE Trading Agent
#
# v2.1: Integre l'API alternative.me pour les vraies donnees Fear & Greed
#       Aligne les fonctions de scoring avec decision_engine_v2.py
#       Simule: conviction >= 50 => LONG, TP +20%, SL -10%
#       6 coins, 90 jours, max 3 positions, $3K/trade
#       Metriques: WR, Avg Win/Loss, R:R, EV, Max Drawdown, PnL curve

import sys, json, urllib.request
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import setup_logging

logger = setup_logging("backtest_v2")

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "NEARUSDT", "POLYUSDT"]
NAMES = {"BTCUSDT":"BTC","ETHUSDT":"ETH","SOLUSDT":"SOL","LINKUSDT":"LINK","NEARUSDT":"NEAR","POLYUSDT":"POLY"}
TP = 0.20
SL = -0.10
SIZE = 3000
MAX_POS = 3
THRESHOLD = 50

# =====================================================================
# SCORING — identique a decision_engine_v2.py
# =====================================================================

def score_fear_greed(fg_value):
    """Fear & Greed: <25 = Extreme Fear = max points (opportunite)"""
    if fg_value is None: return 0
    if fg_value <= 25: return 25       # Extreme fear
    elif fg_value <= 40: return 20     # Fear
    elif fg_value <= 60: return 10     # Neutral
    elif fg_value <= 75: return 5      # Greed
    else: return 0                      # Extreme greed

def score_rsi(rsi):
    """RSI: 30-50 = zone d'achat, >70 = surchauffe"""
    if rsi is None: return 0
    if rsi < 20: return 25              # Extreme oversold
    elif rsi < 30: return 20            # Oversold
    elif rsi < 50: return 15            # Neutral-bearish
    elif rsi < 70: return 5             # Neutral-bullish
    else: return 0                       # Overbought

def score_btc_dominance(btc_dom):
    """BTC.D > 55% = alts sous-valorises"""
    if btc_dom is None: return 0
    if btc_dom > 60: return 10
    elif btc_dom > 55: return 5
    elif btc_dom < 45: return -5
    return 0

def score_momentum(change_24h, rsi=None, vol_ratio=None):
    """Momentum: surge avec volume = fort. Cap si RSI > 70."""
    if change_24h is None: return 0
    score = 0
    if change_24h > 10: score = 25
    elif change_24h > 5: score = 15
    elif change_24h > 2: score = 10
    elif change_24h < -10: score = 10   # Oversold bounce
    elif change_24h < -5: score = 5
    if rsi and rsi > 70:
        score = score * 0.5
    return score

def rsi(prices, period=14):
    """Calcul RSI classique (Wilder smoothing)"""
    if len(prices) < period + 1: return None
    gains = [max(prices[i]-prices[i-1],0) for i in range(1,len(prices))]
    losses = [abs(min(prices[i]-prices[i-1],0)) for i in range(1,len(prices))]
    avg_gain = sum(gains[-period:])/period
    avg_loss = sum(losses[-period:])/period
    if avg_loss == 0: return 100.0
    return round(100-(100/(1+avg_gain/avg_loss)), 1)

def mean(vals):
    return sum(vals)/len(vals) if vals else 0

# =====================================================================
# DATA: Binance OHLCV + Alternative.me Fear & Greed
# =====================================================================

def fetch_klines(sym, limit=100):
    """OHLCV journalier Binance"""
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1d&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent":"TA/2.0"})
        raw = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return [{"t": datetime.fromtimestamp(k[0]/1000,tz=timezone.utc).strftime("%Y-%m-%d"),
                 "o":float(k[1]),"c":float(k[4]),"v":float(k[5])} for k in raw]
    except Exception as e:
        logger.error(f"Fetch {sym}: {e}")
        return []

def fetch_fear_greed_history(limit=100):
    """Historique Fear & Greed depuis alternative.me (gratuit, pas de cle)"""
    try:
        url = f"https://api.alternative.me/fng/?limit={limit}&format=json"
        req = urllib.request.Request(url, headers={"User-Agent":"TA/2.0"})
        raw = json.loads(urllib.request.urlopen(req, timeout=15).read())
        fg_map = {}
        for entry in raw.get("data", []):
            ts = int(entry["timestamp"])
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            fg_map[date_str] = int(entry["value"])
        return fg_map
    except Exception as e:
        logger.error(f"Fear & Greed fetch: {e}")
        return {}

# =====================================================================
# BACKTEST
# =====================================================================

def run():
    logger.info("=== BACKTEST V2.1 (FG reel) ===")

    # 1. Fetch data
    print("Fetching 90-day OHLCV Binance...")
    raw = {}
    for sym in COINS:
        raw[sym] = fetch_klines(sym, 100)
        if raw[sym]:
            print(f"  {sym}: {len(raw[sym])}d {raw[sym][0]['t']} -> {raw[sym][-1]['t']}")

    print("Fetching Fear & Greed history...")
    fg_history = fetch_fear_greed_history(100)
    print(f"  FG data points: {len(fg_history)} ({min(fg_history.keys()) if fg_history else 'none'} -> {max(fg_history.keys()) if fg_history else 'none'})")

    if not fg_history:
        print("ERROR: No FG data, cannot run backtest")
        return

    # 2. Build date-indexed structures
    days = {}
    for sym in COINS:
        days[sym] = {d["t"]: d for d in raw.get(sym, [])}

    all_dates = sorted(set(
        d for sym in COINS for d in days.get(sym, {})
        if d in fg_history  # Only dates with FG data
    ))

    if len(all_dates) < 30:
        print(f"ERROR: Only {len(all_dates)} dates with both OHLCV and FG data")
        return

    print(f"Backtest period: {all_dates[0]} -> {all_dates[-1]} ({len(all_dates)} days)")

    # 3. Close history for RSI calculation
    closes_hist = {}
    for sym in COINS:
        closes_hist[sym] = [days[sym][d]["c"] for d in all_dates if d in days.get(sym, {})]

    # 4. Simulate
    trades = []
    open_pos = []
    equity = 100000
    peak = 100000
    max_dd = 0
    wins = 0
    losses = 0
    win_pnl = 0
    loss_pnl = 0
    curve = []

    min_lookback = 15  # RSI needs 15 data points (14+1)

    for i in range(min_lookback, len(all_dates)):
        today = all_dates[i]

        # ---- STEP 1: Check TP/SL exits ----
        for pos in list(open_pos):
            sym = pos["sym"]
            price = days.get(sym, {}).get(today, {}).get("c")
            if not price:
                continue
            pnl_pct = (price - pos["entry"]) / pos["entry"]
            if pnl_pct >= TP or pnl_pct <= SL:
                pos["exit_price"] = price
                pos["exit_date"] = today
                pos["pnl"] = (price - pos["entry"]) * pos["qty"]
                pos["pnl_pct"] = round(pnl_pct * 100, 2)
                pos["outcome"] = "WIN" if pnl_pct > 0 else "LOSS"
                equity += pos["pnl"]
                if pos["outcome"] == "WIN":
                    wins += 1
                    win_pnl += pos["pnl"]
                else:
                    losses += 1
                    loss_pnl += abs(pos["pnl"])
                open_pos.remove(pos)
                trades.append(pos)

        # ---- STEP 2: Compute conviction (4-criteria matrix) ----
        # Fear & Greed: real data from alternative.me
        fg_val = fg_history.get(today, 50)  # default neutral if missing
        fg_s = score_fear_greed(fg_val)

        # RSI per coin
        coin_metrics = {}
        for sym in COINS:
            closes_sym = closes_hist.get(sym, [])[:i+1]
            if len(closes_sym) < 15:
                continue
            r = rsi(closes_sym[-15:], 14)
            chg = ((closes_sym[-1] - closes_sym[-2]) / closes_sym[-2] * 100) if len(closes_sym) >= 2 else 0
            # Skip coins with sparse/zero data (POLY often has gaps)
            if closes_sym[-1] <= 0:
                continue
            coin_metrics[sym] = {"price": closes_sym[-1], "rsi": r, "chg": chg}

        if not coin_metrics:
            continue

        # Aggregate RSI
        rsi_vals = [m["rsi"] for m in coin_metrics.values() if m.get("rsi") is not None]
        avg_rsi = mean(rsi_vals) if rsi_vals else None

        rsi_s = score_rsi(avg_rsi)

        # BTC Dominance proxy (constant approximation, same as production)
        btc_s = score_btc_dominance(55)

        # Momentum: best coin daily change
        best_coin = None
        mom_s = 0
        for sym, m in coin_metrics.items():
            ms = score_momentum(m.get("chg", 0), m.get("rsi"))
            if ms > mom_s:
                mom_s = ms
                best_coin = sym

        total = fg_s + rsi_s + btc_s + mom_s

        # ---- STEP 3: Open trade if signal ----
        if total >= THRESHOLD and len(open_pos) < MAX_POS and best_coin:
            in_positions = [p["sym"] for p in open_pos]
            if best_coin not in in_positions:
                entry = coin_metrics[best_coin]["price"]
                qty = SIZE / entry
                pos = {
                    "sym": best_coin,
                    "coin": NAMES.get(best_coin, best_coin),
                    "entry": entry,
                    "date": today,
                    "qty": qty,
                    "value": SIZE,
                    "score": total,
                    "fg": fg_val, "avg_rsi": avg_rsi,
                    "tp": entry * (1 + TP),
                    "sl": entry * (1 + SL),
                    "exit_price": None, "exit_date": None,
                    "pnl": None, "pnl_pct": None, "outcome": None
                }
                open_pos.append(pos)
                logger.info(f"TRADE: {best_coin} @ {today} score={total} FG={fg_val} RSI={coin_metrics[best_coin].get('rsi')}")

        # ---- STEP 4: Daily PnL ----
        unreal = 0
        for p in open_pos:
            price = days.get(p["sym"], {}).get(today, {}).get("c")
            if price:
                unreal += (price - p["entry"]) * p["qty"]
        daily_eq = equity + unreal
        curve.append({"date": today, "equity": round(daily_eq, 2), "open": len(open_pos)})
        peak = max(peak, daily_eq)
        dd_pct = (peak - daily_eq) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd_pct)

    # 5. Metrics
    closed = [t for t in trades if t.get("outcome")]
    total_pnl = sum(t["pnl"] for t in closed if t["pnl"] is not None) if closed else 0
    aw = sum(t["pnl"] for t in closed if t["outcome"]=="WIN" and t["pnl"] is not None) / max(wins, 1)
    al = sum(t["pnl"] for t in closed if t["outcome"]=="LOSS" and t["pnl"] is not None) / max(losses, 1)
    wr = (wins / len(closed) * 100) if closed else 0
    rr = abs(aw/al) if al != 0 and aw != 0 else 0
    ev = (wr/100 * aw) - ((1-wr/100) * abs(al))

    result = {
        "backtest": "v2.1_fg_real",
        "period": f"{all_dates[min_lookback]} -> {all_dates[-1]}",
        "params": {"tp": TP, "sl": SL, "size": SIZE, "max_pos": MAX_POS, "threshold": THRESHOLD},
        "metrics": {
            "total": len(trades), "closed": len(closed), "open_end": len(open_pos),
            "wins": wins, "losses": losses, "wr": round(wr,1),
            "avg_win": round(aw,2), "avg_loss": round(al,2),
            "total_pnl": round(total_pnl,2), "rr": round(rr,2), "ev": round(ev,2),
            "max_dd": round(max_dd,2), "final_equity": round(equity,2),
            "return_pct": round((equity-100000)/100000*100, 2)
        },
        "trades": trades[-20:],  # Last 20 trades for debug
        "pnl_curve": curve[-60:]
    }

    # Save
    out_dir = Path(__file__).resolve().parent.parent / "data" / "backtest_v2"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"v2.1_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)

    # Print summary
    m = result["metrics"]
    print(f"\n{'='*55}")
    print(f"BACKTEST V2.1 (Fear & Greed reel)")
    print(f"Periode: {result['period']}")
    print(f"{'='*55}")
    print(f"Trades: {m['total']} | Fermes: {m['closed']} | Ouverts: {m['open_end']}")
    print(f"Wins: {m['wins']} | Losses: {m['losses']} | WR: {m['wr']}%")
    print(f"Avg Win: {m['avg_win']:+,.2f} | Avg Loss: {m['avg_loss']:+,.2f}")
    print(f"R:R: {m['rr']:.2f} | EV: {m['ev']:+,.2f}")
    print(f"Total PnL: {m['total_pnl']:+,.2f} | Return: {m['return_pct']:+.2f}%")
    print(f"Max DD: {m['max_dd']:.2f}% | Final Equity: {m['final_equity']:,.2f}")
    print(f"\nDerniers trades:")
    for t in closed[-5:]:
        print(f"  {t['date']} {t['coin']:4s} {t['entry']:>10.4f} -> {t['exit_price']:>10.4f}  {t['pnl_pct']:>+6.2f}%  {t['pnl']:>+8.2f}  {t['outcome']}")
    print(f"\nSauvegarde: {out}")

    return result

if __name__ == "__main__":
    run()

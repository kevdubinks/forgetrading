# backtest_engine_v2.py — Backtest matrice 4 criteres (clean rewrite)
# FORGE Trading Agent
# 
# Simule la strategie reelle: conviction >= 50 => LONG, TP +20%, SL -10%
# 5 coins, 90 jours, max 3 positions, $3K/trade
# Metriques: WR, Avg Win/Loss, R:R, EV, Max Drawdown, PnL curve

import sys, json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import setup_logging

logger = setup_logging("backtest_v2")

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "NEARUSDT"]
NAMES = {"BTCUSDT":"BTC","ETHUSDT":"ETH","SOLUSDT":"SOL","LINKUSDT":"LINK","NEARUSDT":"NEAR"}
TP = 0.20
SL = -0.10
SIZE = 3000
MAX_POS = 3
THRESHOLD = 50

# =====================================================================
# SCORING (identique a decision_engine_v2.py)
# =====================================================================

def score_fg(val):
    if val is None: return 0
    if val <= 20: return 25
    if val <= 35: return 20
    if val <= 50: return 10
    if val <= 65: return 5
    return 0

def score_rsi(avg):
    if avg is None: return 0
    if avg < 30: return 25
    if avg < 40: return 20
    if avg < 50: return 15
    if avg < 60: return 10
    if avg < 70: return 5
    return 0

def score_btcd(val):
    if val is None: return 0
    if val >= 60: return 10
    if val >= 50: return 5
    return 0

def score_mom(chg, rsi=None):
    if chg is None: return 0
    if chg >= 5: base = 25
    elif chg >= 2: base = 15
    elif chg >= 0: base = 10
    elif chg >= -5: base = 5
    else: base = 0
    if rsi and rsi > 70:
        base /= 2
    return min(base, 25)

def rsi(prices, period=14):
    if len(prices) < period + 1: return None
    g = [max(prices[i]-prices[i-1],0) for i in range(1,len(prices))]
    l = [abs(min(prices[i]-prices[i-1],0)) for i in range(1,len(prices))]
    ag = sum(g[-period:])/period
    al = sum(l[-period:])/period
    if al == 0: return 100.0
    return round(100-(100/(1+ag/al)), 1)

def mean(vals):
    return sum(vals)/len(vals) if vals else 0

# =====================================================================
# DATA
# =====================================================================

import urllib.request

def fetch(sym, limit=100):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1d&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent":"TA/2.0"})
        raw = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return [{"t": datetime.fromtimestamp(k[0]/1000,tz=timezone.utc).strftime("%Y-%m-%d"),
                 "o":float(k[1]),"c":float(k[4]),"v":float(k[5])} for k in raw]
    except Exception as e:
        logger.error(f"Fetch {sym}: {e}")
        return []

# =====================================================================
# BACKTEST
# =====================================================================

def run():
    logger.info("=== BACKTEST V2 (clean) ===")
    
    # 1. Fetch data
    print("Fetching 90-day OHLCV...")
    raw = {}
    for sym in COINS:
        raw[sym] = fetch(sym, 100)
        if raw[sym]:
            print(f"  {sym}: {len(raw[sym])}d {raw[sym][0]['t']} -> {raw[sym][-1]['t']}")
    
    # 2. Build clean date-indexed structure
    #   days[sym] = {date: {open, close, volume}}
    days = {}
    for sym in COINS:
        days[sym] = {d["t"]: d for d in raw.get(sym, [])}
    
    # All dates (union, sorted)
    all_dates = sorted(set(d for sym in COINS for d in days.get(sym, {})))
    
    # 3. Build close history for RSI (ordered list per symbol)
    closes_hist = {}
    for sym in COINS:
        closes_hist[sym] = [days[sym][d]["c"] for d in all_dates if d in days.get(sym,{})]
    
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
    
    min_lookback = 30  # need 30 days for FG proxy + 14 for RSI
    
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
        
        # ---- STEP 2: Compute conviction ----
        # Fear & Greed proxy: BTC 30-day drawdown
        btc_close_today = days.get("BTCUSDT", {}).get(today, {}).get("c")
        btc_hist_30 = closes_hist.get("BTCUSDT", [])[max(0,i-30):i+1]
        if len(btc_hist_30) >= 30 and btc_close_today:
            high30 = max(btc_hist_30)
            dd = (btc_close_today - high30) / high30 * 100
            if dd < -20: fg_val = 15
            elif dd < -10: fg_val = 25
            elif dd < -5: fg_val = 32
            elif dd < 0: fg_val = 45
            else: fg_val = 65
        else:
            fg_val = 50
        
        # RSI per coin
        coin_metrics = {}
        for sym in COINS:
            closes_sym = closes_hist.get(sym, [])[:i+1]
            if len(closes_sym) < 15:
                continue
            r = rsi(closes_sym[-15:], 14)
            chg = ((closes_sym[-1] - closes_sym[-2]) / closes_sym[-2] * 100) if len(closes_sym) >= 2 else 0
            coin_metrics[sym] = {"price": closes_sym[-1], "rsi": r, "chg": chg}
        
        if not coin_metrics:
            continue
        
        # Scores
        rsi_vals = [m["rsi"] for m in coin_metrics.values() if m.get("rsi")]
        avg_rsi = mean(rsi_vals) if rsi_vals else None
        
        fg_s = score_fg(fg_val)
        rsi_s = score_rsi(avg_rsi)
        btc_s = score_btcd(55)  # proxy: >50%
        
        best_coin = None
        mom_s = 0
        for sym, m in coin_metrics.items():
            ms = score_mom(m.get("chg", 0), m.get("rsi"))
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
                    "tp": entry * (1 + TP),
                    "sl": entry * (1 + SL),
                    "exit_price": None, "exit_date": None,
                    "pnl": None, "pnl_pct": None, "outcome": None
                }
                open_pos.append(pos)
        
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
    total_pnl = sum(t["pnl"] for t in closed if t["pnl"]) if closed else 0
    aw = sum(t["pnl"] for t in closed if t["outcome"]=="WIN" and t["pnl"]) / max(wins, 1)
    al = sum(t["pnl"] for t in closed if t["outcome"]=="LOSS" and t["pnl"]) / max(losses, 1)
    wr = (wins / len(closed) * 100) if closed else 0
    rr = abs(aw/al) if al != 0 and aw != 0 else 0
    ev = (wr/100 * aw) - ((1-wr/100) * abs(al))
    
    result = {
        "backtest": "v2_clean",
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
        "pnl_curve": curve[-30:]
    }
    
    # Save
    out_dir = Path(__file__).resolve().parent.parent / "data" / "backtest_v2"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"v2_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    
    # Print
    m = result["metrics"]
    print(f"\n{'='*50}")
    print(f"BACKTEST V2 — {result['period']}")
    print(f"{'='*50}")
    print(f"Trades: {m['total']} | Closed: {m['closed']} | Open: {m['open_end']}")
    print(f"Wins: {m['wins']} | Losses: {m['losses']} | WR: {m['wr']}%")
    print(f"Avg Win: ${m['avg_win']:+,.2f} | Avg Loss: ${m['avg_loss']:+,.2f}")
    print(f"R:R: {m['rr']:.2f} | EV: ${m['ev']:+,.2f}")
    print(f"Total PnL: ${m['total_pnl']:+,.2f} | Return: {m['return_pct']:+.2f}%")
    print(f"Max DD: {m['max_dd']:.2f}% | Final: ${m['final_equity']:,.2f}")
    print(f"\nSaved: {out}")
    
    return result

if __name__ == "__main__":
    run()

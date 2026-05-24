# backtest_engine_v2.py — Backtest avec la vraie matrice 4 criteres
# FORGE Trading Agent — Phase 4
# 
# Ce backtest utilise EXACTEMENT la meme logique que decision_engine_v2.py:
#   - Fear/Greed score
#   - RSI moyen
#   - BTC Dominance
#   - Momentum (change_24h + RSI cap)
# 
# Modele: daily OHLCV 90j, buy next-day-open si conviction >= 50
# TP +20%, SL -10%, max 3 positions simultanees
# Metriques: WR, Avg Win/Loss, R:R, EV, Max Drawdown, PnL curve

import sys, json, os, math
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import setup_logging, load_settings, now_iso

logger = setup_logging("backtest_v2")
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "backtest_v2"

# =====================================================================
# SCORING — Identique a decision_engine_v2.py
# =====================================================================

def score_fear_greed(fg_value):
    if fg_value is None: return 0
    if fg_value <= 20: return 25   # Extreme Fear = best buy
    if fg_value <= 35: return 20   # Fear
    if fg_value <= 50: return 10   # Neutral
    if fg_value <= 65: return 5    # Greed
    return 0                        # Extreme Greed = avoid

def score_rsi(avg_rsi):
    if avg_rsi is None: return 0
    if avg_rsi < 30: return 25     # Oversold
    if avg_rsi < 40: return 20
    if avg_rsi < 50: return 15
    if avg_rsi < 60: return 10
    if avg_rsi < 70: return 5
    return 0

def score_btc_dominance(btc_dom):
    if btc_dom is None: return 0
    if btc_dom >= 60: return 10    # High BTC.D = alt season ahead
    if btc_dom >= 50: return 5
    return 0

def score_momentum(change_24h, coin_rsi=None, vol_ratio=None):
    if change_24h is None: return 0
    base = 0
    if change_24h >= 5: base = 25
    elif change_24h >= 2: base = 15
    elif change_24h >= 0: base = 10
    elif change_24h >= -5: base = 5
    if coin_rsi is not None and coin_rsi > 70:
        base /= 2  # RSI cap
    return min(base, 25)

# =====================================================================
# DATA — Fetch daily OHLCV from Binance
# =====================================================================

import urllib.request, time as _time

def fetch_daily_klines(symbol, limit=100):
    """Fetch daily OHLCV from Binance."""
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/2.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return [
            {
                "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
                "close": float(k[4]), "volume": float(k[5]),
                "ts": datetime.fromtimestamp(k[0]/1000, tz=timezone.utc).strftime("%Y-%m-%d")
            }
            for k in data
        ]
    except Exception as e:
        logger.error(f"Klines {symbol}: {e}")
        return []

def compute_rsi_from_series(closes, period=14):
    if len(closes) < period + 1: return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(diff if diff > 0 else 0)
        losses.append(abs(diff) if diff < 0 else 0)
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)

# =====================================================================
# BACKTEST ENGINE
# =====================================================================

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "NEARUSDT"]  # POLY: data too sparse
COIN_NAMES = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL", "LINKUSDT": "LINK", "NEARUSDT": "NEAR", "POLYUSDT": "POLY"}

TP_PCT = 0.20
SL_PCT = -0.10
POSITION_SIZE = 3000  # $3K per trade (Mode B MODERATE)
MAX_POSITIONS = 3
CONVICTION_THRESHOLD = 50

def run_backtest_v2():
    logger.info("=== BACKTEST V2 START ===")
    
    # 1. Fetch daily data for all coins (90 days)
    print("Fetching 90-day OHLCV...")
    data = {}
    for sym in COINS:
        klines = fetch_daily_klines(sym, limit=100)
        if klines:
            data[sym] = klines[-90:]  # last 90 days
            print(f"  {sym}: {len(data[sym])} days ({data[sym][0]['ts']} -> {data[sym][-1]['ts']})")
        _time.sleep(0.2)  # Rate limit
    
    if len(data) < 2:
        logger.error("Insufficient data")
        return None
    
    # 2. Simulate day by day
    all_dates = sorted(set(d["ts"] for klines in data.values() for d in klines))
    trades = []
    open_positions = []
    daily_pnl = []
    peak_equity = 100000
    equity = 100000
    max_dd = 0
    win_count = loss_count = 0
    total_win_pnl = total_loss_pnl = 0
    
    # We need at least 15 days of history for RSI calculation
    start_idx = 15
    
    # Build date-indexed price maps for efficient lookup
    price_map = {}
    for sym in COINS:
        price_map[sym] = {d["ts"]: d["close"] for d in data.get(sym, [])}

    for day_idx in range(start_idx, len(all_dates)):
        date = all_dates[day_idx]
        
        # ===== STEP 1: Check exits (TP/SL) =====
        for pos in list(open_positions):
            sym = pos["symbol"]
            current_price = price_map.get(sym, {}).get(date)
            if not current_price:
                continue
            pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"]
            
            if pnl_pct >= TP_PCT or pnl_pct <= SL_PCT:
                pos["exit_price"] = current_price
                pos["exit_date"] = date
                pos["pnl"] = pos["quantity"] * current_price - pos["value"]
                pos["pnl_pct"] = pnl_pct * 100
                pos["outcome"] = "WIN" if pnl_pct > 0 else "LOSS"
                
                equity += pos["pnl"]
                if pos["outcome"] == "WIN":
                    win_count += 1
                    total_win_pnl += pos["pnl"]
                else:
                    loss_count += 1
                    total_loss_pnl += abs(pos["pnl"])
                
                open_positions.remove(pos)
                trades.append(pos)
        
        # ===== STEP 2: Generate conviction score =====
        # Compute metrics from last 7-14 days of closes
        coin_metrics = {}
        for sym in COINS:
            if sym not in data:
                continue
            closes = close_history[sym][:day_idx+1]
            if len(closes) < 15:
                continue
            closes_15 = closes[-15:]
            rsi = compute_rsi_from_series(closes_15, 14)
            chg = ((closes[-1] - closes[-2]) / closes[-2]) * 100 if len(closes) >= 2 else 0
            coin_metrics[sym] = {"price": closes[-1], "rsi": rsi, "change_24h": chg}
        
        if not coin_metrics:
            continue
        
        # Fear & Greed proxy: BTC 30-day drawdown = better fear signal
        # Real FG 0-25 = Extreme Fear (score 25), 25-35 = Fear (score 20)
        btc_closes_fg = close_history.get("BTCUSDT", [])[:day_idx+1]
        if len(btc_closes_fg) >= 30:
            high30 = max(btc_closes_fg[-30:])
            drawdown = (btc_closes_fg[-1] - high30) / high30 * 100
            if drawdown < -20: fg_proxy = 15      # Extreme Fear
            elif drawdown < -10: fg_proxy = 25     # Extreme Fear / Fear
            elif drawdown < -5: fg_proxy = 32      # Fear
            elif drawdown < 0: fg_proxy = 45       # Neutral
            else: fg_proxy = 65                     # Greed
        else:
            fg_proxy = 50
        
        # BTC Dominance: use BTC volume / total volume as proxy
        btc_vol = coin_metrics.get("BTCUSDT", {}).get("change_24h", 0) or 0
        total_vol = sum(abs(m.get("change_24h", 0) or 0) for m in coin_metrics.values())
        btc_dom_proxy = 60 if total_vol > 0 and abs(btc_vol) > total_vol * 0.4 else 55
        
        # Avg RSI
        rsi_values = [m["rsi"] for m in coin_metrics.values() if m.get("rsi") is not None]
        avg_rsi = sum(rsi_values) / len(rsi_values) if rsi_values else None
        
        # Score
        fg_score = score_fear_greed(fg_proxy)
        rsi_score = score_rsi(avg_rsi)
        btc_score = score_btc_dominance(btc_dom_proxy)
        
        # Momentum: best coin
        momentum_score = 0
        best_coin = None
        for sym, m in coin_metrics.items():
            ms = score_momentum(m.get("change_24h", 0), m.get("rsi"))
            if ms > momentum_score:
                momentum_score = ms
                best_coin = sym
        
        total_score = fg_score + rsi_score + btc_score + momentum_score
        
        # ===== STEP 3: Execute trades if conviction >= threshold =====
        if total_score >= CONVICTION_THRESHOLD and len(open_positions) < MAX_POSITIONS and best_coin and best_coin in coin_metrics:
            coin_data = coin_metrics[best_coin]
            if coin_data.get("price"):
                if best_coin not in [p["symbol"] for p in open_positions]:
                    entry_price = coin_data["price"]
                quantity = POSITION_SIZE / entry_price
                pos = {
                    "symbol": best_coin,
                    "coin": COIN_NAMES.get(best_coin, best_coin),
                    "entry_price": entry_price,
                    "entry_date": date,
                    "quantity": quantity,
                    "value": POSITION_SIZE,
                    "conviction_score": total_score,
                    "tp": entry_price * (1 + TP_PCT),
                    "sl": entry_price * (1 + SL_PCT),
                    "exit_price": None,
                    "exit_date": None,
                    "pnl": None,
                    "pnl_pct": None,
                    "outcome": None
                }
                open_positions.append(pos)
        
        # ===== STEP 4: Track daily PnL =====
        unrealized = 0
        for pos in open_positions:
            curr = price_map.get(pos["symbol"], {}).get(date)
            if curr:
                unrealized += (curr - pos["entry_price"]) * pos["quantity"]
        
        daily_equity = equity + unrealized
        daily_pnl.append({"date": date, "equity": daily_equity, "open": len(open_positions)})
        peak_equity = max(peak_equity, daily_equity)
        dd = (peak_equity - daily_equity) / peak_equity * 100
        max_dd = max(max_dd, dd)
    
    # ===== STEP 5: Compute metrics =====
    total_trades = len(trades)
    closed = [t for t in trades if t["outcome"]]
    total_pnl = sum(t["pnl"] for t in closed if t["pnl"]) if closed else 0
    
    avg_win = sum(t["pnl"] for t in closed if t["outcome"] == "WIN" and t["pnl"]) / max(win_count, 1)
    avg_loss = sum(t["pnl"] for t in closed if t["outcome"] == "LOSS" and t["pnl"]) / max(loss_count, 1)
    win_rate = (win_count / len(closed) * 100) if closed else 0
    r_r = abs(avg_win / avg_loss) if avg_loss != 0 and avg_win != 0 else 0
    ev = (win_rate/100 * avg_win) - ((1 - win_rate/100) * abs(avg_loss))
    
    result = {
        "backtest": "v2_4criteria",
        "period": f"{all_dates[start_idx]} -> {all_dates[-1]}",
        "params": {
            "tp_pct": TP_PCT, "sl_pct": SL_PCT,
            "position_size": POSITION_SIZE, "max_positions": MAX_POSITIONS,
            "conviction_threshold": CONVICTION_THRESHOLD
        },
        "metrics": {
            "total_trades": total_trades,
            "closed_trades": len(closed),
            "open_at_end": len(open_positions),
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": round(win_rate, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "total_pnl": round(total_pnl, 2),
            "r_r_ratio": round(r_r, 2),
            "expected_value": round(ev, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "final_equity": round(equity, 2),
            "return_pct": round((equity - 100000) / 100000 * 100, 2)
        },
        "trades": trades,
        "pnl_curve": daily_pnl[-30:]  # last 30 days
    }
    
    # Save
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / f"backtest_v2_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    
    # Print summary
    m = result["metrics"]
    print(f"\n{'='*50}")
    print(f"BACKTEST V2 — {result['period']}")
    print(f"{'='*50}")
    print(f"Trades: {m['total_trades']} total | {m['closed_trades']} closed | {m['open_at_end']} open")
    print(f"Win: {m['win_count']} | Loss: {m['loss_count']} | WR: {m['win_rate']}%")
    print(f"Avg Win: ${m['avg_win']:+,.2f} | Avg Loss: ${m['avg_loss']:+,.2f}")
    print(f"R:R Ratio: {m['r_r_ratio']:.2f} | EV: ${m['expected_value']:+,.2f}/trade")
    print(f"Total PnL: ${m['total_pnl']:+,.2f} | Return: {m['return_pct']:+.2f}%")
    print(f"Max Drawdown: {m['max_drawdown_pct']:.2f}%")
    print(f"Final Equity: ${m['final_equity']:,.2f}")
    print(f"\nSaved: {out}")
    
    return result

if __name__ == "__main__":
    run_backtest_v2()

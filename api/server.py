# server.py — FORGE Trading API (Flask)
# Deploie sur Render: gunicorn api.server:app
# Local: python api/server.py (port 8080)
# 
# Endpoints:
#   GET /                 -> dashboard.html
#   GET /api/dry-run      -> performance resume (PnL, WR, R:R, EV)
#   GET /api/prices       -> prix Binance + RSI en temps reel
#   GET /api/decision     -> score conviction du jour (4 criteres)
#   GET /api/portfolio    -> compte Alpaca Paper + positions
#   GET /api/trades       -> historique trades (Supabase placeholder)
#   GET /api/health       -> health check Render

import sys
import os
import time
import json
import logging
from pathlib import Path

# === Logging minimal (Flask a son propre logger) ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("forge-api")

# === Ajouter scripts/ au path ===
ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
sys.path.insert(0, str(SCRIPTS))

# === Flask init ===
from flask import Flask, jsonify, send_from_directory, request

app = Flask(__name__)

# === CORS (dashboard peut etre servi depuis n'importe ou) ===
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


# =====================================================================
# CACHE LAYER — evite spammer Binance/Alpaca sur chaque refresh
# =====================================================================
_cache = {}
DEFAULT_TTL = 60  # secondes

def cached(key, ttl=DEFAULT_TTL):
    """Decorateur: cache le resultat d'une fonction pendant ttl secondes."""
    def decorator(fn):
        def wrapper(*args, **kwargs):
            now = time.time()
            if key in _cache and now - _cache[key]["ts"] < ttl:
                return _cache[key]["data"]
            data = fn(*args, **kwargs)
            _cache[key] = {"data": data, "ts": now}
            return data
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorator


# =====================================================================
# LOADERS — importent les modules internes avec fallback
# =====================================================================

def _import_or_none(module_name, attr_name):
    """Import securise: retourne l'attribut ou None si indisponible."""
    try:
        mod = __import__(module_name, fromlist=[attr_name])
        return getattr(mod, attr_name, None)
    except Exception as e:
        logger.warning(f"Import failed {module_name}.{attr_name}: {e}")
        return None


# =====================================================================
# ENDPOINTS
# =====================================================================

@app.route("/")
def serve_dashboard():
    """Sert dashboard.html depuis la racine du projet."""
    dashboard_path = ROOT / "dashboard.html"
    if dashboard_path.exists():
        return send_from_directory(str(ROOT), "dashboard.html")
    return jsonify({"error": "dashboard.html not found"}), 404


@app.route("/api/health")
def health():
    """Health check pour Render — repond en <1ms."""
    return jsonify({
        "status": "ok",
        "service": "forge-dashboard",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    })


# --- /api/dry-run — Resume de performance (PRIORITE 1) ---

@app.route("/api/dry-run")
def api_dry_run():
    """Performance resume: PnL, WR, R:R, EV, best/worst trade."""
    try:
        # Essayer Supabase d'abord
        try:
            from supabase_client import get_dry_run_summary, get_all_trades
            summary = get_dry_run_summary()
            open_trades = get_all_trades(outcome="OPEN", limit=20)
            if summary and summary.get("total_trades", 0) > 0:
                summary["open_positions"] = len(open_trades)
                summary["open_positions_detail"] = [
                    {
                        "coin": t.get("coin"),
                        "symbol": t.get("symbol"),
                        "entry_price": t.get("entry_price"),
                        "quantity": t.get("quantity"),
                        "conviction": t.get("conviction_level")
                    }
                    for t in open_trades
                ]
                summary["source"] = "supabase"
                return jsonify(summary)
        except Exception as e:
            logger.warning(f"Supabase fallback: {e}")

        # Fallback local JSON
        load_open_positions = _import_or_none("trade_executor", "load_open_positions")
        load_trade_history = _import_or_none("trade_executor", "load_trade_history")
        generate_dry_run_summary = _import_or_none("trade_executor", "generate_dry_run_summary")

        if not all([load_trade_history, generate_dry_run_summary]):
            return jsonify({"error": "trade_executor module not available"}), 503

        history = load_trade_history()
        summary = generate_dry_run_summary(history)

        if load_open_positions:
            positions = load_open_positions()
            summary["open_positions"] = len([p for p in positions if p.get("status") == "OPEN"])
            summary["open_positions_detail"] = [
                {
                    "coin": p.get("coin"),
                    "symbol": p.get("symbol"),
                    "entry_price": p.get("entry_price"),
                    "quantity": p.get("quantity"),
                    "conviction": p.get("conviction_level")
                }
                for p in positions if p.get("status") == "OPEN"
            ]
        else:
            summary["open_positions"] = 0
            summary["open_positions_detail"] = []

        summary["source"] = "local_json"
        return jsonify(summary)
    except Exception as e:
        logger.error(f"/api/dry-run error: {e}")
        return jsonify({"error": str(e)}), 500


# --- /api/prices — Prix Binance + RSI (PRIORITE 2) ---

@app.route("/api/prices")
def api_prices():
    """Prix en temps reel depuis Binance + RSI par coin."""
    try:
        get_prices = _import_or_none("binance_provider", "get_prices_binance")
        get_rsi = _import_or_none("binance_provider", "get_rsi_all")
        
        if not get_prices:
            return jsonify({"error": "binance_provider not available"}), 503
        
        prices = get_prices()
        rsi_data = get_rsi() if get_rsi else {}
        
        # Fusionner prix + RSI
        result = {}
        for coin, data in prices.items():
            entry = {
                "price": data.get("price"),
                "change_24h": data.get("change_24h"),
                "volume_24h": data.get("volume_24h"),
                "rsi": rsi_data.get(coin, {}).get("rsi"),
                "rsi_signal": rsi_data.get(coin, {}).get("signal")
            }
            result[coin] = entry
        
        return jsonify({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "coins": result
        })
    except Exception as e:
        logger.error(f"/api/prices error: {e}")
        return jsonify({"error": str(e)}), 500


# --- /api/decision — Score conviction (PRIORITE 3) ---

@app.route("/api/decision")
def api_decision():
    """Score conviction multi-signaux (Fear/Greed + RSI + BTC.D + Momentum)."""
    try:
        get_signals = _import_or_none("binance_provider", "get_enhanced_signals_binance")
        get_prices = _import_or_none("binance_provider", "get_prices_binance")
        generate = _import_or_none("decision_engine_v2", "generate_conviction_v2")
        
        if not all([get_signals, get_prices, generate]):
            return jsonify({"error": "decision engine not available"}), 503
        
        # 1. Enhanced signals (FG, BTC.D, RSI, prices)
        enhanced_signals = get_signals()
        
        # 2. Price data avec alerts (pour le scoring momentum)
        prices = get_prices()
        alerts = []
        for coin_id, data in prices.items():
            chg = data.get("change_24h", 0)
            if abs(chg) >= 5:  # seuil minimal pour etre une "alerte"
                alerts.append({
                    "coin": coin_id.upper(),
                    "change_24h": chg,
                    "price": data.get("price"),
                    "volume_24h": data.get("volume_24h")
                })
        price_data = {"alerts": alerts, "coins": prices}
        
        # 3. Wallet alerts (vide pour l'API — couteux a charger)
        wallet_alerts = []
        
        # 4. Articles (vide pour l'API — pas de news en temps reel)
        articles = []
        
        conviction = generate(articles, price_data, wallet_alerts, enhanced_signals)
        
        # Charger decision persistee si disponible
        decisions_file = DATA_DIR / "decisions_v2.json"
        last_decision = None
        if decisions_file.exists():
            try:
                with open(decisions_file, "r", encoding="utf-8") as f:
                    decisions = json.load(f)
                    if decisions:
                        last_decision = decisions[-1]
            except Exception:
                pass
        
        return jsonify({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "current": conviction,
            "last_stored": last_decision
        })
    except Exception as e:
        logger.error(f"/api/decision error: {e}")
        return jsonify({"error": str(e)}), 500


# --- /api/portfolio — Alpaca Paper (PRIORITE 4) ---

@app.route("/api/portfolio")
def api_portfolio():
    """Compte Alpaca Paper + positions + market status."""
    try:
        get_client = _import_or_none("alpaca_tracker", "get_alpaca_client")
        get_account = _import_or_none("alpaca_tracker", "get_account_summary")
        get_positions = _import_or_none("alpaca_tracker", "get_positions")
        get_status = _import_or_none("alpaca_tracker", "get_market_status")
        
        if not all([get_client, get_account]):
            return jsonify({"error": "alpaca_tracker not available"}), 503
        
        client = get_client()
        account = get_account(client) if client else None
        positions = get_positions(client) if client and get_positions else []
        market = get_status(client) if client and get_status else None
        
        result = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "connected": client is not None,
            "account": account,
            "market": market,
            "positions": positions,
            "position_count": len(positions) if positions else 0
        }
        return jsonify(result)
    except Exception as e:
        logger.error(f"/api/portfolio error: {e}")
        return jsonify({"error": str(e), "connected": False}), 500


# --- /api/trades — Historique (PRIORITE 5, Supabase + fallback local) ---

@app.route("/api/trades")
def api_trades():
    """Historique des trades. Supabase si configure, sinon JSON local."""
    try:
        limit = request.args.get("limit", default=20, type=int)
        outcome = request.args.get("outcome")

        # Essayer Supabase
        try:
            from supabase_client import get_all_trades
            trades = get_all_trades(outcome=outcome, limit=limit)
            return jsonify({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "total": len(trades),
                "trades": trades,
                "source": "supabase"
            })
        except Exception as e:
            logger.warning(f"Supabase trades fallback: {e}")

        # Fallback local
        history_file = DATA_DIR / "trade_history.json"
        trades = []
        if history_file.exists():
            with open(history_file, "r", encoding="utf-8") as f:
                trades = json.load(f)

        if outcome:
            trades = [t for t in trades if t.get("outcome") == outcome or t.get("status") == outcome]

        return jsonify({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total": len(trades),
            "trades": trades[-limit:],
            "source": "local_json"
        })
    except Exception as e:
        logger.error(f"/api/trades error: {e}")
        return jsonify({"error": str(e)}), 500


# =====================================================================
# MAIN — port 8080 (Render override avec PORT env var)
# =====================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"FORGE Dashboard API starting on port {port}...")
    logger.info(f"Root: {ROOT}")
    logger.info(f"Scripts: {SCRIPTS}")
    logger.info("Endpoints: /api/health /api/dry-run /api/prices /api/decision /api/portfolio /api/trades")
    app.run(host="0.0.0.0", port=port, debug=False)

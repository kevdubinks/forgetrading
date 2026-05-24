# server.py - FORGE Trading API (Flask) v2.2
# Render: gunicorn api.server:app | Local: python api/server.py

import sys, os, time, json, logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("forge-api")

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
DATA_DIR = ROOT / "data"
sys.path.insert(0, str(SCRIPTS))

from flask import Flask, jsonify, send_from_directory, request
app = Flask(__name__)

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

def _import_or_none(mod_name, attr_name):
    try:
        m = __import__(mod_name, fromlist=[attr_name])
        return getattr(m, attr_name, None)
    except Exception as e:
        logger.warning(f"Import failed {mod_name}: {e}")
        return None

def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

# === ENDPOINTS ===

@app.route("/")
def serve_dashboard():
    p = ROOT / "dashboard.html"
    return send_from_directory(str(ROOT), "dashboard.html") if p.exists() else ("Not found", 404)

@app.route("/api/health")
def health():
    return jsonify({"service": "forge-dashboard", "status": "ok", "timestamp": _now()})

@app.route("/api/debug")
def debug():
    results = {}
    for mod in ["utils","alpaca_tracker","binance_provider","signals_enhanced","decision_engine_v2","trade_executor"]:
        try:
            __import__(mod)
            results[mod] = "OK"
        except Exception as e:
            results[mod] = f"{type(e).__name__}: {str(e)[:200]}"
    results["sys_path"] = sys.path[:3]
    results["cwd"] = str(Path.cwd())
    return jsonify(results)

@app.route("/api/portfolio")
def api_portfolio():
    try:
        get_client = _import_or_none("alpaca_tracker", "get_alpaca_client")
        get_account = _import_or_none("alpaca_tracker", "get_account_summary")
        get_positions = _import_or_none("alpaca_tracker", "get_positions")
        if not get_client:
            return jsonify({"error": "alpaca_tracker not available"}), 503

        client = get_client()
        if not client:
            return jsonify({"timestamp": _now(), "connected": False,
                "error": "Alpaca unavailable", "account": None, "positions": [], "position_count": 0}), 200

        account = get_account(client) if get_account else None
        positions = get_positions(client) if get_positions else []
        return jsonify({"timestamp": _now(), "connected": True,
            "account": account, "positions": positions, "position_count": len(positions) if positions else 0})
    except Exception as e:
        logger.error(f"/api/portfolio: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/prices")
def api_prices():
    try:
        get_prices = _import_or_none("binance_provider", "get_prices_binance")
        get_rsi = _import_or_none("binance_provider", "get_rsi_all")
        if not get_prices:
            return jsonify({"error": "binance_provider not available"}), 503

        prices = get_prices()
        if not prices:
            return jsonify({"timestamp": _now(), "coins": {}, "error": "Binance unavailable"}), 200

        rsi_data = get_rsi() if get_rsi else {}
        result = {}
        for coin, data in prices.items():
            result[coin] = {
                "price": data.get("price"), "change_24h": data.get("change_24h"),
                "volume_24h": data.get("volume_24h"),
                "rsi": rsi_data.get(coin, {}).get("rsi"),
                "rsi_signal": rsi_data.get(coin, {}).get("signal")
            }
        return jsonify({"timestamp": _now(), "coins": result})
    except Exception as e:
        logger.error(f"/api/prices: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/decision")
def api_decision():
    try:
        get_signals = _import_or_none("binance_provider", "get_enhanced_signals_binance")
        get_prices = _import_or_none("binance_provider", "get_prices_binance")
        generate = _import_or_none("decision_engine_v2", "generate_conviction_v2")
        if not all([get_signals, get_prices, generate]):
            return jsonify({"error": "decision engine not available"}), 503

        enhanced_signals = get_signals()
        if not enhanced_signals:
            return jsonify({"timestamp": _now(), "current": None, "error": "Signals unavailable"}), 200

        prices = get_prices() or {}
        alerts = []
        for cid, d in prices.items():
            chg = d.get("change_24h", 0)
            if abs(chg) >= 5:
                alerts.append({"coin": cid.upper(), "change_24h": chg, "price": d.get("price")})
        conviction = generate([], {"alerts": alerts, "coins": prices}, [], enhanced_signals)
        return jsonify({"timestamp": _now(), "current": conviction})
    except Exception as e:
        logger.error(f"/api/decision: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/dry-run")
def api_dry_run():
    try:
        from supabase_client import get_dry_run_summary, get_all_trades
        summary = get_dry_run_summary()
        if summary and summary.get("total_trades", 0) > 0:
            open_trades = get_all_trades(outcome="OPEN", limit=20)
            summary["open_positions"] = len(open_trades)
            summary["open_positions_detail"] = [{"coin": t.get("coin"), "symbol": t.get("symbol"),
                "entry_price": t.get("entry_price"), "quantity": t.get("quantity"),
                "conviction": t.get("conviction_level")} for t in open_trades]
            summary["source"] = "supabase"
            return jsonify(summary)
    except Exception as e:
        logger.warning(f"Supabase fallback: {e}")

    # Fallback local
    lhp = _import_or_none("trade_executor", "load_trade_history")
    gds = _import_or_none("trade_executor", "generate_dry_run_summary")
    if not lhp or not gds:
        return jsonify({"error": "trade_executor not available"}), 503
    history = lhp()
    summary = gds(history)
    summary["source"] = "local_json"
    return jsonify(summary)


@app.route("/api/performance")
def api_performance():
    """Alias for /api/dry-run — dashboard format."""
    return api_dry_run()

@app.route("/api/trades")
def api_trades():
    try:
        limit = request.args.get("limit", default=20, type=int)
        outcome = request.args.get("outcome")
        from supabase_client import get_all_trades
        trades = get_all_trades(outcome=outcome, limit=limit)
        return jsonify({"timestamp": _now(), "total": len(trades), "trades": trades, "source": "supabase"})
    except Exception:
        pass

    history_file = DATA_DIR / "trade_history.json"
    trades = json.loads(history_file.read_text(encoding="utf-8")) if history_file.exists() else []
    return jsonify({"timestamp": _now(), "total": len(trades), "trades": trades[-20:], "source": "local_json"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"FORGE API starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)

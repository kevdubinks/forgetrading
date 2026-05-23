# api_server.py v1 — Serveur HTTP local pour dashboard trading
# ⚙️ FORGE | Projet: Trading Agent Phase 4
# Objectif: Servir les donnees Alpaca/Binance/RSI en JSON sur localhost:8080
# Securite: localhost uniquement, cles API jamais exposes dans les reponses
# Zero dependance externe: http.server + threading (stdlib Python)

import json
import os
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

# === Configuration ===
HOST = "127.0.0.1"   # localhost uniquement — securite
PORT = 8080
SCRIPTS_DIR = Path("C:/FORGE/trading/scripts")
sys.path.insert(0, str(SCRIPTS_DIR))

# Cache minimal pour eviter de spammer les APIs
_cache = {}
_cache_ttl = 60  # secondes
_cache_lock = threading.Lock()

# === Chargement des cles API depuis ENV uniquement (pas de fallback fichier) ===
ETHERSCAN_KEY = os.environ.get("ETHERSCAN_API_KEY", "")
ALPACA_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "")


def get_cached(key, fetcher):
    """Cache thread-safe avec TTL. Evite d'appeler l'API a chaque requete."""
    with _cache_lock:
        now = time.time()
        if key in _cache and (now - _cache[key]["ts"]) < _cache_ttl:
            return _cache[key]["data"]
    data = fetcher()
    with _cache_lock:
        _cache[key] = {"ts": time.time(), "data": data}
    return data


# === Handlers de donnees ===

def fetch_portfolio():
    """Donnees Alpaca: account + positions + market status."""
    if not ALPACA_KEY or not ALPACA_SECRET:
        return {"error": "Alpaca API keys not configured", "portfolio_value": 0, "buying_power": 0, "positions": []}
    
    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(api_key=ALPACA_KEY, secret_key=ALPACA_SECRET, paper=True)
        account = client.get_account()
        positions = client.get_all_positions()
        clock = client.get_clock()
        
        return {
            "portfolio_value": float(account.portfolio_value),
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "equity": float(account.equity),
            "long_market_value": float(account.long_market_value),
            "status": str(account.status),
            "market_open": clock.is_open,
            "next_open": str(clock.next_open),
            "next_close": str(clock.next_close),
            "positions": [{
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc)
            } for p in positions],
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "portfolio_value": 0, "buying_power": 0, "positions": []}


def fetch_prices():
    """Prix en temps reel via Binance (pas de cache dans dashboard.py)."""
    try:
        from binance_provider import get_enhanced_signals_binance
        from utils import load_settings
        settings = load_settings()
        signals = get_enhanced_signals_binance(settings)
        coins = signals.get("coins", {})
        return {
            coin_id: {
                "price": cs.get("price", 0),
                "change_24h": cs.get("change_24h", 0),
                "rsi": cs.get("rsi"),
                "volume_ratio": cs.get("volume_ratio"),
            }
            for coin_id, cs in coins.items()
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_signals():
    """Signaux etendus: Fear & Greed, BTC Dominance, decision history."""
    try:
        from signals_enhanced import get_fear_greed
        fg = get_fear_greed()
        
        from utils import load_json, DATA_DIR
        decisions = load_json(DATA_DIR / "decisions_v2.json") or []
        last = decisions[-1] if decisions else {}
        
        return {
            "fear_greed": fg,
            "last_decision": {
                "score": last.get("score", 0),
                "level": last.get("level", "CALM"),
                "action": last.get("action", "HOLD"),
                "components": last.get("components", {}),
                "details": last.get("details", {}),
                "reasons": last.get("reasons", []),
                "timestamp": last.get("timestamp", "")
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_wallets():
    """Soldes wallets tracks via Etherscan."""
    if not ETHERSCAN_KEY:
        return {"error": "Etherscan API key not configured", "wallets": []}
    
    try:
        from wallet_tracker import track_all_wallets
        from utils import load_settings
        settings = load_settings()
        data = track_all_wallets(settings)
        return {"wallets": data, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"error": str(e), "wallets": []}


def fetch_performance():
    """Statistiques de trading: resume + historique recent."""
    try:
        from utils import load_json, DATA_DIR
        summary = load_json(DATA_DIR / "dry_run_summary.json") or {}
        history = load_json(DATA_DIR / "trade_history.json") or []
        # 10 derniers trades (tries par date)
        recent = sorted(history, key=lambda t: t.get("entry_time", ""), reverse=True)[:10]
        return {
            "summary": summary,
            "recent_trades": recent,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "summary": {}, "recent_trades": []}


def fetch_health():
    """Health check + statut des APIs."""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "apis": {
            "alpaca": bool(ALPACA_KEY and ALPACA_SECRET),
            "etherscan": bool(ETHERSCAN_KEY),
            "binance": True  # pas de cle necessaire
        },
        "cache_ttl": _cache_ttl
    }


# === Routeur HTTP ===
ROUTES = {
    "/api/portfolio":   fetch_portfolio,
    "/api/prices":      fetch_prices,
    "/api/signals":     fetch_signals,
    "/api/wallets":     fetch_wallets,
    "/api/performance": fetch_performance,
    "/api/health":      fetch_health,
}


class DashboardAPIHandler(BaseHTTPRequestHandler):
    """Handler HTTP minimal avec CORS + routage JSON + log console."""

    def log_message(self, format, *args):
        """Log leger dans la console."""
        print(f"[api-server] {self.client_address[0]} — {args[0]}")

    def _send_json(self, data, status=200):
        """Envoie une reponse JSON avec headers CORS."""
        body = json.dumps(data, ensure_ascii=False, indent=2)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_OPTIONS(self):
        """Preflight CORS — repond juste les headers."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        """Route les requetes GET vers le bon handler."""
        # Nettoyage du path (enlever query string)
        path = self.path.split("?")[0].rstrip("/")
        
        handler = ROUTES.get(path)
        if handler:
            try:
                data = handler() if "health" in path else get_cached(path, handler)
                self._send_json(data)
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
        elif path == "" or path == "/":
            # Rediriger vers la doc rapide des endpoints
            self._send_json({
                "service": "FORGE Trading API",
                "version": "1.0",
                "endpoints": list(ROUTES.keys())
            })
        else:
            self._send_json({"error": f"Not found: {path}"}, status=404)


def main():
    """Demarre le serveur HTTP."""
    # Verifier que les cles sont en place
    print("=" * 50)
    print("  FORGE Trading API Server v1.0")
    print(f"  Host: {HOST}:{PORT}")
    print("=" * 50)
    print(f"  Alpaca API:    {'[OK] configuree' if ALPACA_KEY else '[!!] manquante'}")
    print(f"  Etherscan API: {'[OK] configuree' if ETHERSCAN_KEY else '[!!] manquante'}")
    print(f"  Binance API:   [OK] publique (pas de cle)")
    print(f"  Cache TTL:     {_cache_ttl}s")
    print("=" * 50)
    print(f"  Endpoints:")
    for route in ROUTES:
        print(f"    http://{HOST}:{PORT}{route}")
    print("=" * 50)
    print("  Ctrl+C pour arreter")
    print()

    server = HTTPServer((HOST, PORT), DashboardAPIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[api-server] Arret demande.")
        server.shutdown()


if __name__ == "__main__":
    main()

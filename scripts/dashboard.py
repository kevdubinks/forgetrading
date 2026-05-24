# dashboard.py v3 — Generateur dashboard HTML avec fetch API live
# ⚙️ FORGE | Projet: Trading Agent Phase 4
# Le HTML genere est autonome: il fetch les donnees depuis api_server.py:8080
# Si l'API n'est pas lancee, le dashboard affiche "API indisponible"
# Auto-refresh: 60s pour les donnees, 300s pour la page entiere

import json, os, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils import load_settings, load_json, DATA_DIR
from binance_provider import get_enhanced_signals_binance
from wallet_tracker import track_all_wallets, get_eth_balance

# === Configuration API server ===
API_BASE = "http://127.0.0.1:8080"

def get_coin_color(change):
    return "#3B6D11" if change > 0 else "#A32D2D" if change < 0 else "#666"

def get_rsi_color(rsi):
    if rsi is None: return "#666"
    if rsi < 30: return "#3B6D11"
    if rsi < 50: return "#639922"
    if rsi < 70: return "#BA7517"
    return "#A32D2D"

def get_conviction_color(score):
    if score >= 75: return ("#3B6D11", "strong", "b-green")
    if score >= 50: return ("#854F0B", "moderate", "b-amber")
    if score >= 30: return ("#BA7517", "weak", "b-amber")
    return ("#666", "calm", "")

def get_fg_color(val):
    if val is None: return "#666"
    if val < 30: return "#3B6D11"
    if val < 60: return "#BA7517"
    return "#A32D2D"

# === Le JavaScript est dans une fonction separee pour eviter les conflits f-string ===
# Toutes les accolades {{ }} sont preservees, __API_BASE__ et __FALLBACK__ sont remplacees
DASHBOARD_JS = """
// ===== DASHBOARD LIVE FETCH =====
(function() {
    var API = "__API_BASE__";
    var FALLBACK = __FALLBACK__;

    var els = {
        portfolio: document.getElementById("pf-portfolio"),
        buyingPower: document.getElementById("pf-buying-power"),
        positions: document.getElementById("pf-positions"),
        positionsLabel: document.getElementById("pf-positions-label"),
        positionsContainer: document.getElementById("positions-container"),
        equity: document.getElementById("pf-equity"),
        apiIndicator: document.getElementById("api-indicator"),
        pricesContainer: document.getElementById("prices-container")
    };

    function coinColor(change) {
        return change > 0 ? "#3B6D11" : change < 0 ? "#A32D2D" : "#666";
    }
    function rsiColor(rsi) {
        if (rsi === null || rsi === undefined) return "#666";
        if (rsi < 30) return "#3B6D11";
        if (rsi < 50) return "#639922";
        if (rsi < 70) return "#BA7517";
        return "#A32D2D";
    }
    function fmtUSD(val) {
        if (val === undefined || val === null) return "...";
        return "$" + val.toLocaleString("en-US", {maximumFractionDigits: 0});
    }
    function fmtPct(val) {
        if (val === undefined || val === null) return "...";
        return (val > 0 ? "+" : "") + val.toFixed(1) + "%";
    }
    function setApiStatus(ok) {
        if (ok) {
            els.apiIndicator.innerHTML = '<span class="api-dot api-dot-ok"></span> API live';
        } else {
            els.apiIndicator.innerHTML = '<span class="api-dot api-dot-err"></span> API indisponible';
        }
    }

    // FETCH: Portfolio Alpaca
    async function fetchPortfolio() {
        try {
            var resp = await fetch(API + "/api/portfolio");
            if (!resp.ok) throw new Error("HTTP " + resp.status);
            var data = await resp.json();
            if (data.error) throw new Error(data.error);

            els.portfolio.innerHTML = fmtUSD(data.portfolio_value);
            els.buyingPower.innerHTML = fmtUSD(data.buying_power);
            var nPos = data.positions ? data.positions.length : 0;
            els.positions.innerHTML = nPos;
            els.positionsLabel.innerHTML = nPos === 0 ? "Aucun trade actif" : nPos + " actives";
            els.equity.innerHTML = "Equity: " + fmtUSD(data.equity) + " · Marché: " + (data.market_open ? "ouvert" : "fermé");

            // Positions detail
            if (nPos > 0) {
                var html = "";
                data.positions.forEach(function(p) {
                    var plColor = p.unrealized_pl >= 0 ? "#4ade80" : "#f87171";
                    html += '<div class="pos-row">' +
                      '<span style="font-weight:500;">' + p.symbol + '</span>' +
                      '<span>' + p.qty + ' @ ' + p.avg_entry_price.toFixed(2) + '</span>' +
                      '<span style="color:' + plColor + ';">' + (p.unrealized_plpc * 100).toFixed(1) + '%</span>' +
                    '</div>';
                });
                els.positionsContainer.innerHTML = html;
            } else {
                els.positionsContainer.innerHTML = '<span style="color: var(--color-text-secondary);">Aucune position ouverte</span>';
            }

            setApiStatus(true);
        } catch (e) {
            console.warn("[dashboard] Portfolio fetch failed:", e.message);
            setApiStatus(false);
            els.portfolio.innerHTML = fmtUSD(FALLBACK.portfolio_value);
            els.buyingPower.innerHTML = fmtUSD(FALLBACK.buying_power);
            els.positions.innerHTML = "0";
            els.positionsLabel.innerHTML = "API indisponible";
            els.positionsContainer.innerHTML = '<span style="color: #f87171;">API Alpaca indisponible — runner api_server.py</span>';
            els.equity.innerHTML = "Equity: indisponible";
        }
    }

    // FETCH: Performance trading
    var perfEls = {
        pnl: document.getElementById("perf-pnl"),
        wr: document.getElementById("perf-wr"),
        rr: document.getElementById("perf-rr"),
        ev: document.getElementById("perf-ev"),
        best: document.getElementById("perf-best"),
        worst: document.getElementById("perf-worst"),
        trades: document.getElementById("perf-trades"),
        history: document.getElementById("perf-trades-history")
    };
    async function fetchPerformance() {
        try {
            var resp = await fetch(API + "/api/performance");
            if (!resp.ok) throw new Error("HTTP " + resp.status);
            var data = await resp.json();
            if (data.error) throw new Error(data.error);
            var s = data.summary || {};

            if (perfEls.pnl) {
                var pnl = s.cumulative_pnl || 0;
                var pnlColor = pnl >= 0 ? "#4ade80" : "#f87171";
                perfEls.pnl.innerHTML = (pnl >= 0 ? "+" : "") + "$" + pnl.toLocaleString("en-US", {maximumFractionDigits: 0});
                perfEls.pnl.style.color = pnlColor;
            }
            if (perfEls.wr) perfEls.wr.innerHTML = (s.win_rate || 0).toFixed(1) + "%";
            if (perfEls.rr) perfEls.rr.innerHTML = (s.r_r_ratio || 0).toFixed(2);
            if (perfEls.ev) {
                var ev = s.expected_value || 0;
                perfEls.ev.innerHTML = (ev >= 0 ? "+" : "") + "$" + ev.toFixed(2);
                perfEls.ev.style.color = ev >= 0 ? "#4ade80" : "#f87171";
            }
            if (perfEls.best && s.best_trade) {
                var bt = s.best_trade;
                perfEls.best.innerHTML = bt.coin.toUpperCase() + " " + (bt.pnl_pct >= 0 ? "+" : "") + bt.pnl_pct.toFixed(1) + "%";
            }
            if (perfEls.worst && s.worst_trade) {
                var wt = s.worst_trade;
                perfEls.worst.innerHTML = wt.coin.toUpperCase() + " " + (wt.pnl_pct >= 0 ? "+" : "") + wt.pnl_pct.toFixed(1) + "%";
            }
            if (perfEls.trades) perfEls.trades.innerHTML = (s.total_trades || 0) + " (" + (s.open_trades || 0) + " ouverts)";

            // Trade history table
            var recent = data.recent_trades || [];
            if (perfEls.history && recent.length > 0) {
                var h = "";
                recent.slice(0, 5).forEach(function(t) {
                    var pnlC = (t.pnl || 0) >= 0 ? "#4ade80" : "#f87171";
                    var status = t.status === "OPEN" ? '<span class="badge b-blue">OPEN</span>' :
                                 t.exit_reason === "TAKE_PROFIT" ? '<span class="badge b-green">TP</span>' :
                                 t.exit_reason === "STOP_LOSS" ? '<span class="badge b-red">SL</span>' :
                                 '<span class="badge b-amber">' + (t.status || "?") + '</span>';
                    var pnlDisp = t.pnl ? (t.pnl >= 0 ? "+$" : "-$") + Math.abs(t.pnl).toFixed(0) : "-";
                    h += '<div class="pos-row">' +
                      '<span>' + t.coin.toUpperCase() + '</span>' +
                      '<span style="font-size:11px;color:var(--color-text-secondary);">' + (t.entry_time || "").substring(0,10) + '</span>' +
                      '<span>' + status + '</span>' +
                      '<span style="color:' + pnlC + ';">' + pnlDisp + '</span>' +
                    '</div>';
                });
                perfEls.history.innerHTML = h;
            } else if (perfEls.history) {
                perfEls.history.innerHTML = '<span style="color:var(--color-text-secondary);font-size:12px;">Aucun trade enregistre</span>';
            }
        } catch (e) {
            console.warn("[dashboard] Performance fetch failed:", e.message);
        }
    }

    // FETCH: Prix Binance
    async function fetchPrices() {
        try {
            var resp = await fetch(API + "/api/prices");
            if (!resp.ok) throw new Error("HTTP " + resp.status);
            var data = await resp.json();
            if (data.error) throw new Error(data.error);

            Object.keys(data).forEach(function(coinId) {
                var cs = data[coinId];
                var priceEl = document.querySelector(".coin-price-" + coinId);
                var changeEl = document.querySelector(".coin-change-" + coinId);
                if (priceEl) priceEl.textContent = "$" + cs.price.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});
                if (changeEl) {
                    changeEl.textContent = fmtPct(cs.change_24h);
                    changeEl.style.background = coinColor(cs.change_24h) + "20";
                    changeEl.style.color = coinColor(cs.change_24h);
                }
            });
        } catch (e) {
            console.warn("[dashboard] Prices fetch failed:", e.message);
        }
    }

    // INIT
    async function refreshAll() {
        await Promise.all([fetchPortfolio(), fetchPrices(), fetchPerformance()]);
    }

    refreshAll();
    setInterval(refreshAll, 60000);
})();
"""

def generate_dashboard(settings=None):
    """Genere le dashboard HTML avec donnees statiques (prix/signaux)
    et JS fetch pour les donnees live (Alpaca portfolio)."""
    if settings is None: settings = load_settings()
    now = datetime.now()

    # === DONNEES STATIQUES (generees au moment du cron) ===
    signals = get_enhanced_signals_binance(settings)
    wallets = track_all_wallets(settings)

    # Decision history
    decisions = load_json(DATA_DIR / "decisions_v2.json") or []
    last = decisions[-1] if decisions else {}

    # Fear & Greed
    fg = signals.get("fear_greed", {})
    fg_val = fg["current"]["value"] if fg else 50
    fg_class = fg["current"]["class"] if fg else "Neutral"

    # Conviction
    score = last.get("score", 0)
    level = last.get("level", "CALM")
    comps = last.get("components", {})
    fg_score = comps.get("sentiment", 0)
    rsi_score = comps.get("rsi", 0)
    btc_score = comps.get("btc_dominance", 0)
    mom_score = comps.get("momentum", 0)
    details = last.get("details", {})
    avg_rsi = details.get("avg_rsi", 0) or 0
    btc_dom = signals.get("btc_dominance", 50)

    cv_color, cv_level, cv_badge = get_conviction_color(score)

    # === Coins HTML ===
    coins_rows = []
    for coin_id, cs in signals.get("coins", {}).items():
        name = coin_id.capitalize()
        price = cs.get("price") or 0
        change = cs.get("change_24h") or 0
        rsi = cs.get("rsi")
        chg_c = get_coin_color(change)
        chg_sign = "+" if change > 0 else ""
        rsi_badge = f'<span class="badge b-red">RSI {rsi}</span>' if rsi and rsi > 70 else ""
        coins_rows.append(f"""      <div class="row">
        <span style="font-size: 13px; font-weight: 500; color: var(--color-text-primary);">{name}</span>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="coin-price-{coin_id}" style="font-size: 13px; color: var(--color-text-secondary);">${price:,.2f}</span>
          <span class="coin-change-{coin_id} badge" style="background: {chg_c}20; color: {chg_c};">{chg_sign}{change:+.1f}%</span>
          {rsi_badge}
        </div>
      </div>""")
    coins_html = "\n".join(coins_rows)

    # === Signals reasoning ===
    signal_items = []
    for reason in last.get("reasons", []):
        dot_color = "#EF9F27"
        if "RSI" in reason: dot_color = "#639922"
        elif "MOMENTUM" in reason: dot_color = "#E24B4A"
        signal_items.append(f'''        <div style="display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--color-text-primary);">
          <div class="sig-dot" style="background: {dot_color};"></div>{reason}
        </div>''')
    signals_html = "\n".join(signal_items) if signal_items else '<div style="font-size:13px;color:var(--color-text-secondary);">Aucun signal actif</div>'

    # === Wallets HTML ===
    wallets_rows = []
    settings_wallets = settings.get("wallet_tracking", {}).get("ethereum_wallets", [])
    api_key = os.environ.get("ETHERSCAN_API_KEY", "")
    for w in settings_wallets[:3]:
        addr = w["address"]
        label = w["label"]
        short = f"{addr[:6]}…{addr[-4:]}"
        bal = get_eth_balance(addr, api_key) if api_key else None
        bal_str = f"{bal:.2f} ETH" if bal else "?"
        wallets_rows.append(f"""      <div class="row">
        <div>
          <p style="font-size: 13px; font-weight: 500; margin: 0; color: var(--color-text-primary);">{label}</p>
          <p style="font-size: 11px; color: var(--color-text-secondary); margin: 2px 0 0;">{short}</p>
        </div>
        <div style="text-align: right;">
          <p style="font-size: 13px; font-weight: 500; margin: 0; color: var(--color-text-primary);">{bal_str}</p>
          <span class="badge b-green">0 alerte</span>
        </div>
      </div>""")
    wallets_html = "\n".join(wallets_rows)

    # === RSI cap status ===
    rsi_capped = any(cs.get("rsi") and cs["rsi"] > 70 for cs in signals.get("coins", {}).values())
    mom_status = "RSI cap" if rsi_capped else ""

    # === Fallback data pour le JS (si API down) ===
    fallback = {"portfolio_value": 0, "buying_power": 0, "cash": 0, "positions": []}
    fallback_json = json.dumps(fallback)

    # === Injecter les valeurs dynamiques dans le JS ===
    js_code = DASHBOARD_JS.replace("__API_BASE__", API_BASE)
    js_code = js_code.replace("__FALLBACK__", fallback_json)

    # === GENERATION HTML ===
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="300">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FORGE Trading Dashboard</title>
<style>
:root {{ --color-background-primary: #0d0d12; --color-background-secondary: #14141c; --color-border-tertiary: #2a2a3a; --color-text-primary: #e8e8ed; --color-text-secondary: #8888a0; --border-radius-md: 8px; --border-radius-lg: 12px; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background: #0a0a0f; color: var(--color-text-primary); padding: 1.5rem; min-height: 100vh; }}
.grid4 {{ display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 10px; margin-bottom: 1.5rem; }}
.grid2 {{ display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; margin-bottom: 1.5rem; }}
.grid3 {{ display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 10px; margin-bottom: 1.5rem; }}
.mcard {{ background: var(--color-background-secondary); border-radius: var(--border-radius-md); padding: 1rem; }}
.card {{ background: var(--color-background-primary); border: 0.5px solid var(--color-border-tertiary); border-radius: var(--border-radius-lg); padding: 1rem 1.25rem; }}
.mlabel {{ font-size: 12px; color: var(--color-text-secondary); margin: 0 0 4px; }}
.mval {{ font-size: 22px; font-weight: 500; margin: 0; color: var(--color-text-primary); }}
.msub {{ font-size: 12px; margin: 2px 0 0; }}
.badge {{ display: inline-block; font-size: 11px; font-weight: 500; padding: 2px 8px; border-radius: var(--border-radius-md); }}
.b-green {{ background: #EAF3DE20; color: #4ade80; }}
.b-amber {{ background: #FAEEDA20; color: #facc15; }}
.b-red {{ background: #FCEBEB20; color: #f87171; }}
.b-blue {{ background: #E6F1FB20; color: #60a5fa; }}
.row {{ display: flex; align-items: center; justify-content: space-between; padding: 8px 0; border-bottom: 0.5px solid var(--color-border-tertiary); }}
.row:last-child {{ border-bottom: none; }}
.section-title {{ font-size: 11px; font-weight: 500; color: var(--color-text-secondary); text-transform: uppercase; letter-spacing: 0.06em; margin: 0 0 10px; }}
.bar-wrap {{ background: var(--color-background-secondary); border-radius: 4px; height: 6px; flex: 1; margin: 0 10px; }}
.bar-fill {{ height: 6px; border-radius: 4px; }}
.sig-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
.cron-pill {{ display: inline-flex; align-items: center; gap: 6px; font-size: 12px; background: var(--color-background-secondary); border-radius: 20px; padding: 4px 12px; color: var(--color-text-secondary); border: 0.5px solid var(--color-border-tertiary); }}
button {{ background: var(--color-background-secondary); border: 0.5px solid var(--color-border-tertiary); color: var(--color-text-primary); padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; }}
.api-status {{ font-size: 10px; display: inline-flex; align-items: center; gap: 4px; }}
.api-dot {{ width: 6px; height: 6px; border-radius: 50%; display: inline-block; }}
.api-dot-ok {{ background: #4ade80; }}
.api-dot-err {{ background: #f87171; }}
.api-dot-pending {{ background: #facc15; animation: pulse 1s infinite; }}
@keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.3; }} }}
.spinner {{ display: inline-block; width: 14px; height: 14px; border: 2px solid var(--color-border-tertiary); border-top-color: var(--color-text-secondary); border-radius: 50%; animation: spin 0.8s linear infinite; }}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
.pos-row {{ display: flex; align-items: center; justify-content: space-between; padding: 4px 0; font-size: 12px; }}
.sr-only {{ position: absolute; width: 1px; height: 1px; overflow: hidden; }}
</style>
</head>
<body>
<h2 class="sr-only">Dashboard trading FORGE — {now.strftime('%d/%m/%Y %H:%M')}</h2>

<div style="padding: 1rem 0 0;">
  <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.25rem;">
    <div>
      <p style="font-size: 18px; font-weight: 500; margin: 0; color: var(--color-text-primary);">FORGE — rapport trading</p>
      <p style="font-size: 13px; color: var(--color-text-secondary); margin: 4px 0 0;">
        {now.strftime('%d %B %Y · %H:%M')}
        · <span id="api-indicator" class="api-status"><span class="api-dot api-dot-pending"></span> connexion...</span>
      </p>
    </div>
    <div style="display: flex; gap: 8px; align-items: center;">
      <span class="cron-pill">⏰ cron 14:30</span>
    </div>
  </div>

  <!-- BLOC 1: Portfolio Alpaca (FETCH LIVE) -->
  <div class="grid4">
    <div class="mcard">
      <p class="mlabel">Portefeuille paper</p>
      <p class="mval" id="pf-portfolio">$<span class="spinner"></span></p>
      <p class="msub" style="color: var(--color-text-secondary);">Alpaca Paper</p>
    </div>
    <div class="mcard">
      <p class="mlabel">Buying power</p>
      <p class="mval" id="pf-buying-power">$<span class="spinner"></span></p>
      <p class="msub" style="color: var(--color-text-secondary);">2× levier dispo</p>
    </div>
    <div class="mcard">
      <p class="mlabel">Positions</p>
      <p class="mval" id="pf-positions"><span class="spinner"></span></p>
      <p class="msub" style="color: var(--color-text-secondary);" id="pf-positions-label">chargement...</p>
    </div>
    <div class="mcard">
      <p class="mlabel">Conviction du jour</p>
      <p class="mval" style="color: {cv_color};">{score}</p>
      <p class="msub" style="color: {cv_color};">{level}</p>
    </div>
  </div>

  <!-- BLOC 2: Decision Engine + Prix -->
  <div class="grid2">
    <div class="card">
      <p class="section-title">Decision engine v2</p>
      <div style="margin-bottom: 1rem;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
          <span style="font-size: 13px; color: var(--color-text-secondary);">Score global</span>
          <span style="font-size: 20px; font-weight: 500; color: {cv_color};">{score} / 100</span>
        </div>
        <div style="background: var(--color-background-secondary); border-radius: 4px; height: 8px;">
          <div style="width: {score}%; height: 8px; border-radius: 4px; background: {cv_color};"></div>
        </div>
        <p style="font-size: 11px; color: var(--color-text-secondary); margin: 4px 0 0;">Seuil paper trade : 50+ · Seuil fort : 75+</p>
      </div>
      <div>
        <div style="display: flex; align-items: center; gap: 8px; padding: 7px 0; border-bottom: 0.5px solid var(--color-border-tertiary);">
          <span style="font-size: 12px; color: var(--color-text-secondary); width: 120px;">Fear &amp; Greed</span>
          <div class="bar-wrap"><div class="bar-fill" style="width: {fg_score/25*100:.0f}%; background: {get_fg_color(fg_val)};"></div></div>
          <span style="font-size: 13px; font-weight: 500; width: 40px; text-align: right; color: var(--color-text-primary);">{fg_score}/25</span>
          <span class="badge b-green">{fg_class}</span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px; padding: 7px 0; border-bottom: 0.5px solid var(--color-border-tertiary);">
          <span style="font-size: 12px; color: var(--color-text-secondary); width: 120px;">RSI moyen</span>
          <div class="bar-wrap"><div class="bar-fill" style="width: {rsi_score/25*100:.0f}%; background: {get_rsi_color(avg_rsi)};"></div></div>
          <span style="font-size: 13px; font-weight: 500; width: 40px; text-align: right; color: var(--color-text-primary);">{rsi_score}/25</span>
          <span class="badge b-blue">{avg_rsi:.1f}</span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px; padding: 7px 0; border-bottom: 0.5px solid var(--color-border-tertiary);">
          <span style="font-size: 12px; color: var(--color-text-secondary); width: 120px;">BTC dominance</span>
          <div class="bar-wrap"><div class="bar-fill" style="width: {btc_score/10*100:.0f}%; background: #BA7517;"></div></div>
          <span style="font-size: 13px; font-weight: 500; width: 40px; text-align: right; color: var(--color-text-primary);">{btc_score}/10</span>
          <span class="badge b-amber">{btc_dom}%</span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px; padding: 7px 0;">
          <span style="font-size: 12px; color: var(--color-text-secondary); width: 120px;">Momentum</span>
          <div class="bar-wrap"><div class="bar-fill" style="width: {mom_score/25*100:.0f}%; background: #BA7517;"></div></div>
          <span style="font-size: 13px; font-weight: 500; width: 40px; text-align: right; color: var(--color-text-primary);">{mom_score}/25</span>
          <span class="badge {'b-red' if mom_status else ''}">{mom_status}</span>
        </div>
      </div>
    </div>

    <div class="card">
      <p class="section-title">Prix crypto 24h</p>
      <div id="prices-container">
{coins_html}
      </div>
      <div style="margin-top: 12px; padding-top: 10px; border-top: 0.5px solid var(--color-border-tertiary);">
        <p class="section-title" style="margin-bottom: 6px;">Trending</p>
        <div style="display: flex; flex-wrap: wrap; gap: 6px;">
          <span class="badge b-amber">MAJ toutes les 60s</span>
        </div>
      </div>
    </div>
  </div>

  <!-- BLOC 2.5: Performance trading (FETCH LIVE) -->
  <div class="grid4" style="margin-bottom: 1.5rem;">
    <div class="mcard">
      <p class="mlabel">PnL cumule</p>
      <p class="mval" id="perf-pnl" style="color: var(--color-text-primary);">$<span class="spinner"></span></p>
      <p class="msub" style="color: var(--color-text-secondary);">depuis lancement</p>
    </div>
    <div class="mcard">
      <p class="mlabel">Win rate</p>
      <p class="mval" id="perf-wr"><span class="spinner"></span></p>
      <p class="msub" style="color: var(--color-text-secondary);" id="perf-trades">trades: ...</p>
    </div>
    <div class="mcard">
      <p class="mlabel">R:R ratio</p>
      <p class="mval" id="perf-rr"><span class="spinner"></span></p>
      <p class="msub" style="color: var(--color-text-secondary);">Avg Win / Avg Loss</p>
    </div>
    <div class="mcard">
      <p class="mlabel">Expected value</p>
      <p class="mval" id="perf-ev">$<span class="spinner"></span></p>
      <p class="msub" style="color: var(--color-text-secondary);">$/trade moyen</p>
    </div>
  </div>

  <!-- BLOC 3: Positions + Signaux + Wallets -->
  <div class="grid3">
    <div class="card">
      <p class="section-title">Signaux actifs</p>
      <div style="display: flex; flex-direction: column; gap: 8px;">
{signals_html}
      </div>
    </div>

    <div class="card">
      <p class="section-title">Positions Alpaca</p>
      <div id="positions-container" style="font-size: 13px; color: var(--color-text-secondary);">
        <span class="spinner"></span> chargement...
      </div>
      <div style="margin-top: 10px; padding-top: 10px; border-top: 0.5px solid var(--color-border-tertiary);">
        <p style="font-size: 12px; color: var(--color-text-secondary); margin: 0;" id="pf-equity">Equity: ...</p>
      </div>
    </div>

    <div class="card">
      <p class="section-title">Wallet tracker</p>
{wallets_html}
      <div style="margin-top: 10px; padding-top: 10px; border-top: 0.5px solid var(--color-border-tertiary);">
        <p style="font-size: 12px; color: var(--color-text-secondary); margin: 0;">Etherscan V2</p>
      </div>
    </div>
  </div>

  <!-- Modules actifs -->
  <div style="margin-bottom: 1rem;">
    <div class="card">
      <p class="section-title">Modules actifs</p>
      <div style="display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 2px;">
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 0;">
          <span style="color: var(--color-text-secondary); font-size: 12px;">News collector</span><span class="badge b-green">RSS + Reddit</span></div>
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 0;">
          <span style="color: var(--color-text-secondary); font-size: 12px;">Wallet tracker</span><span class="badge b-green">Etherscan V2</span></div>
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 0;">
          <span style="color: var(--color-text-secondary); font-size: 12px;">Price tracker</span><span class="badge b-green">Binance</span></div>
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 0;">
          <span style="color: var(--color-text-secondary); font-size: 12px;">Decision engine</span><span class="badge b-green">v2 · 4 criteres</span></div>
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 0;">
          <span style="color: var(--color-text-secondary); font-size: 12px;">Trade executor</span><span class="badge b-green">paper auto</span></div>
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 0;">
          <span style="color: var(--color-text-secondary); font-size: 12px;">API server</span><span class="badge b-green">localhost:8080</span></div>
      </div>
    </div>
  </div>

  <!-- BLOC 4: Historique trades recent -->
  <div class="grid2" style="margin-bottom: 1rem;">
    <div class="card">
      <p class="section-title">Historique trades (5 derniers)</p>
      <div id="perf-trades-history" style="font-size: 12px; color: var(--color-text-secondary);">
        <span class="spinner"></span> chargement...
      </div>
    </div>
    <div class="card">
      <p class="section-title">Best / Worst trades</p>
      <div style="display: flex; gap: 12px;">
        <div style="flex: 1;">
          <p style="font-size: 11px; color: var(--color-text-secondary); margin: 0 0 4px;">Best</p>
          <p style="font-size: 15px; font-weight: 500; margin: 0; color: #4ade80;" id="perf-best">...</p>
        </div>
        <div style="flex: 1;">
          <p style="font-size: 11px; color: var(--color-text-secondary); margin: 0 0 4px;">Worst</p>
          <p style="font-size: 15px; font-weight: 500; margin: 0; color: #f87171;" id="perf-worst">...</p>
        </div>
      </div>
      <div style="margin-top: 12px; padding-top: 10px; border-top: 0.5px solid var(--color-border-tertiary);">
        <p style="font-size: 11px; color: var(--color-text-secondary); margin: 0;">
          Mode B — full paper auto · Seuils: 50+ (3%) / 75+ (5%)
        </p>
      </div>
    </div>
  </div>

  <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; font-size: 12px; color: var(--color-text-secondary); border-top: 0.5px solid var(--color-border-tertiary);">
    <span>Aucun trade reel — confirmation humaine obligatoire · max 5%/position · stop-loss -10%</span>
    <span>FORGE v3.2 · {now.strftime('%H:%M')}</span>
  </div>
</div>

<script>
{js_code}
</script>
</body>
</html>"""

    path = Path(__file__).resolve().parent.parent / "dashboard.html"
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Dashboard: {path}")
    print(f"  -> Ouvre le fichier dans le navigateur")
    print(f"  -> Demarre l'API: python C:\\FORGE\\trading\\scripts\\api_server.py")
    return path

if __name__ == "__main__":
    generate_dashboard()

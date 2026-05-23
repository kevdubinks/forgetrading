# supabase_client.py — Abstraction Supabase avec fallback JSON local
# Mode: Supabase si SUPABASE_URL+SUPABASE_KEY sont definis, sinon JSON local.
# Utilise par: trade_executor, report_generator, api/server.py

import os
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger("forge-supabase")

# === Chemins ===
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# === Fallback local JSON ===
TRADE_HISTORY_FILE = DATA_DIR / "trade_history.json"
DRY_RUN_FILE = DATA_DIR / "dry_run_summary.json"
DECISIONS_FILE = DATA_DIR / "decisions_v2.json"


def _now_iso():
    """Timestamp ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def _get_supabase():
    """Retourne le client Supabase ou None si non configure."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except ImportError:
        logger.warning("supabase package not installed — fallback to local JSON")
        return None
    except Exception as e:
        logger.warning(f"Supabase init failed: {e} — fallback to local JSON")
        return None


# =====================================================================
# TRADES
# =====================================================================

def insert_trade(trade: dict):
    """Insere un trade. Supabase ou JSON local."""
    trade["created_at"] = _now_iso()
    supabase = _get_supabase()

    if supabase:
        try:
            # Nettoyer les cles non-SQL (None -> null en JSON)
            clean = {k: v for k, v in trade.items() if v is not None or k in ("exit_price", "exit_time", "pnl", "pnl_pct", "exit_reason")}
            result = supabase.table("trades").insert(clean).execute()
            logger.info(f"Supabase: trade inserted ({trade.get('id')})")
            return result
        except Exception as e:
            logger.warning(f"Supabase insert failed: {e} — fallback to local")

    # Fallback local
    trades = _read_local_json(TRADE_HISTORY_FILE, [])
    trades.append(trade)
    _write_local_json(TRADE_HISTORY_FILE, trades)
    logger.info(f"Local: trade saved ({trade.get('id')})")
    return None


def update_trade(trade_id: str, updates: dict):
    """Met a jour un trade existant (ex: exit_price, pnl)."""
    updates["updated_at"] = _now_iso()
    supabase = _get_supabase()

    if supabase:
        try:
            result = supabase.table("trades").update(updates).eq("id", trade_id).execute()
            logger.info(f"Supabase: trade updated ({trade_id})")
            return result
        except Exception as e:
            logger.warning(f"Supabase update failed: {e} — fallback to local")

    # Fallback local
    trades = _read_local_json(TRADE_HISTORY_FILE, [])
    for t in trades:
        if t.get("id") == trade_id:
            t.update(updates)
            break
    _write_local_json(TRADE_HISTORY_FILE, trades)
    return None


def get_all_trades(outcome: str = None, limit: int = 50):
    """Recupere les trades. Filtre optionnel par outcome/status."""
    supabase = _get_supabase()

    if supabase:
        try:
            query = supabase.table("trades").select("*").order("created_at", desc=True).limit(limit)
            if outcome:
                query = query.eq("status" if outcome in ("OPEN",) else "outcome", outcome)
            result = query.execute()
            return result.data
        except Exception as e:
            logger.warning(f"Supabase fetch failed: {e} — fallback to local")

    # Fallback local
    trades = _read_local_json(TRADE_HISTORY_FILE, [])
    if outcome:
        trades = [t for t in trades if t.get("status") == outcome or t.get("outcome") == outcome]
    return list(reversed(trades))[-limit:]


# =====================================================================
# DRY RUN SUMMARY
# =====================================================================

def upsert_dry_run_summary(summary: dict):
    """Insere ou met a jour le resume de performance (1 seule ligne)."""
    summary["updated_at"] = _now_iso()
    supabase = _get_supabase()

    if supabase:
        try:
            # Upsert: delete old, insert new (simpler than ON CONFLICT)
            supabase.table("dry_run_summary").delete().neq("id", -1).execute()
            clean = {
                "id": 1,
                "updated_at": summary["updated_at"],
                "total_trades": summary.get("total_trades", 0),
                "closed_trades": summary.get("closed_trades", 0),
                "cumulative_pnl": summary.get("cumulative_pnl", 0),
                "win_rate": summary.get("win_rate", 0),
                "r_r_ratio": summary.get("r_r_ratio", 0),
                "expected_value": summary.get("expected_value", 0),
                "best_trade": summary.get("best_trade"),
                "worst_trade": summary.get("worst_trade"),
            }
            result = supabase.table("dry_run_summary").insert(clean).execute()
            logger.info("Supabase: dry_run_summary upserted")
            return result
        except Exception as e:
            logger.warning(f"Supabase upsert failed: {e} — fallback to local")

    # Fallback local
    _write_local_json(DRY_RUN_FILE, summary)
    logger.info("Local: dry_run_summary saved")
    return None


def get_dry_run_summary():
    """Recupere le resume de performance."""
    supabase = _get_supabase()

    if supabase:
        try:
            result = supabase.table("dry_run_summary").select("*").limit(1).execute()
            if result.data:
                return result.data[0]
        except Exception as e:
            logger.warning(f"Supabase fetch failed: {e} — fallback to local")

    # Fallback local
    return _read_local_json(DRY_RUN_FILE, {})


# =====================================================================
# REPORTS
# =====================================================================

def insert_report(report: dict):
    """Insere un rapport quotidien."""
    report["created_at"] = _now_iso()
    supabase = _get_supabase()

    if supabase:
        try:
            result = supabase.table("reports").insert(report).execute()
            logger.info(f"Supabase: report inserted ({report.get('date')})")
            return result
        except Exception as e:
            logger.warning(f"Supabase insert failed: {e} — fallback to local")

    # Fallback local
    reports_file = DATA_DIR / "reports.json"
    reports = _read_local_json(reports_file, [])
    reports.append(report)
    _write_local_json(reports_file, reports)
    logger.info(f"Local: report saved ({report.get('date')})")
    return None


def get_latest_report():
    """Recupere le dernier rapport."""
    supabase = _get_supabase()
    if supabase:
        try:
            result = supabase.table("reports").select("*").order("created_at", desc=True).limit(1).execute()
            if result.data:
                return result.data[0]
        except Exception as e:
            logger.warning(f"Supabase fetch failed: {e} — fallback to local")

    reports = _read_local_json(DATA_DIR / "reports.json", [])
    return reports[-1] if reports else None


# =====================================================================
# HELPERS — JSON local
# =====================================================================

def _read_local_json(path: Path, default):
    """Lit un fichier JSON local."""
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Read error {path}: {e}")
    return default


def _write_local_json(path: Path, data):
    """Ecrit un fichier JSON local (atomique via temp file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        tmp.replace(path)
    except Exception as e:
        logger.error(f"Write error {path}: {e}")
        if tmp.exists():
            tmp.unlink(missing_ok=True)

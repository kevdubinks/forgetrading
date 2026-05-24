# utils.py — Utilitaires partages pour l'agent de trading
# Auteur: FORGE | Projet: Trading Agent v2.1
# Compatible Windows + Linux (Render)

import json, os, logging
from datetime import datetime, timezone
from pathlib import Path

# === Configuration des chemins (dynamique, pas de hardcode) ===
BASE_DIR = Path(__file__).resolve().parent.parent  # scripts/.. = racine projet
CONFIG_PATH = BASE_DIR / 'config' / 'settings.json'
DATA_DIR = BASE_DIR / 'data'
REPORTS_DIR = BASE_DIR / 'reports'
NEWS_CACHE = DATA_DIR / 'news_cache.json'
WALLET_STATE = DATA_DIR / 'wallet_state.json'

# === Logging ===
LOG_FILE = DATA_DIR / 'agent.log'

def setup_logging(name='trading_agent'):
    """Setup logging: stream toujours, fichier si le dossier data/ existe."""
    handlers = [logging.StreamHandler()]
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(LOG_FILE, encoding='utf-8'))
    except Exception:
        pass  # Pas de fichier log si dossier inaccessible (ex: Render read-only)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=handlers
    )
    return logging.getLogger(name)

# === Helpers JSON ===
def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_settings():
    return load_json(CONFIG_PATH)

# === Formatage ===
def now_iso():
    return datetime.now(timezone.utc).isoformat()

def today_str():
    return datetime.now().strftime('%Y-%m-%d')

def ts_to_date(ts):
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')

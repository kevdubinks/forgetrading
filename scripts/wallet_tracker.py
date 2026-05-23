# wallet_tracker.py — Surveillance de wallets Ethereum (whales/influenceurs)
# Auteur: FORGE | Projet: Trading Agent Phase 1
# Utilise l'API Etherscan pour tracker les transactions des wallets configures
# Alerte si mouvement > min_transfer_eth ou variation > alert_move_pct

import json, os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.request
import sys
sys.path.insert(0, str(Path(__file__).parent))

from utils import load_json, save_json, now_iso, WALLET_STATE, setup_logging, load_settings

logger = setup_logging('wallet_tracker')

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) TradingAgent/1.0'

def get_etherscan_api_key():
    """Recupere la cle API Etherscan depuis les variables d'environnement."""
    key = os.environ.get('ETHERSCAN_API_KEY', '')
    if not key:
        settings = load_settings()
        key = settings.get('api_keys', {}).get('etherscan', '')
    return key

def get_eth_balance(address, api_key):
    """Solde ETH d'un wallet."""
    url = f'https://api.etherscan.io/v2/api?chainid=1&module=account&action=balance&address={address}&tag=latest&apikey={api_key}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if data.get('status') == '1':
                return int(data['result']) / 1e18  # Wei -> ETH
    except Exception as e:
        logger.warning(f'Etherscan balance {address[:10]}...: {e}')
    return None

def get_recent_transactions(address, api_key, limit=20):
    """Liste des transactions recentes (normales + ERC20)."""
    url = (f'https://api.etherscan.io/v2/api?chainid=1&module=account&action=txlist'
           f'&address={address}&startblock=0&endblock=99999999'
           f'&page=1&offset={limit}&sort=desc&apikey={api_key}')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if data.get('status') == '1':
                return data['result']
    except Exception as e:
        logger.warning(f'Etherscan tx {address[:10]}...: {e}')
    return []

def analyze_wallet_activity(wallet, api_key, min_eth, alert_pct):
    """Analyse l'activite recente d'un wallet et genere des alertes."""
    address = wallet['address']
    label = wallet['label']
    alerts = []
    
    tx_list = get_recent_transactions(address, api_key)
    if not tx_list:
        return alerts

    total_volume_eth = 0
    for tx in tx_list[:20]:
        value_eth = int(tx['value']) / 1e18
        if value_eth > 0:
            total_volume_eth += value_eth

    balance = get_eth_balance(address, api_key) or 0

    # Comparer avec l'etat precedent
    prev_state = load_json(WALLET_STATE) or {}
    prev_entry = prev_state.get(address, {})
    prev_balance = prev_entry.get('balance_eth', 0)
    prev_volume = prev_entry.get('total_volume_eth', 0)

    if prev_balance > 0:
        balance_change_pct = ((balance - prev_balance) / prev_balance) * 100
    else:
        balance_change_pct = 0

    if prev_volume > 0:
        volume_change_pct = ((total_volume_eth - prev_volume) / prev_volume) * 100
    else:
        volume_change_pct = 0

    # === Regles d'alerte ===
    if abs(balance_change_pct) > alert_pct:
        alerts.append({
            'wallet': label,
            'address': address,
            'type': 'balance_change',
            'severity': 'high' if abs(balance_change_pct) > alert_pct * 2 else 'medium',
            'detail': f'Solde {balance:.2f} ETH (var {balance_change_pct:+.1f}%)',
            'timestamp': now_iso()
        })

    if total_volume_eth > min_eth:
        alerts.append({
            'wallet': label,
            'address': address,
            'type': 'volume_spike',
            'severity': 'high' if total_volume_eth > min_eth * 3 else 'medium',
            'detail': f'Volume 24h: {total_volume_eth:.2f} ETH (var {volume_change_pct:+.1f}%)',
            'timestamp': now_iso()
        })

    # Sauvegarder l'etat actuel
    prev_state[address] = {
        'label': label,
        'balance_eth': balance,
        'total_volume_eth': total_volume_eth,
        'tx_count': len(tx_list),
        'last_checked': now_iso()
    }
    save_json(WALLET_STATE, prev_state)

    return alerts

def track_all_wallets(settings=None):
    """Point d'entree principal: analyse tous les wallets configures."""
    if settings is None:
        settings = load_settings()
    
    api_key = get_etherscan_api_key()
    if not api_key or api_key == 'YOUR_KEY_HERE':
        logger.warning('ETHERSCAN_API_KEY non configuree — wallet tracking desactive')
        return []

    wallets = settings.get('wallet_tracking', {}).get('ethereum_wallets', [])
    min_eth = settings.get('wallet_tracking', {}).get('min_transfer_eth', 5.0)
    alert_pct = settings.get('wallet_tracking', {}).get('alert_move_pct', 5.0)

    all_alerts = []
    for wallet in wallets:
        if wallet['address'].startswith('0x0000000000000000000000'):
            logger.info(f'Wallet example {wallet["label"]} — skip')
            continue
        try:
            alerts = analyze_wallet_activity(wallet, api_key, min_eth, alert_pct)
            all_alerts.extend(alerts)
            logger.info(f'Wallet {wallet["label"]}: {len(alerts)} alertes')
        except Exception as e:
            logger.error(f'Erreur wallet {wallet["label"]}: {e}')

    logger.info(f'TOTAL: {len(all_alerts)} alertes wallet')
    return all_alerts

if __name__ == '__main__':
    alerts = track_all_wallets()
    if not alerts:
        print('Aucune alerte wallet (API key manquante ou wallets example uniquement)')
    else:
        for a in alerts:
            print(f"  [{a['severity'].upper()}] {a['wallet']}: {a['detail']}")

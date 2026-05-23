# price_tracker.py - Suivi de prix crypto via CoinGecko API (gratuit, pas de cle)
# Auteur: FORGE | Projet: Trading Agent Phase 2.1

import json, urllib.request, sys, os
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils import setup_logging, load_settings

logger = setup_logging('price_tracker')
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) TradingAgent/1.0'

# Top coins a tracker (configurable)
DEFAULT_COINS = ['bitcoin', 'ethereum', 'solana', 'near', 'polymath', 'chainlink']

def get_prices(coin_ids=None):
    """Recupere les prix depuis CoinGecko API v3 (gratuit)."""
    if coin_ids is None:
        settings = load_settings()
        coin_ids = settings.get('price_tracking', {}).get('coins', DEFAULT_COINS)

    ids_str = ','.join(coin_ids)
    url = f'https://api.coingecko.com/api/v3/simple/price?ids={ids_str}&vs_currencies=usd&include_24hr_change=true&include_24hr_vol=true'

    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data
    except Exception as e:
        logger.error(f'CoinGecko API error: {e}')
        return {}

def get_trending():
    """Recupere les tendances CoinGecko (top 5 trending)."""
    url = 'https://api.coingecko.com/api/v3/search/trending'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            coins = data.get('coins', [])[:5]
            return [{
                'name': c['item']['name'],
                'symbol': c['item']['symbol'].upper(),
                'market_cap_rank': c['item'].get('market_cap_rank', '?'),
                'score': c['item'].get('score', 0)
            } for c in coins]
    except Exception as e:
        logger.warning(f'Trending error: {e}')
        return []

def analyze_price_moves(prices, thresholds=None):
    """Analyse les mouvements de prix et genere des alertes."""
    if thresholds is None:
        thresholds = {'surge': 5.0, 'drop': -5.0, 'extreme_surge': 10.0, 'extreme_drop': -10.0}

    alerts = []
    for coin_id, data in prices.items():
        change = data.get('usd_24h_change', 0) or 0
        price = data.get('usd', 0)
        vol = data.get('usd_24h_vol', 0)

        severity = 'low'
        if change > thresholds.get('extreme_surge', 10):
            severity = 'high'
        elif change > thresholds.get('surge', 5):
            severity = 'medium'
        elif change < thresholds.get('extreme_drop', -10):
            severity = 'high'
        elif change < thresholds.get('drop', -5):
            severity = 'medium'

        direction = 'UP' if change >= 0 else 'DOWN'

        alerts.append({
            'coin': coin_id.capitalize(),
            'price': price,
            'change_24h': change,
            'volume_24h': vol,
            'direction': direction,
            'severity': severity
        })

    # Sort by absolute change
    alerts.sort(key=lambda x: abs(x['change_24h']), reverse=True)
    return alerts

def get_price_data(settings=None):
    """Point d'entree principal."""
    if settings is None:
        settings = load_settings()

    coin_ids = settings.get('price_tracking', {}).get('coins', DEFAULT_COINS)
    prices = get_prices(coin_ids)
    trending = get_trending()
    alerts = analyze_price_moves(prices)

    logger.info(f'Prices: {len(prices)} coins, {len(alerts)} alerts, {len(trending)} trending')
    return {'prices': prices, 'trending': trending, 'alerts': alerts}

if __name__ == '__main__':
    data = get_price_data()
    print(f"\n=== Prix ({len(data['prices'])} coins) ===")
    for a in data['alerts'][:6]:
        emoji = 'UP' if a['change_24h'] >= 0 else 'DOWN'
        print(f"  {a['coin']:15s}   {a['change_24h']:+.2f}%  [{a['severity'].upper()}]")
    if data['trending']:
        print(f"\n=== Trending ===")
        for t in data['trending']:
            print(f"  {t['symbol']:8s} {t['name']} (rank #{t['market_cap_rank']})")

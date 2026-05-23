# alpaca_tracker.py - Suivi de portefeuille Alpaca Markets
# Auteur: FORGE | Projet: Trading Agent Phase 1
# Utilise alpaca-py SDK pour account, positions, market status

import os, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils import setup_logging, load_settings

logger = setup_logging('alpaca_tracker')

def get_alpaca_client(settings=None):
    if settings is None:
        settings = load_settings()
    ac = settings.get('api_keys', {}).get('alpaca', {})
    api_key = os.environ.get('ALPACA_API_KEY', ac.get('api_key', ''))
    secret_key = os.environ.get('ALPACA_SECRET_KEY', ac.get('secret_key', ''))
    paper = ac.get('paper', True)
    if not api_key or not secret_key or '****' in api_key:
        logger.warning('Alpaca credentials not configured')
        return None
    try:
        from alpaca.trading.client import TradingClient
        return TradingClient(api_key=api_key, secret_key=secret_key, paper=paper)
    except ImportError:
        logger.error('alpaca-py not installed. Run: pip install alpaca-py')
        return None

def get_account_summary(client):
    try:
        a = client.get_account()
        return {
            'cash': float(a.cash),
            'buying_power': float(a.buying_power),
            'portfolio_value': float(a.portfolio_value),
            'equity': float(a.equity),
            'long_market_value': float(a.long_market_value),
            'daytrade_count': int(a.daytrade_count),
            'pattern_day_trader': bool(a.pattern_day_trader),
            'account_blocked': bool(a.account_blocked),
            'trading_blocked': bool(a.trading_blocked),
            'status': str(a.status)
        }
    except Exception as e:
        logger.error(f'Account error: {e}')
        return None

def get_positions(client):
    try:
        positions = client.get_all_positions()
        return [{
            'symbol': p.symbol,
            'qty': float(p.qty),
            'avg_entry_price': float(p.avg_entry_price),
            'current_price': float(p.current_price),
            'market_value': float(p.market_value),
            'unrealized_pl': float(p.unrealized_pl),
            'unrealized_plpc': float(p.unrealized_plpc),
            'change_today': float(p.change_today)
        } for p in positions]
    except Exception as e:
        logger.error(f'Positions error: {e}')
        return []

def get_market_status(client):
    try:
        clock = client.get_clock()
        return {
            'is_open': clock.is_open,
            'next_open': str(clock.next_open),
            'next_close': str(clock.next_close)
        }
    except Exception as e:
        logger.error(f'Clock error: {e}')
        return None

def get_alpaca_data(settings=None):
    client = get_alpaca_client(settings)
    if not client:
        return None
    account = get_account_summary(client)
    positions = get_positions(client)
    market = get_market_status(client)
    logger.info(f'Alpaca: {account["portfolio_value"]} portfolio, {len(positions)} positions, market open={market["is_open"]}')
    return {
        'account': account,
        'positions': positions,
        'market': market
    }

if __name__ == '__main__':
    data = get_alpaca_data()
    if data:
        a = data['account']
        print(f'Portfolio: {a["portfolio_value"]} | Cash: {a["cash"]} | BP: {a["buying_power"]}')
        print(f'Positions: {len(data["positions"])}')
        print(f'Market open: {data["market"]["is_open"]}')
    else:
        print('Alpaca not configured')
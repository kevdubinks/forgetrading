DOL = chr(36)
# report_generator.py v2.1 - Synthese quotidienne
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from utils import REPORTS_DIR, setup_logging, load_settings
from news_collector import collect_all_news
from wallet_tracker import track_all_wallets
from alpaca_tracker import get_alpaca_data
from decision_engine_v2 import get_decision_v2 as get_decision_report
from price_tracker import get_price_data
from auto_trader import auto_trade_from_conviction, generate_daily_dryrun_block
from binance_provider import get_enhanced_signals_binance

DOL = chr(36)
logger = setup_logging('report_generator')

def classify_impact(article):
    t = article['title'].lower()
    hk = ['hack','exploit','ban','sec','regulation','crash','delist','emergency','vulnerability','rug','scam']
    mk = ['partnership','launch','mainnet','listing','acquisition','funding','raise','million','billion','upgrade','surge','rally','pump','jump']
    for kw in hk:
        if kw in t: return 'HIGH'
    for kw in mk:
        if kw in t: return 'MEDIUM'
    return 'LOW'

def generate_daily_report(settings=None):
    if settings is None:
        settings = load_settings()
    today = datetime.now().strftime('%Y-%m-%d')
    now = datetime.now().strftime('%H:%M')
    rp = REPORTS_DIR / f'{today}.md'

    logger.info('=== DEBUT RAPPORT ===')
    logger.info('Collecte news...')
    articles = collect_all_news(settings)
    logger.info('Analyse wallets...')
    wallet_alerts = track_all_wallets(settings)
    logger.info('Prix crypto...')
    price_data = get_price_data(settings)
    logger.info('Portfolio Alpaca...')
    alpaca = get_alpaca_data(settings)

    logger.info('Signaux avances...')
    enhanced = get_enhanced_signals_binance(settings)

    lines = []
    lines.append(f'# Rapport Trading - {today}')
    lines.append(f'> Genere le {today} a {now} par FORGE Trading Agent')
    lines.append('')
    lines.append('---')
    lines.append('')

    # Resume
    hi_a = [x for x in wallet_alerts if x['severity'] == 'high']
    hi_n = [x for x in articles if classify_impact(x) == 'HIGH']
    md_n = [x for x in articles if classify_impact(x) == 'MEDIUM']
    price_a = [x for x in price_data.get('alerts', []) if x['severity'] in ('high', 'medium')]
    lines.append('## Resume')
    lines.append(f'- **News**: {len(articles)} ({len(hi_n)} HIGH)')
    lines.append(f'- **Wallet alerts**: {len(wallet_alerts)} ({len(hi_a)} HIGH)')
    lines.append(f'- **Price moves**: {len(price_a)} significatifs')
    lines.append('')

    # Price Alerts
    if price_data.get('alerts'):
        lines.append('## Crypto Prices (24h)')
        lines.append('')
        for a in price_data['alerts'][:10]:
            emoji = '+' if a['change_24h'] >= 0 else ''
            sev = f" [{a['severity'].upper()}]" if a['severity'] != 'low' else ''
            p = a['price']
            c = a['change_24h']
            n = a['coin']
            lines.append(f"- **{n}**: {DOL}{p:,.2f} ({emoji}{c:+.2f}%){sev}")
        lines.append('')
    if price_data.get('trending'):
        lines.append('### Trending CoinGecko')
        lines.append('')
        for t in price_data['trending'][:5]:
            lines.append(f"- **{t['symbol']}** ({t['name']}) - rank #{t['market_cap_rank']}")
        lines.append('')

    # Wallet Alerts
    if hi_a:
        lines.append('## ALERTES Wallet - HAUTE PRIORITE')
        lines.append('')
        for a in hi_a:
            lines.append(f"- **{a['wallet']}** - {a['detail']} ({a['type']})")
        lines.append('')

    # News
    if hi_n:
        lines.append('## News Impact ELEVE')
        lines.append('')
        for a in hi_n:
            lines.append(f"### [{a['source']}] {a['title']}")
            lines.append(f"- **Lien**: {a['url']}")
            if a.get('summary'):
                lines.append(f"- **Resume**: {a['summary'][:200]}")
            lines.append('')
    if md_n:
        lines.append('## News Impact MOYEN')
        lines.append('')
        for a in md_n[:10]:
            lines.append(f"- [{a['source']}] **{a['title']}** - [lien]({a['url']})")
        lines.append('')
    lo_n = [x for x in articles if classify_impact(x) == 'LOW'][:10]
    if lo_n:
        lines.append('## Autres News')
        lines.append('')
        for a in lo_n:
            lines.append(f"- [{a['source']}] {a['title']} - [lien]({a['url']})")
        lines.append('')

    # Alpaca
    if alpaca:
        ac = alpaca['account']
        mk = alpaca['market']
        lines.append('---')
        lines.append('## Alpaca Portfolio (Paper Trading)')
        lines.append('')
        lines.append(f"- **Portfolio**: {DOL}{ac['portfolio_value']:,.2f}")
        lines.append(f"- **Cash**: {DOL}{ac['cash']:,.2f}")
        lines.append(f"- **BP**: {DOL}{ac['buying_power']:,.2f}")
        lines.append(f"- **Market**: {'OPEN' if mk['is_open'] else 'CLOSED'}")
        lines.append('')
        for p in alpaca.get('positions', []):
            ps = '+' if p['unrealized_pl'] >= 0 else ''
            lines.append(f"- **{p['symbol']}**: {p['qty']} @ {DOL}{p['avg_entry_price']} | P/L: {ps}{DOL}{p['unrealized_pl']:,.2f} ({p['unrealized_plpc']:+.2f}%)")
        if not alpaca.get('positions'):
            lines.append('*Aucune position*')
        lines.append('')

    # === Decision Engine V2 ===
    cv = get_decision_report(articles, price_data, wallet_alerts, enhanced, settings)
    rc = None  # V2 pas de reco paper trade separee (gere par auto-trader)
    if cv:
        lines.append("---")
        lines.append("## Decision Engine")
        lines.append("")
        lines.append(f"- **Conviction**: {cv.get("level","?")} ({cv.get("score",0)}/100)")
        lines.append(f"- **Action**: {cv.get("action","?")}")
        lines.append("")
        for r in cv.get("reasons", [])[:5]:
            lines.append(f"- {r}")
        lines.append("")
    # === Auto-Trader (dry-run) ===
    logger.info('Auto-trader dry-run...')
    trade = auto_trade_from_conviction(cv, price_data, enhanced, alpaca, settings)

    # Dry-run summary block
    dry_block = generate_daily_dryrun_block()
    lines.append(dry_block)

    # Risk
    lines.append('---')
    lines.append('## Regles de Risk Management')
    rk = settings.get('risk_rules', {})
    lines.append(f"- Position max: **{rk.get('max_position_pct', 5)}%**")
    lines.append(f"- Portfolio risk max: **{rk.get('max_portfolio_risk_pct', 20)}%**")
    lines.append(f"- Stop-loss: **-{rk.get('stop_loss_pct', 10)}%**")
    lines.append('')
    lines.append('> AUCUNE action automatique. Confirmation humaine obligatoire.')
    lines.append('')
    lines.append('*FORGE Trading Agent v2.1*')

    report_text = chr(10).join(lines)
    with open(rp, 'w', encoding='utf-8') as f:
        f.write(report_text)
    logger.info(f'Rapport ecrit: {rp}')
    return rp, len(articles), len(wallet_alerts)

if __name__ == '__main__':
    p, n, a = generate_daily_report()
    print(f'Rapport: {p}')
    print(f'News: {n} | Alertes: {a}')
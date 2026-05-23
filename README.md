# FORGE Trading Agent v2.1

Agent de trading crypto paper — Mode B full auto (Alpaca Paper).
Pipeline quotidien + dashboard live + stockage Supabase.

## Stack

```
trading/
├── api/
│   └── server.py              # Flask API (7 endpoints)
├── scripts/
│   ├── run_daily.py            # Pipeline quotidien (cron)
│   ├── trade_executor.py       # Execution paper (Alpaca)
│   ├── decision_engine_v2.py   # Score conviction 4 criteres
│   ├── binance_provider.py     # Prix + RSI (Binance)
│   ├── signals_enhanced.py     # Fear/Greed + BTC.D + Volume
│   ├── alpaca_tracker.py       # Compte + positions Alpaca
│   ├── supabase_client.py      # DB Supabase (auto-fallback JSON)
│   ├── wallet_tracker.py       # Surveillance whales (Etherscan)
│   ├── report_generator.py     # Rapport Markdown quotidien
│   ├── backtest_engine.py      # Backtest 90j OHLCV + R:R
│   ├── dashboard.py            # Generateur dashboard HTML
│   ├── news_collector.py       # RSS + Reddit news
│   └── utils.py                # Helpers
├── config/
│   └── settings.example.json   # Template config
├── dashboard.html              # Dashboard live (auto-refresh)
├── render.yaml                 # Deploiement Render (web + cron)
├── requirements.txt            # Dependances Python
├── .env.example                # Template variables env
└── .gitignore
```

## Deploiement Render

1. Push sur GitHub
2. Render > New Blueprint > selectionner le repo
3. Remplir les 6 variables d'env dans le dashboard Render
4. Le web service et le cron job se deploient automatiquement

## Endpoints API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard HTML |
| `GET /api/health` | Health check |
| `GET /api/dry-run` | Performance (PnL, WR, R:R, EV) |
| `GET /api/prices` | Prix Binance + RSI live |
| `GET /api/decision` | Score conviction (4 criteres) |
| `GET /api/portfolio` | Compte Alpaca + positions |
| `GET /api/trades` | Historique trades (Supabase) |

## Pipeline quotidien (14h30 Paris)

```
Decision Engine V2 → Trade Executor → Report Generator → Dashboard → Discord Embed
```

Seuils : >= 50 MODERATE (3% portfolio), >= 75 STRONG (5% portfolio).
Stop-loss -10%, Take-profit +20%. Max 3 positions, max 20% risque.

## Regles
- Paper trading uniquement (Alpaca Paper)
- Aucun trade reel sans confirmation humaine explicite
- Les credentials sont dans les variables d'environnement, jamais dans le code

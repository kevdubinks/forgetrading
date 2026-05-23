-- Supabase migration: FORGE Trading Agent tables
-- Executer dans le SQL Editor Supabase (une seule fois)

-- 1. TRADES — journal de tous les trades
CREATE TABLE IF NOT EXISTS trades (
    id          TEXT PRIMARY KEY,
    coin        TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    direction   TEXT NOT NULL DEFAULT 'LONG',
    source      TEXT DEFAULT 'momentum',
    entry_price NUMERIC NOT NULL,
    entry_time  TIMESTAMPTZ NOT NULL,
    quantity    NUMERIC NOT NULL,
    conviction_score  INTEGER,
    conviction_level  TEXT,
    position_size_pct NUMERIC,
    tp_price    NUMERIC,
    sl_price    NUMERIC,
    exit_price  NUMERIC,
    exit_time   TIMESTAMPTZ,
    pnl         NUMERIC,
    pnl_pct     NUMERIC,
    exit_reason TEXT,
    status      TEXT NOT NULL DEFAULT 'OPEN',
    outcome     TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(created_at DESC);

-- 2. REPORTS — rapports quotidiens
CREATE TABLE IF NOT EXISTS reports (
    id              SERIAL PRIMARY KEY,
    date            DATE NOT NULL,
    content         TEXT,
    conviction_score INTEGER,
    conviction_level TEXT,
    fear_greed      INTEGER,
    rsi_avg         NUMERIC,
    btc_dominance   NUMERIC,
    momentum        NUMERIC,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(date DESC);

-- 3. DRY_RUN_SUMMARY — resume de performance (1 seule ligne upsertée)
CREATE TABLE IF NOT EXISTS dry_run_summary (
    id              INTEGER PRIMARY KEY DEFAULT 1,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    total_trades    INTEGER DEFAULT 0,
    closed_trades   INTEGER DEFAULT 0,
    cumulative_pnl  NUMERIC DEFAULT 0,
    win_rate        NUMERIC DEFAULT 0,
    r_r_ratio       NUMERIC DEFAULT 0,
    expected_value  NUMERIC DEFAULT 0,
    best_trade      JSONB,
    worst_trade     JSONB
);

-- Row Level Security (optionnel — permet l'acces anonymous si active)
-- ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "Allow all" ON trades FOR ALL USING (true);
-- ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "Allow all" ON reports FOR ALL USING (true);
-- ALTER TABLE dry_run_summary ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "Allow all" ON dry_run_summary FOR ALL USING (true);

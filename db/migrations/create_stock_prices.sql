CREATE TABLE IF NOT EXISTS stock_prices (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    close_price NUMERIC(18, 4),
    price_date DATE NOT NULL,
    shares_outstanding BIGINT,
    market_cap NUMERIC(24, 2),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (ticker, price_date)
);

CREATE INDEX IF NOT EXISTS idx_stock_prices_ticker
    ON stock_prices (ticker);

CREATE INDEX IF NOT EXISTS idx_stock_prices_date
    ON stock_prices (price_date);

CREATE INDEX IF NOT EXISTS idx_stock_prices_ticker_date
    ON stock_prices (ticker, price_date DESC);

CREATE TABLE IF NOT EXISTS sec_shares (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    cik VARCHAR(20),
    company_name VARCHAR(255),
    shares_outstanding BIGINT,
    shares_date DATE,
    fetched_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sec_shares_ticker
    ON sec_shares (ticker);

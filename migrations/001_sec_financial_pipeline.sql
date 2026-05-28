-- SEC-backed financial pipeline schema

CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(16) NOT NULL UNIQUE,
    cik VARCHAR(10) NOT NULL UNIQUE,
    company_name VARCHAR(255) NOT NULL,
    exchange VARCHAR(64),
    sector VARCHAR(128),
    industry VARCHAR(128),
    website VARCHAR(255),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_companies_ticker ON companies (ticker);
CREATE INDEX IF NOT EXISTS ix_companies_cik ON companies (cik);

CREATE TABLE IF NOT EXISTS filings (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    accession_number VARCHAR(32) NOT NULL,
    filing_type VARCHAR(16) NOT NULL,
    filing_date DATE NOT NULL,
    fiscal_year INTEGER,
    fiscal_period VARCHAR(8),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_filings_company_accession UNIQUE (company_id, accession_number)
);

CREATE INDEX IF NOT EXISTS ix_filings_company_id ON filings (company_id);
CREATE INDEX IF NOT EXISTS ix_filings_company_type_date ON filings (company_id, filing_type, filing_date);

CREATE TABLE IF NOT EXISTS raw_financial_facts (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    filing_id INTEGER NOT NULL REFERENCES filings(id),
    taxonomy VARCHAR(32) NOT NULL,
    tag VARCHAR(128) NOT NULL,
    unit VARCHAR(32) NOT NULL,
    value NUMERIC(24, 6) NOT NULL,
    period_start DATE,
    period_end DATE,
    filed_date DATE,
    frame VARCHAR(64),
    raw_json JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_raw_financial_facts_company_filing ON raw_financial_facts (company_id, filing_id);
CREATE INDEX IF NOT EXISTS ix_raw_financial_facts_tag ON raw_financial_facts (tag);

CREATE TABLE IF NOT EXISTS normalized_financials (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    filing_id INTEGER NOT NULL REFERENCES filings(id),
    total_revenue NUMERIC(24, 6),
    interest_income NUMERIC(24, 6),
    total_debt NUMERIC(24, 6),
    cash_and_equivalents NUMERIC(24, 6),
    total_assets NUMERIC(24, 6),
    market_cap NUMERIC(24, 6),
    operating_income NUMERIC(24, 6),
    net_income NUMERIC(24, 6),
    shares_outstanding NUMERIC(24, 6),
    source_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_normalized_company_filing UNIQUE (company_id, filing_id)
);

CREATE INDEX IF NOT EXISTS ix_normalized_company ON normalized_financials (company_id);

CREATE TABLE IF NOT EXISTS halal_screen_results (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    filing_id INTEGER NOT NULL REFERENCES filings(id),
    debt_ratio NUMERIC(12, 8),
    interest_income_ratio NUMERIC(12, 8),
    cash_ratio NUMERIC(12, 8),
    halal_status VARCHAR(64) NOT NULL,
    data_source VARCHAR(32) NOT NULL DEFAULT 'sec_xbrl',
    source_filing_date DATE,
    mapped_tags_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    reasoning_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_halal_result_company_filing UNIQUE (company_id, filing_id)
);

CREATE INDEX IF NOT EXISTS ix_halal_screen_results_company ON halal_screen_results (company_id);

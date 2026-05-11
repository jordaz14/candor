-- Candor: company intelligence schema
-- Run automatically by docker-entrypoint-initdb.d on first container start.

CREATE EXTENSION IF NOT EXISTS vector;

-- Master company table
CREATE TABLE IF NOT EXISTS companies (
    id           SERIAL PRIMARY KEY,
    ticker       TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    cik          TEXT UNIQUE,
    sector       TEXT,
    industry     TEXT,
    last_ingested_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker);

-- Filing metadata
CREATE TABLE IF NOT EXISTS filings (
    id           SERIAL PRIMARY KEY,
    company_id   INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    filing_type  TEXT NOT NULL,            -- '10-K' | '10-Q'
    period_end   DATE,
    filed_date   DATE,
    accession_no TEXT UNIQUE,
    edgar_url    TEXT,
    UNIQUE (company_id, accession_no)
);

CREATE INDEX IF NOT EXISTS idx_filings_company ON filings(company_id);

-- Earnings call metadata
CREATE TABLE IF NOT EXISTS earnings_calls (
    id                SERIAL PRIMARY KEY,
    company_id        INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    quarter           SMALLINT NOT NULL,   -- 1..4
    year              SMALLINT NOT NULL,
    source            TEXT NOT NULL,        -- '8-K' | 'FMP'
    has_qa_transcript BOOLEAN NOT NULL DEFAULT FALSE,
    call_date         DATE,
    UNIQUE (company_id, year, quarter)
);

CREATE INDEX IF NOT EXISTS idx_earnings_calls_company ON earnings_calls(company_id);

-- Glassdoor structured snapshot (one row per company per scrape date)
CREATE TABLE IF NOT EXISTS glassdoor_reviews (
    id                 SERIAL PRIMARY KEY,
    company_id         INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    overall_rating     NUMERIC(3,2),
    culture            NUMERIC(3,2),
    work_life_balance  NUMERIC(3,2),
    compensation       NUMERIC(3,2),
    management         NUMERIC(3,2),
    career_growth      NUMERIC(3,2),
    ceo_approval       NUMERIC(4,3),        -- 0..1
    review_count       INT,
    last_scraped_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_glassdoor_company ON glassdoor_reviews(company_id);

-- yfinance market data snapshot
CREATE TABLE IF NOT EXISTS financial_metrics (
    id                 SERIAL PRIMARY KEY,
    company_id         INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    beta               NUMERIC(6,3),
    market_cap         BIGINT,
    shares_outstanding BIGINT,
    total_debt         BIGINT,
    cash               BIGINT,
    dividend_yield     NUMERIC(6,5),
    revenue_history    JSONB,                -- [{"year": 2024, "value": 130497}]
    fcf_history        JSONB,
    operating_income_history JSONB,
    fetched_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_financial_metrics_company ON financial_metrics(company_id);

-- Unified vector chunks table: filings + transcripts + glassdoor reviews
-- Dimension 1536 matches OpenAI text-embedding-3-small.
CREATE TABLE IF NOT EXISTS document_chunks (
    id           BIGSERIAL PRIMARY KEY,
    company_id   INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    source_type  TEXT NOT NULL,            -- 'filing' | 'transcript' | 'glassdoor'
    source_id    INT NOT NULL,             -- FK by convention into filings/earnings_calls/glassdoor_reviews
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
    text         TEXT NOT NULL,
    embedding    vector(1536) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_company_source
    ON document_chunks (company_id, source_type);

CREATE INDEX IF NOT EXISTS idx_chunks_metadata
    ON document_chunks USING gin (metadata jsonb_path_ops);

-- HNSW gives better recall and faster queries than IVFFlat at this scale.
-- Cosine distance matches OpenAI embedding normalization.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON document_chunks USING hnsw (embedding vector_cosine_ops);

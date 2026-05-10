# Candor — Company Intelligence MCP Server — Project Spec
_Decided: 2026-05-03 via /decision + /grill-me session_

## What It Is

An MCP server that conducts deep, multi-source analysis of S&P 500 publicly traded companies. Combines SEC filings, earnings call transcripts, Glassdoor employee sentiment, and market data into structured outputs via four synthesis skills. Core differentiator: cross-source tension analysis surfacing the gap between management narrative and employee reality.

---

## Tech Stack

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python | Financial data ecosystem lives here (pandas, yfinance, edgartools) |
| MCP library | fastmcp (mcp v1.0+ decorator API) | Reduces protocol boilerplate; focus on data + synthesis logic |
| Database | PostgreSQL + pgvector via Docker | Single DB for structured + semantic data; portable via docker-compose |
| Embeddings | OpenAI text-embedding-3-small | Best retrieval quality for financial jargon at negligible cost (~$2 for full S&P 500) |
| EDGAR ingestion | edgartools | Parses filing structure into sections; handles XBRL extraction |
| Market data | yfinance | Free, no API key, covers all WACC inputs |
| Earnings transcripts | EDGAR 8-K (default) + FMP API (optional upgrade) | Zero friction default; FMP adds full Q&A for users with a key |

---

## Data Sources

### SEC EDGAR (via edgartools)
- **10-K / 10-Q:** 5 years of filings per company
- **Earnings call prepared remarks:** 12 quarters via 8-K filings (Item 2.02)
- Free, public API, no scraping required

### FMP API (optional)
- Full earnings call transcripts including analyst Q&A
- Activated by setting `FMP_API_KEY` in `.env`
- Falls back to EDGAR 8-Ks silently if key absent

### Glassdoor (separate scraper repo)
- Reverse-engineered internal API (Julian's domain expertise)
- Lives in a separate repo; writes to the shared Postgres DB
- **Fields extracted:**
  - Overall rating (1–5)
  - Sub-ratings: culture, work-life balance, compensation, management, career growth
  - CEO approval rating + trend
  - Review text (pros and cons) — goes into vector DB
- Excluded: interview experience ratings, "recommend to a friend" %, salary data

### yfinance (market data)
- Refreshed on every `get_company_data` call (no cache needed)
- **Fields:**
  - Beta (5-year monthly)
  - Shares outstanding
  - Total debt
  - Cash and equivalents
  - Market cap
  - Historical revenue, operating income, FCF (sanity check vs. EDGAR)
  - Dividend yield (terminal growth rate governor for DCF)

---

## Database Design

### Setup
- PostgreSQL 16 + pgvector extension
- Local Docker via `docker-compose.yml` — one command, fully portable
- `pgvector/pgvector:pg16` image

### Tables

**`companies`**
Master company table: ticker, name, CIK, sector, industry.

**`document_chunks`** (unified vector table)
All document text across sources. One vector index covers everything.
```
id | company_id | source_type | source_id | metadata jsonb | text | embedding vector
```
- `source_type`: `'filing'` | `'transcript'` | `'glassdoor'`
- `metadata jsonb` carries chunk-level context:
  - Filings: `{"section": "Risk Factors", "chunk_index": 3, "filing_type": "10-K"}`
  - Transcripts: `{"speaker": "Jensen Huang", "speaker_role": "CEO", "quarter": "Q3", "year": 2024}`
  - Glassdoor: `{"type": "pro", "overall_rating": 4, "year": 2023}`

**`filings`**
EDGAR filing metadata: company_id, filing_type, period_end, filed_date, edgar_url.

**`earnings_calls`**
Call metadata: company_id, quarter, year, source (8-K or FMP), has_qa_transcript.

**`glassdoor_reviews`**
Structured Glassdoor data: all sub-ratings, CEO approval, review count, last scraped date.

**`financial_metrics`**
yfinance structured data: beta, market cap, shares outstanding, total debt, cash, FCF history, dividend yield.

### Chunking Strategy
- **Document-structure-aware** — parse section headers first, chunk within sections
- Filings: chunk by named section (Business Overview, Risk Factors, MD&A, Financial Statements)
- Transcripts: chunk by speaker turn + paragraph; tag with speaker role
- Glassdoor: chunk by individual review pro/con

---

## Ingestion Pipeline

### Architecture
Standalone `ingest.py` script — **not** an MCP tool. The MCP server is a pure read layer.

### Commands
```bash
python ingest.py NVDA                # single company
python ingest.py NVDA AAPL MSFT     # batch
python ingest.py --sp500            # full index
python ingest.py --update NVDA      # refresh stale data (re-fetch if >90 days old)
```

### Pipeline per company
1. Fetch 5yr 10-K/10-Q via edgartools → parse sections → chunk → embed → store
2. Fetch 12 quarters earnings call 8-Ks (or FMP if key present) → chunk by speaker turn → embed → store
3. Check Glassdoor table for existing data (populated by separate scraper repo)
4. Fetch yfinance market data → store in financial_metrics
5. Upsert company record with ingestion timestamp

### Quarterly refresh
Run `ingest.py --update` on a cron schedule. Re-fetches any company whose most recent filing is older than 90 days.

---

## MCP Tool Surface

All tools are pure read operations. No LLM calls inside the server.

| Tool | Signature | Purpose |
|------|-----------|---------|
| `list_companies` | `()` | Returns ingested tickers + last updated date |
| `get_company_data` | `(ticker: str)` | Structured snapshot — see return shape below |
| `get_company_reviews` | `(ticker: str)` | Structured Glassdoor data: ratings, CEO approval, review count |
| `search_filings` | `(query, ticker, filing_type=None, section=None)` | Semantic search over 10-K/10-Q chunks |
| `search_transcripts` | `(query, ticker, speaker_role=None, quarter=None, year=None)` | Semantic search over earnings call chunks |
| `search_company_reviews` | `(query, ticker)` | Semantic search over Glassdoor review text |

### `get_company_data` return shape
```json
{
  "company": {"name": "NVIDIA", "ticker": "NVDA", "sector": "Technology", "industry": "Semiconductors", "cik": "..."},
  "data_availability": {
    "filings": true,
    "transcripts": "12 of 12 quarters",
    "glassdoor": true,
    "yfinance": true
  },
  "financial_metrics": {
    "beta": 1.68,
    "market_cap": 2800000000000,
    "shares_outstanding": 24500000000,
    "total_debt": 8460000000,
    "cash": 7281000000,
    "dividend_yield": 0.0003
  },
  "historical_financials": {
    "revenue": [26974, 44870, 60922, 79775, 130497],
    "fcf": [3808, 3808, 11638, 27021, 60452],
    "operating_income": [4224, 4408, 10041, 32972, 81453],
    "years": [2020, 2021, 2022, 2023, 2024]
  },
  "glassdoor_summary": {
    "overall_rating": 4.2,
    "culture": 4.1,
    "work_life_balance": 3.8,
    "compensation": 4.5,
    "management": 3.9,
    "career_growth": 4.0,
    "ceo_approval": 0.91,
    "review_count": 4823
  }
}
```

---

## Skills Surface

Skills are instructional resources loaded via fastmcp's Skills Provider (`skill://` URI scheme). Synthesis happens in the host agent's context — the MCP server makes no LLM calls for synthesis.

```
skills/
  bmc-synthesis/
    SKILL.md              ← Business Model Canvas instructions
  dcf-model/
    SKILL.md              ← DCF orchestration instructions
    dcf_calculator.py     ← Deterministic WACC + DCF computation
  tension-analysis/
    SKILL.md              ← Cross-source tension instructions
    tension_scorer.py     ← Rating delta scoring (optional)
  compare-companies/
    SKILL.md              ← Multi-ticker orchestration instructions
```

### Skill purposes

**`bmc-synthesis`**
Populates a Business Model Canvas from retrieved context: customer segments, value propositions, channels, revenue streams, cost structure, key resources, key activities, key partnerships. Purely qualitative synthesis.

**`dcf-model`**
SKILL.md: instructs agent which tools to call, how to extract growth rate assumptions from transcript chunks, how to use dividend yield as a terminal growth rate governor.
`dcf_calculator.py`: deterministic computation — WACC, FCF projection, terminal value, enterprise value → equity value → intrinsic value per share bridge.

**`tension-analysis`**
Calls `search_transcripts` and `search_company_reviews` across five themes: culture, compensation, work-life balance, leadership trust, career growth. Surfaces management claim vs. employee reality per theme with explicit high/medium/low tension signal.

**`compare-companies`**
Orchestration skill — calls `get_company_data` for each ticker, synthesizes cross-company comparison. Not a tool because it's a multi-step reasoning workflow, not a data fetch.

---

## Error Handling

Graceful degradation with explicit gap flagging. Tools always return whatever data exists; gaps are surfaced in `data_availability`. Skills adapt output based on what's available.

- No Glassdoor data → tension-analysis returns "insufficient review data"
- Missing transcript quarters → noted in data_availability; DCF proceeds with available quarters
- Incomplete filing history (recent IPO) → DCF notes shortened history window
- yfinance gap → flagged; WACC calculation deferred

---

## Configuration

`.env` + `python-dotenv`. `.env.example` committed to repo.

```bash
# .env.example
OPENAI_API_KEY=your_key_here
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/company_intel
FMP_API_KEY=optional_for_full_transcripts_with_qa
```

---

## Repo Structure

```
company-intel-mcp/
  mcp/                    ← MCP server + tool definitions
    server.py
    tools/
      company.py          ← get_company_data, list_companies
      reviews.py          ← get_company_reviews
      search.py           ← search_filings, search_transcripts, search_company_reviews
  pipeline/               ← Ingestion script + source fetchers
    ingest.py
    sources/
      edgar.py
      transcripts.py
      yfinance_fetch.py
  skills/                 ← Skill directories
    bmc-synthesis/
    dcf-model/
    tension-analysis/
    compare-companies/
  db/                     ← Schema + migrations
    schema.sql
  docker-compose.yml
  .env.example
  README.md
```

---

## Demo Plan

- **Primary:** YouTube unlisted video (~3 min) — live Claude session using the MCP server
- **Secondary:** README with sample outputs (BMC, DCF, tension analysis) for a well-known company
- **Pre-ingested for demo:** NVDA, AAPL, + one high-tension company (notable Glassdoor divergence from management narrative)
- Demo arc: `list_companies` → `get_company_data` → DCF skill → tension-analysis → compare two companies

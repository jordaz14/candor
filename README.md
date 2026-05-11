# Candor

MCP server for deep, multi-source analysis of S&P 500 companies.
Combines SEC filings, earnings transcripts, Glassdoor sentiment, and market data —
surfaces the tension between management narrative and employee reality.

See [`docs/candor-mcp-project-spec.md`](docs/candor-mcp-project-spec.md) for the full spec.

## Quickstart

```bash
# 1. Start Postgres + pgvector
docker compose up -d

# 2. Install deps
uv pip install -e .         # or: pip install -e .

# 3. Configure
cp .env.example .env        # then fill in OPENAI_API_KEY, SEC_USER_AGENT

# 4. Ingest a company
python -m pipeline.ingest NVDA

# 5. Run the MCP server
python -m mcp.server
```

## Repo layout

```
mcp/        MCP server + read-only tools
pipeline/   Standalone ingestion script + source fetchers
skills/     Instructional resources surfaced via skill:// URIs
db/         Postgres schema
docs/       Spec + design docs
```

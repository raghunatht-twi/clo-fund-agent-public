# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Brand Guidelines

All output documentation must conform to these brand guidelines:
- **Fonts**: Inter for all text except document titles, which use Bitter
- **Colors** (use only these): `#FFFFFF`, `#EDF1F3`, `#000000`, `#003D4F`, `#F2617A`, `#CC850A`, `#689E78`, `#47A1AD`, `#634F7D`

---

## Development Setup

```bash
uv sync                        # install main + dev dependencies (includes ruff)
git config core.hooksPath .githooks   # activate pre-commit ruff hook (once per clone)
```

### Linting

```bash
uv run ruff check .            # check
uv run ruff check . --fix      # auto-fix safe issues
```

Rules: `E`, `F`, `W`. Line length: 100. `E501` is suppressed in `db/` and `generate_data.py` — their compact table format is intentional. Commits are blocked if ruff errors are present.

---

## Running the Project

**Prerequisites**: Python 3.12+, `uv`, `ANTHROPIC_API_KEY`, PostgreSQL (DB agent and API only).

### Excel Agent (no database required)
```bash
uv run python -m clo_agent 'What is the net IRR for DKIG-2024-VII?'   # one-shot
uv run python -m clo_agent                                              # REPL
```

### PostgreSQL Agent
```bash
# One-time database setup
psql -h /tmp -d postgres -f db/schema.sql
uv run python db/load_data.py          # DKIG-2024-VII and DKIG-2016-I
uv run python db/load_ce_fund.py       # DKIG-2018-CE (Clean Energy)
uv run python db/load_tech_fund.py     # DKIG-2019-TECH (Technology sector)

uv run python -m clo_db_agent 'What is the net IRR for DKIG-2024-VII?'   # one-shot
uv run python -m clo_db_agent                                              # REPL
```

**REPL vs one-shot**: The REPL is significantly faster for interactive use — the Anthropic prompt cache warms after the first question, the DB connection pool stays open, and the 5-minute in-memory data cache avoids repeated PostgreSQL queries. One-shot mode starts fresh each time and is best for scripting.

### REST API
```bash
# Development
uv run uvicorn clo_api.main:app --host 127.0.0.1 --port 8000
# Production (behind TLS-terminating reverse proxy)
uv run gunicorn clo_api.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000
```
Swagger UI at `http://127.0.0.1:8000/docs` (disabled when `ENVIRONMENT=production`).

### Browser Chat UI
```bash
uv run python clo_chat_server.py       # serves at http://localhost:7860
PORT=8080 uv run python clo_chat_server.py   # custom port
```
Wraps `clo_db_agent` with a FastAPI server that streams responses via Server-Sent Events. The HTML interface is served at `/`; agent queries are posted to `/ask`.

---

## Architecture

### Packages

| Package | Backend | Entry Point |
|---|---|---|
| `clo_agent/` | Excel (`CLO_Fund_Domain_Data.xlsx`) | `python -m clo_agent` |
| `clo_db_agent/` | PostgreSQL | `python -m clo_db_agent` |
| `clo_api/` | PostgreSQL (via `clo_db_agent.data_access`) | `uvicorn clo_api.main:app` |
| `clo_chat_server.py` | PostgreSQL (via `clo_db_agent`) | `python clo_chat_server.py` |
| `portfolio_optimizer/` | PostgreSQL (via `clo_db_agent.data_access`) | imported by `clo_db_agent/tools.py` |

Both agents expose the same tool interface (`clo_agent/tools.py`, `clo_db_agent/tools.py`). The only difference is the data access layer. `clo_analytics.py` is a shared module for loan-level computations (WARF, WAS, WAL, loan replacement simulation, return attribution) used by both agents' tool layers.

### Portfolio Optimizer

`portfolio_optimizer/` is a greedy hill-climbing optimizer that maximises equity yield subject to compliance constraints, exposed as the `optimize_portfolio_returns` tool in the DB agent:

- `analytics.py` — pure stateless computation: `evaluate_trade`, `apply_trade`, `compute_equity_yield`. No I/O or LLM calls; fully unit-testable.
- `optimizer.py` — drives the loop (up to 150 iterations), persists the most recent `OptimizationResult` per fund in `_SESSION` (in-process dict) so follow-up questions don't re-run the optimizer.

Pre-filter: only trades that sell a lower-spread position into a higher-spread one are evaluated. Sell fractions: 0.25, 0.50, or 1.00. A candidate is accepted only if it improves equity yield AND all compliance tests still pass.

### Data Products

Eight data products map to Excel sheets and PostgreSQL tables (`dp01_*` … `dp08_*`):

| ID | Data Product | Table / Sheet |
|---|---|---|
| DP-01 | Fund Static Profile | Attribute/Value pairs; flattened to a single dict |
| DP-02 | Portfolio Snapshot | One row per loan position |
| DP-03 | Performance | Time-series NAV, IRR, DPI, RVPI, TVPI |
| DP-04 | Compliance Dashboard | OC/IC/Quality/Concentration tests, PASS/FAIL, breach consequences |
| DP-05 | Cashflows | One row per waterfall step per payment date |
| DP-06 | Fees | Fee and expense ledger |
| DP-07 | Key Metrics Tracker | Weekly WARF, WAS, WAL, diversity score |
| DP-08 | Liability Structure | One row per tranche class |

### Funds

| Fund ID | Backend | Notes |
|---|---|---|
| `DKIG-2024-VII` | Excel + PostgreSQL | 2024 vintage, reinvesting, 12 monthly snapshots |
| `DKIG-2016-I` | Excel + PostgreSQL | 2016 vintage, amortising, 40 quarterly snapshots, 1 active covenant breach (CCC bucket at 7.8% vs 7.5% threshold) |
| `DKIG-2018-CE` | PostgreSQL only | $300M clean energy focus, 97 monthly snapshots |
| `DKIG-2019-TECH` | PostgreSQL only | $400M technology sector focus, 29 quarterly snapshots; load via `db/load_tech_fund.py` |

### Agent Architecture

`agent.py` in each package:
- Loads the JSON-LD ontology (`clo-fund-ontology.jsonld`) into the system prompt with `cache_control: ephemeral` for prompt caching
- Uses `anthropic.beta.messages.tool_runner` with `claude-sonnet-4-6` and all registered tools
- Runs the tool runner in a daemon thread; yields results through a `queue.Queue` to enforce a per-request wall-clock timeout

**Tool naming convention**: `get_*_latest` tools return the most recent single snapshot; `get_*_history` tools return time-series with optional `start_date`/`end_date` filtering. Use `_latest` for current-state questions, `_history` or `compute_period_return` for trends and period-over-period analysis.

### Excel Agent Data Access

`clo_agent/data_access.py` reads the workbook with `openpyxl`. All 8 data functions are decorated with `@lru_cache(maxsize=4)` — the workbook is read once per fund per session. Headers start at row 4 (rows 1–3 are title/subtitle/blank). Fund sheets are prefixed: `DKIG-2016-I` uses `"2016-"` prefix (e.g. `"2016-DP-01 Static Profile"`).

### PostgreSQL Data Access

`clo_db_agent/data_access.py` connects to PostgreSQL using the `DATABASE_URL` env var (default: `host=/tmp port=5432 dbname=postgres`). The DB agent discovers funds dynamically from the database — no code change needed when loading additional funds.

### Synthetic Data Generation

`generate_data.py` regenerates `CLO_Fund_Domain_Data.xlsx` and `clo-fund-ontology.jsonld` from scratch (single fund: DKIG-2024-VII). Run it only when rebuilding the Excel workbook or ontology for development purposes.

---

## Security Controls

Comment tags in the source map to OWASP LLM Top 10 findings:

| Tag | Control |
|---|---|
| AI-01 | Input sanitisation: 500-char cap, NFKC normalisation, 17-pattern blocklist (`_sanitise_input` in `agent.py`) |
| AI-02/AI-08 | Tool result sanitisation: strips injection markers and markdown heading syntax before model re-ingestion (`_to_json()` in `tools.py`) |
| AI-04/AI-07/AI-12/AI-13 | Output safety: system prompt leakage detection; citation warning when financial figures lack fund/DP/date attribution (`_check_output` in `agent.py`) |
| AI-06 | Ontology and workbook SHA-256 integrity checks at startup (env vars `CLO_ONTOLOGY_SHA256`, `CLO_WORKBOOK_SHA256`) |
| AI-09 | Row cap on history tool results: `_MAX_HISTORY_ROWS` (default 200), truncation sentinel appended |
| AI-10 | Tool-call iteration cap per question: `_MAX_TOOL_ITERATIONS` (default 10) |
| AI-15 | Per-session token budget in REPL: `CLO_SESSION_TOKEN_LIMIT` (default 200,000) with 80% warning |
| AI-17 | Per-request wall-clock timeout: `CLO_REQUEST_TIMEOUT_SEC` (default 120s) |

API security (tagged F-01…F-20 in `clo_api/main.py`): API key auth (`X-API-Key` header), CORS allowlist (no wildcard), rate limiting (60 req/min/IP), request logging, generic error handler (no stack traces in responses), Swagger/ReDoc disabled in production.

---

## Environment Variables

| Variable | Default | Component | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | — | Both agents | Required |
| `PORT` | `7860` | Chat server | HTTP port for the browser chat interface |
| `CLO_SESSION_TOKEN_LIMIT` | `200000` | Both agents | Max tokens per REPL session |
| `CLO_REQUEST_TIMEOUT_SEC` | `120` | Both agents | Per-question timeout (s) |
| `CLO_MAX_TOOL_ITERATIONS` | `10` | Both agents | Max tool-call cycles per question |
| `CLO_MAX_HISTORY_ROWS` | `200` | Both agents | Max rows returned by history tools |
| `CLO_ONTOLOGY_SHA256` | *(unset)* | Both agents | Expected SHA-256 of ontology file |
| `CLO_WORKBOOK_SHA256` | *(unset)* | Excel agent | Expected SHA-256 of workbook |
| `CLO_API_KEY` | *(unset)* | REST API | Required for any shared deployment |
| `DATABASE_URL` | `host=/tmp port=5432 dbname=postgres` | DB agent, API | PostgreSQL DSN |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:8000` | REST API | Comma-separated allowed origins |
| `ENVIRONMENT` | *(unset)* | REST API | Set to `production` to disable `/docs` and `/redoc` |

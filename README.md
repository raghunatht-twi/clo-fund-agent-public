# CLO Fund Performance Agent

An AI agent platform that answers questions about CLO fund performance in plain English. Four funds are currently loaded. A browser-based chat interface is the primary way to interact — it supports both a single-agent mode and a multi-agent orchestration mode. A command-line interface and a REST API are also available.

## Documentation

| Document | Description |
|---|---|
| [`docs/user-guide.html`](docs/user-guide.html) | Comprehensive user guide — setup, all entry points, example questions, data product reference, REST API, multi-agent system, portfolio optimizer, configuration, and security controls |
| [`OWASP_AI_Security_Report.html`](OWASP_AI_Security_Report.html) | Full OWASP LLM Top 10 security assessment and remediation report |

| Fund | Vintage | Status |
|---|---|---|
| DKIG Funding 2024-VII LLC | 2024 | Reinvesting, 12 monthly snapshots |
| DKIG Funding 2016-I LLC | 2016 | Amortising, 40 quarterly snapshots, 1 active covenant breach |
| DKIG Clean Energy CLO 2018-I LLC | 2018 | $300M clean energy focus, 97 monthly snapshots |
| DKIG Technology CLO 2019-I LLC | 2019 | $400M technology sector focus, 29 quarterly snapshots |

---

## Prerequisites

- **Python 3.12+**
- **`uv`** — recommended package manager ([install](https://docs.astral.sh/uv/getting-started/installation/))
- **`ANTHROPIC_API_KEY`** — must be set in your environment before running any agent or server
- **PostgreSQL** running locally — required for the chat server, `clo_db_agent`, `clo_api`, and the multi-agent system (tested with PostgreSQL 18 via Homebrew on `host=/tmp port=5432`)

---

## Setup

### 1. Set your API key

```bash
export ANTHROPIC_API_KEY=<your key>
```

### 2. Install dependencies

```bash
uv sync          # installs main + dev dependencies (includes ruff)
git config core.hooksPath .githooks   # activate pre-commit ruff hook (once per clone)
```

### 3. Set up the database

```bash
psql -h /tmp -d postgres -f db/schema.sql
uv run python db/load_data.py          # loads DKIG-2024-VII and DKIG-2016-I
uv run python db/load_ce_fund.py       # loads DKIG-2018-CE (Clean Energy)
uv run python db/load_tech_fund.py     # loads DKIG-2019-TECH (Technology)
```

---

## Browser Chat Interface (recommended)

The chat server wraps both agent backends behind a single web interface. Start it, then open your browser.

```bash
uv run python clo_chat_server.py
```

Open **http://localhost:7860** in your browser.

The interface has two modes, selectable via the toggle in the header:

| Mode | Backend | Best for |
|---|---|---|
| **Single Agent** (green pill) | `clo_db_agent` — one Claude session | Targeted questions about a specific fund or data product |
| **Multi-Agent** (purple pill) | `multi_agent` orchestrator | Complex cross-cutting tasks: distribution reports, compliance + cashflow coordination, portfolio optimisation |

Set the `PORT` environment variable to use a different port:

```bash
PORT=8080 uv run python clo_chat_server.py
```

---

## Multi-Agent System

The multi-agent system coordinates a team of eight Claude Sonnet 4.6 specialists, each responsible for one domain of the CLO fund ontology. An **OrchestratorAgent** decomposes tasks, dispatches specialists (in parallel where tasks are independent), and synthesises results through a shared session memory store.

### Run from the CLI

```bash
uv run python -m multi_agent                                                     # interactive REPL
uv run python -m multi_agent 'Run distribution authorisation for DKIG-2024-VII'  # one-shot
```

### Specialist agents

| Agent | Ontology domain | Data products | Timeout |
|---|---|---|---|
| OrchestratorAgent | All — routes via `clo:retrievalMap` | All | 900 s (stream) |
| PortfolioAgent | `clo:LoanAsset`, `clo:KeyMetricSnapshot` | DP-02, DP-07 | 120 s |
| ComplianceAgent | `clo:OCTest`, `clo:ICTest`, `clo:DiversityTest` | DP-04 | 120 s |
| CashflowAgent | `clo:Waterfall`, `clo:EquityDistribution` | DP-05 | 120 s |
| PerformanceAgent | `clo:PerformanceSnapshot` | DP-03 | 120 s |
| FeeAgent | `clo:ManagementFee`, `clo:IncentiveFee` | DP-06 | 120 s |
| OptimizerAgent | Portfolio return optimisation | DP-02, DP-04 | 900 s † |
| ReportingAgent | Report synthesis from session memory | All | 900 s † |

† OptimizerAgent (up to 150 hill-climbing iterations) and ReportingAgent (reads all session memories and synthesises a full memo) use `CLO_ORCHESTRATOR_TIMEOUT_SEC` for both their `ask()` and `stream()` calls.

### Orchestration model

#### Ontology-driven routing

The orchestrator does not hard-code dispatch logic. It calls `get_ontology_retrieval_map` at runtime to read the `clo:retrievalMap` from the JSON-LD ontology, then routes each part of the task to the correct specialist:

| Ontology class | Specialist dispatched |
|---|---|
| `clo:LoanAsset`, `clo:Obligor`, `clo:KeyMetricSnapshot` | PortfolioAgent |
| `clo:PerformanceSnapshot` | PerformanceAgent |
| `clo:ComplianceTest`, `clo:OCTest`, `clo:ICTest` | ComplianceAgent |
| `clo:Waterfall`, `clo:EquityDistribution` | CashflowAgent |
| `clo:FeeExpense`, `clo:ManagementFee`, `clo:IncentiveFee` | FeeAgent |
| Portfolio return optimisation | OptimizerAgent |
| Final report synthesis | ReportingAgent |

#### Parallel dispatch

When subtasks are independent (for example, fetching different data products), the orchestrator fires multiple specialist agents in a single response turn. For a distribution authorisation, PortfolioAgent, PerformanceAgent, ComplianceAgent, and FeeAgent are dispatched simultaneously, then the orchestrator waits for all four before proceeding.

#### Compliance gate (`clo:WaterfallPriorityAxiom`)

CashflowAgent is **always called after** ComplianceAgent on any distribution task. Per `clo:WaterfallPriorityAxiom`, equity receives nothing if any OC or IC test is failing — compliance results determine which waterfall path (distribution vs. diversion) the cashflow agent models.

#### Optimizer gate

OptimizerAgent is a compute-intensive step (up to 150 hill-climbing iterations) and is called only when one of these conditions holds:

- OC cushion is below 100 bps on any compliance test, or
- a compliance breach exists, or
- the user explicitly requests portfolio optimisation.

### Distribution authorisation workflow

The canonical five-step workflow the orchestrator follows for a distribution authorisation:

```
Step 1  list_available_funds          — discover which funds are loaded (if not specified)

Step 2  PARALLEL dispatch:
          PortfolioAgent              — loan positions, WARF, WAS, WAL  (DP-02, DP-07)
          PerformanceAgent            — NAV, IRR, TVPI                  (DP-03)
          ComplianceAgent             — OC/IC test results and cushions  (DP-04)
          FeeAgent                    — expense ledger                   (DP-06)

Step 3  SEQUENTIAL (waits for Step 2):
          CashflowAgent               — waterfall model using compliance gate result (DP-05)

Step 4  CONDITIONAL (only if cushion < 100 bps or breach):
          OptimizerAgent              — greedy trade recommendations (DP-02, DP-04)

Step 5  ReportingAgent               — reads all session memory, compiles the final memo
```

### Session memory

Specialist agents write their findings to:

```
multi_agent/session_memory/{fund_id}/{session_date}/{agent_name}.json
```

Each file contains the agent's full analysis output for a given fund and date, enabling agents to share findings without re-querying the database. The ReportingAgent reads all outputs to compile consolidated memos. Memory persists between agent calls within the same session date — the orchestrator uses the same `session_date` across all calls in one run.

### Example multi-agent queries

```
Run the Q2-2026 distribution authorisation for all funds
Are all OC/IC tests passing for DKIG-2016-I? If any fail, model the waterfall diversion.
Identify CCC loans in DKIG-2024-VII, stress-test OC cushion, and recommend corrective trades.
Optimise portfolio returns for DKIG-2024-VII — show accepted trades and yield improvement.
Compare performance, compliance, and fees across all four funds.
```

---

## Command-Line Interface

Both single-agent backends can also be used directly from the terminal.

### Excel Agent (`clo_agent`)

Reads directly from `CLO_Fund_Domain_Data.xlsx`. No database required. Available funds: `DKIG-2024-VII` and `DKIG-2016-I`.

```bash
uv run python -m clo_agent 'What is the net IRR for DKIG-2024-VII?'   # one-shot
uv run python -m clo_agent                                              # interactive REPL
```

### PostgreSQL Agent (`clo_db_agent`)

Reads from PostgreSQL. Discovers all loaded funds dynamically.

```bash
uv run python -m clo_db_agent 'What is the net IRR for DKIG-2024-VII?'   # one-shot
uv run python -m clo_db_agent                                              # interactive REPL
```

### REPL vs one-shot

The REPL keeps the Anthropic prompt cache warm across questions (5-minute TTL), so subsequent queries cost substantially less. One-shot mode is best for scripting.

---

## REST API (`clo_api`)

Exposes all 8 data products as JSON endpoints. Requires PostgreSQL.

```bash
uv run uvicorn clo_api.main:app --host 127.0.0.1 --port 8000          # development
uv run gunicorn clo_api.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000  # production
```

Set `CLO_API_KEY` to enable API key authentication (required for any shared deployment). Swagger UI at `http://127.0.0.1:8000/docs` (disabled when `ENVIRONMENT=production`).

---

## Data Products

All agents expose all 8 data products. The Excel agent reads from `CLO_Fund_Domain_Data.xlsx`; the DB agent and multi-agent system read from the corresponding PostgreSQL tables (`dp01_fund_static_profile` … `dp08_liability_structure`).

| ID | Data Product | Key Fields |
|---|---|---|
| DP-01 | Fund Static Profile | Fund name, manager, vintage, closing date, fee rates |
| DP-02 | Portfolio Snapshot | Loan positions, obligor names, prices, ratings, spread, maturity |
| DP-03 | Performance | NAV, IRR, DPI, RVPI, TVPI, P&L, benchmark return |
| DP-04 | Compliance Dashboard | OC/IC/Quality/Concentration tests, cushions, breach consequences |
| DP-05 | Cashflows | Waterfall steps, equity distributions, fees paid |
| DP-06 | Fees | Management, incentive, trustee, admin, TER |
| DP-07 | Key Metrics Tracker | WARF, WAS, WAL, diversity score, CCC%, concentrations |
| DP-08 | Liability Structure | Tranche stack, ratings, OC/IC cushions per class, amortisation |

---

## Development

### Linting

```bash
uv run ruff check .         # check
uv run ruff check . --fix   # auto-fix safe issues
```

Rules: `E`, `F`, `W`. Line length: 100. `E501` is suppressed in `db/` and `generate_data.py`.

### Regenerating synthetic data

`generate_data.py` regenerates `CLO_Fund_Domain_Data.xlsx` and `clo-fund-ontology.jsonld` from scratch (single fund: DKIG-2024-VII). Run it only when rebuilding the Excel workbook or ontology for development.

---

## Environment Variables

| Variable | Default | Applies to | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | *(must be set)* | All agents | Anthropic API key |
| `PORT` | `7860` | Chat server | HTTP port for the browser chat interface |
| `DATABASE_URL` | `host=/tmp port=5432 dbname=postgres` | DB agent, multi-agent, API, chat server | PostgreSQL DSN |
| `CLO_SESSION_TOKEN_LIMIT` | `200000` | Single agents | Max cumulative tokens per REPL session |
| `CLO_REQUEST_TIMEOUT_SEC` | `120` | Fast specialist agents | Default per-agent timeout — Portfolio, Compliance, Cashflow, Performance, Fee |
| `CLO_ORCHESTRATOR_TIMEOUT_SEC` | `900` | Orchestrator, Optimizer, Reporting, chat SSE (multi) | Extended timeout for slow agents and the orchestrator outer loop |
| `CLO_MAX_TOOL_ITERATIONS` | `10` | All agents | Max tool-call cycles per question |
| `CLO_MAX_HISTORY_ROWS` | `200` | All agents | Max rows returned per history tool call |
| `CLO_ONTOLOGY_SHA256` | *(unset)* | All agents | Expected SHA-256 of `clo-fund-ontology.jsonld` |
| `CLO_WORKBOOK_SHA256` | *(unset)* | Excel agent | Expected SHA-256 of `CLO_Fund_Domain_Data.xlsx` |
| `CLO_API_KEY` | *(unset)* | REST API | API key callers must send in `X-API-Key` header |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:8000` | REST API | Comma-separated allowed CORS origins |
| `ENVIRONMENT` | *(unset)* | REST API | Set to `production` to disable `/docs` and `/redoc` |

---

## Security

All OWASP LLM Top 10 (2025) AI-security findings have been remediated — see [`OWASP_AI_Security_Report.html`](OWASP_AI_Security_Report.html). All agents (single and multi) share the same controls via `_shared.py` in the multi-agent package and the existing `agent.py` security layer:

- **Prompt injection guard** — 500-char input cap, NFKC Unicode normalisation, 17-pattern blocklist
- **Tool result sanitisation** — injection markers and markdown syntax stripped before model re-ingestion
- **Output safety checks** — system prompt leakage detection; citation warning when financial figures lack fund/data-product/date attribution
- **Session token budget** — configurable per-session token cap with 80% warning in the REPL
- **Request timeout** — per-agent wall-clock timeout via daemon thread; both `ask()` and `stream()` use the per-class `STREAM_TIMEOUT_SEC` (120 s for fast specialists, 900 s for Optimizer, Reporting, and the Orchestrator)
- **Tool call cap** — maximum 10 tool-call iterations per agent per question
- **Row limits** — history tools cap at 200 rows with a truncation sentinel
- **Ontology integrity** — SHA-256 hash verified at startup if env var is set

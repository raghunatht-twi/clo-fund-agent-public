# DKIG CLO Fund Data API

This document covers two HTTP interfaces:

| Interface | Port | Purpose |
|---|---|---|
| **Data API** (`clo_api`) | 8000 | REST endpoints — raw JSON for all 8 data products |
| **Chat Agent API** (`clo_chat_server`) | 7860 | SSE streaming — natural-language queries via single-agent or multi-agent orchestration |

The Data API serves structured fund data directly. The Chat Agent API accepts plain-English questions and streams responses from a Claude Sonnet 4.6 agent (or a team of eight specialist agents in multi-agent mode).

---

The sections below document the **Data API** first, followed by the Chat Agent API.

---

## Quick Start

### 1. Install dependencies

```bash
cd "/Users/raghunatht/Documents/Delivery/NA BFSI/DKIG/CLO Funds"
source .venv/bin/activate
pip install fastapi uvicorn psycopg2-binary
```

### 2. Start the API server

```bash
uvicorn clo_api.main:app --host 127.0.0.1 --port 8000
```

The server binds to localhost only (`http://localhost:8000`). Do **not** use
`--host 0.0.0.0` or `--reload` in any environment other than an isolated dev
machine — see the [TLS / Production Deployment](#tls--production-deployment)
section below before exposing this service to any network.

### 3. Browse the interactive docs

Open in a browser:

```
http://localhost:8000/docs
```

This opens the Swagger UI where you can explore every endpoint and run live queries without writing any code.

---

## TLS / Production Deployment

**Never run the API directly on a public interface without TLS.** All traffic must
travel over HTTPS so that API keys and fund data are not transmitted in plaintext.

The recommended pattern is to run the API bound to `127.0.0.1` and place a
TLS-terminating reverse proxy in front of it.

### nginx (recommended for on-prem / VPS)

```nginx
server {
    listen 443 ssl;
    server_name api.example.com;

    ssl_certificate     /etc/ssl/certs/api.example.com.crt;
    ssl_certificate_key /etc/ssl/private/api.example.com.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
    }
}
```

Start the API (no `--reload`, bound to localhost only):

```bash
uvicorn clo_api.main:app --host 127.0.0.1 --port 8000
```

Set the required environment variables before starting:

```bash
export CLO_API_KEY="<strong-random-key>"
export DATABASE_URL="host=/tmp port=5432 dbname=postgres"
export ENVIRONMENT="production"   # disables /docs and /redoc
```

### Caddy (automatic TLS via Let's Encrypt)

```caddyfile
api.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy handles certificate provisioning and renewal automatically.

---

## Exposing the API to the Internet

### Option A — ngrok (fastest, free tier available)

ngrok creates a public HTTPS URL that tunnels to your local server.

```bash
# Install ngrok (macOS)
brew install ngrok

# Authenticate (one-time — get your token at https://dashboard.ngrok.com)
ngrok config add-authtoken <YOUR_TOKEN>

# With the API already running on port 8000, open a new terminal:
ngrok http 8000
```

ngrok prints a public URL, for example:

```
Forwarding   https://a1b2c3d4.ngrok-free.app -> http://localhost:8000
```

Anyone on the internet can now call:

```
https://a1b2c3d4.ngrok-free.app/funds
https://a1b2c3d4.ngrok-free.app/funds/DKIG-2024-VII/performance/latest
```

The ngrok URL changes each time you restart. Use a paid ngrok plan or a custom domain for a stable URL.

### Option B — Cloud deployment (permanent URL)

Deploy the API to a cloud platform so it runs 24/7 without your laptop.

**Railway** (recommended — free tier available):

```bash
# Install the Railway CLI
brew install railway

# Login and create a new project
railway login
railway init

# Set the start command in Railway dashboard:
#   uvicorn clo_api.main:app --host 0.0.0.0 --port $PORT  # cloud platforms bind 0.0.0.0 via PORT env var

# Deploy
railway up
```

Set the `DATABASE_URL` environment variable in Railway to point at your PostgreSQL instance (Railway can also provision a managed PostgreSQL database).

**Render** — similar steps; connect your GitHub repo and set the start command to `uvicorn clo_api.main:app --host 0.0.0.0 --port $PORT` (cloud platforms require `0.0.0.0`; TLS is terminated by the platform's load balancer).

---

## API Reference

Replace `{BASE_URL}` with `http://localhost:8000` (local) or your ngrok/cloud URL.

### Discover available funds

```bash
# List all fund IDs in the database
curl {BASE_URL}/funds
```

```json
{
  "funds": ["DKIG-2016-I", "DKIG-2024-VII"]
}
```

---

### DP-01 — Fund Static Profile

```bash
curl {BASE_URL}/funds/DKIG-2024-VII
curl {BASE_URL}/funds/DKIG-2016-I
```

Returns fund name, manager, vintage year, closing date, reinvestment period end, legal maturity, target par, fee rates.

---

### DP-02 — Portfolio Snapshot

```bash
curl {BASE_URL}/funds/DKIG-2024-VII/portfolio
```

Returns all loan positions — obligor, par, market value, price, spread, maturity, ratings, PIK flag, covenant-lite flag.

---

### DP-03 — Performance

```bash
# Latest snapshot only
curl {BASE_URL}/funds/DKIG-2024-VII/performance/latest
curl {BASE_URL}/funds/DKIG-2016-I/performance/latest

# Full history
curl {BASE_URL}/funds/DKIG-2016-I/performance

# Filtered by date range
curl "{BASE_URL}/funds/DKIG-2016-I/performance?start_date=2020-01-01&end_date=2021-12-31"
```

Returns NAV, gross/net IRR, DPI, RVPI, TVPI, P&L, interest income, benchmark return, excess return.

---

### DP-04 — Compliance Dashboard

```bash
curl {BASE_URL}/funds/DKIG-2024-VII/compliance
curl {BASE_URL}/funds/DKIG-2016-I/compliance
```

Returns all OC/IC/quality/concentration test results — current value, threshold, cushion, PASS/FAIL, breach consequence.

> **Note:** DKIG-2016-I has one active FAIL — the CCC/Caa bucket is at 7.8% vs the 7.5% threshold.

---

### DP-05 — Cashflows

```bash
# Full waterfall history
curl {BASE_URL}/funds/DKIG-2024-VII/cashflows

# Latest equity distribution only
curl {BASE_URL}/funds/DKIG-2024-VII/cashflows/equity-distribution/latest
```

Returns waterfall steps across payment dates — interest/principal proceeds, each recipient, amounts disbursed, OC diversions, equity distributions, fees paid.

---

### DP-06 — Fees

```bash
curl {BASE_URL}/funds/DKIG-2024-VII/fees
curl {BASE_URL}/funds/DKIG-2016-I/fees
```

Returns the fee and expense ledger — management fee (senior & subordinated), incentive fee, trustee, admin, legal, rating agency, tax provision, total expense ratio.

---

### DP-07 — Key Metrics

```bash
# Latest snapshot only
curl {BASE_URL}/funds/DKIG-2024-VII/metrics/latest

# Full weekly history
curl {BASE_URL}/funds/DKIG-2024-VII/metrics

# Filtered by date range
curl "{BASE_URL}/funds/DKIG-2024-VII/metrics?start_date=2026-04-01&end_date=2026-04-30"
```

Returns WARF, WAS, WAL, WAC, weighted average recovery rate, par build/loss, % floating, % CCC/Caa, % covenant-lite, diversity score, obligor and industry counts, concentration metrics.

---

### DP-08 — Liability Structure

```bash
curl {BASE_URL}/funds/DKIG-2024-VII/liability
curl {BASE_URL}/funds/DKIG-2016-I/liability
```

Returns the full tranche stack — class, CUSIP, initial/current notional, coupon, ratings, subordination level, OC/IC cushion, waterfall priority, cumulative principal repaid, accrued interest.

---

## Endpoint Summary

| Endpoint | Data Product | Description |
|---|---|---|
| `GET /funds` | — | List all fund IDs |
| `GET /funds/{fund_id}` | DP-01 | Static profile |
| `GET /funds/{fund_id}/portfolio` | DP-02 | Loan positions |
| `GET /funds/{fund_id}/performance/latest` | DP-03 | Latest NAV / IRR / multiples |
| `GET /funds/{fund_id}/performance` | DP-03 | Full history (date filter optional) |
| `GET /funds/{fund_id}/compliance` | DP-04 | OC/IC covenant tests |
| `GET /funds/{fund_id}/cashflows` | DP-05 | Waterfall cashflow history |
| `GET /funds/{fund_id}/cashflows/equity-distribution/latest` | DP-05 | Latest equity distribution |
| `GET /funds/{fund_id}/fees` | DP-06 | Fee & expense ledger |
| `GET /funds/{fund_id}/metrics/latest` | DP-07 | Latest WARF / WAS / diversity |
| `GET /funds/{fund_id}/metrics` | DP-07 | Full quality history (date filter optional) |
| `GET /funds/{fund_id}/liability` | DP-08 | Tranche stack |

All endpoints return `application/json`. Date filters use ISO format `YYYY-MM-DD`.

---

## Chat Agent API

The chat server (`clo_chat_server.py`) runs on port 7860 and exposes two endpoints: the browser UI at `/` and an SSE streaming agent endpoint at `/ask`. Both single-agent and multi-agent orchestration modes are accessible via the same endpoint.

### Start the chat server

```bash
uv run python clo_chat_server.py           # default port 7860
PORT=8080 uv run python clo_chat_server.py  # custom port
```

Requires `ANTHROPIC_API_KEY` and a running PostgreSQL instance (same `DATABASE_URL` as the Data API).

---

### `POST /ask`

Accepts a natural-language question and streams the agent response as [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events).

**Request body** (`application/json`):

| Field | Type | Required | Description |
|---|---|---|---|
| `question` | string | yes | Natural-language question, max 500 characters |
| `mode` | `"single"` \| `"multi"` | no | Agent mode (default `"single"`) |

**SSE event stream** — each event is a JSON object on a `data:` line:

| `type` | When emitted | Fields |
|---|---|---|
| `tool_call` | Each tool invocation during reasoning | `text`: `"→ tool_name(args)"` |
| `answer` | Final response (once, after all tool calls) | `text`: full markdown answer |
| `warning` | Token budget near limit, or incomplete result | `text`: warning message |
| `error` | Agent or timeout error | `message`: error string |
| `done` | Stream complete (always last) | — |

---

#### Single-agent mode (`"mode": "single"`)

Routes the question to a single `clo_db_agent` session. Best for targeted questions about a specific fund or data product.

```bash
curl -N -X POST http://localhost:7860/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the net IRR for DKIG-2024-VII?", "mode": "single"}'
```

```
data: {"type": "tool_call", "text": "→ list_available_funds()"}
data: {"type": "tool_call", "text": "→ get_performance_latest(fund_id='DKIG-2024-VII')"}
data: {"type": "answer", "text": "**Net IRR** — DKIG-2024-VII (DP-03, 2026-04-30): **12.4%**\n\n..."}
data: {"type": "done"}
```

Timeout: 135 seconds (configurable via `CLO_REQUEST_TIMEOUT_SEC` + 15 s buffer).

---

#### Multi-agent mode (`"mode": "multi"`)

Routes the question to the `OrchestratorAgent`, which decomposes the task, dispatches specialist agents in parallel where possible, and synthesises results through shared session memory.

```bash
curl -N -X POST http://localhost:7860/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Run distribution authorisation for DKIG-2024-VII", "mode": "multi"}'
```

```
data: {"type": "tool_call", "text": "→ list_available_funds()"}
data: {"type": "tool_call", "text": "→ call_portfolio_agent(fund_id='DKIG-2024-VII', ...)"}
data: {"type": "tool_call", "text": "→ call_performance_agent(fund_id='DKIG-2024-VII', ...)"}
data: {"type": "tool_call", "text": "→ call_compliance_agent(fund_id='DKIG-2024-VII', ...)"}
data: {"type": "tool_call", "text": "→ call_fee_agent(fund_id='DKIG-2024-VII', ...)"}
data: {"type": "tool_call", "text": "→ call_cashflow_agent(fund_id='DKIG-2024-VII', ...)"}
data: {"type": "tool_call", "text": "→ call_reporting_agent(fund_id='DKIG-2024-VII', ...)"}
data: {"type": "answer", "text": "## Distribution Authorisation — DKIG-2024-VII\n\n..."}
data: {"type": "done"}
```

Timeout: `CLO_ORCHESTRATOR_TIMEOUT_SEC` + 60 s (default 960 s). Multi-agent runs involve sequential specialist calls — keep the connection open.

The orchestrator follows a five-step workflow for distribution tasks:

```
Step 1  list_available_funds
Step 2  PARALLEL: PortfolioAgent + PerformanceAgent + ComplianceAgent + FeeAgent
Step 3  SEQUENTIAL: CashflowAgent  (waits for compliance gate result)
Step 4  CONDITIONAL: OptimizerAgent  (only if OC cushion < 100 bps or breach)
Step 5  ReportingAgent  (synthesises all session memory into the final memo)
```

---

#### JavaScript example (`EventSource`)

```javascript
async function ask(question, mode = "single") {
  const resp = await fetch("http://localhost:7860/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, mode }),
  });

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    for (const line of buffer.split("\n\n")) {
      if (!line.startsWith("data: ")) continue;
      const event = JSON.parse(line.slice(6));
      if (event.type === "answer") console.log(event.text);
      if (event.type === "error")  console.error(event.message);
      if (event.type === "done")   break;
    }
    buffer = "";
  }
}

ask("Compare IRR across all funds", "multi");
```

---

### Rate limiting and concurrency

| Control | Limit | Applies to |
|---|---|---|
| Rate limit | 30 requests / minute / IP | All `/ask` requests |
| Concurrency cap | 5 simultaneous agent calls | All `/ask` requests |

Requests that exceed the concurrency cap receive `503 Service Unavailable`. Requests that exceed the rate limit receive `429 Too Many Requests`.

### CORS

Allowed origins are set via the `CHAT_CORS_ORIGINS` environment variable (default: `http://localhost:7860`). No wildcard origins are permitted.

---

## Available Fund IDs

| Fund ID | Fund Name | Vintage | Status |
|---|---|---|---|
| `DKIG-2024-VII` | DKIG Funding 2024-VII LLC | 2024 | Reinvesting — latest data Apr 2026 |
| `DKIG-2016-I` | DKIG Funding 2016-I LLC | 2016 | Amortising — latest data Mar 2026 |

> The API dynamically discovers funds from the database. Additional funds loaded via `db/load_data.py` are immediately available without restarting the server.

---

## Interactive Documentation

The API ships with two built-in documentation UIs:

| URL | Description |
|---|---|
| `/docs` | Swagger UI — interactive, run requests in the browser |
| `/redoc` | ReDoc — clean, readable reference |

---

*Data source: synthetic sample data — DKIG Asset Management LLC*

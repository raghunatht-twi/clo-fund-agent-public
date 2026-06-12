"""DKIG CLO Fund Data API — FastAPI application.

Exposes all 8 data products (DP-01 through DP-08) for every fund in the
PostgreSQL database as JSON REST endpoints.

Run (development):
    uvicorn clo_api.main:app --host 127.0.0.1 --port 8000

Run (production — behind a TLS-terminating reverse proxy such as nginx/Caddy):
    gunicorn clo_api.main:app -w 4 -k uvicorn.workers.UvicornWorker \\
        --bind 127.0.0.1:8000

Environment variables:
    CLO_API_KEY    Required API key callers must send in the X-API-Key header.
                   If unset, authentication is DISABLED (development only).
    DATABASE_URL   PostgreSQL DSN. Defaults to "host=/tmp port=5432 dbname=postgres".
    CORS_ORIGINS   Comma-separated list of allowed CORS origins.
                   Defaults to "http://localhost:3000,http://localhost:8000".
    ENVIRONMENT    Set to "production" to disable /docs and /redoc.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402
from fastapi.security import APIKeyHeader  # noqa: E402

import clo_db_agent.data_access as da  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s  %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("clo_api")

# ---------------------------------------------------------------------------
# Auth  (F-01, F-07, F-11, F-20)
# ---------------------------------------------------------------------------
_API_KEY = os.environ.get("CLO_API_KEY", "")
if not _API_KEY:
    logger.warning(
        "CLO_API_KEY is not set — authentication DISABLED. "
        "Set CLO_API_KEY before deploying to any shared or public network."
    )

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _verify_api_key(key: str | None = Security(_api_key_header)) -> None:
    """Require X-API-Key header when CLO_API_KEY env var is configured."""
    if _API_KEY and key != _API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key.")


# ---------------------------------------------------------------------------
# CORS  (F-02)
# ---------------------------------------------------------------------------
_raw_origins = os.environ.get(
    "CORS_ORIGINS", "http://localhost:3000,http://localhost:8000"
)
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# ---------------------------------------------------------------------------
# App  (F-01, F-07)
# ---------------------------------------------------------------------------
_is_production = os.environ.get("ENVIRONMENT", "").lower() == "production"
if _is_production and not _API_KEY:
    sys.exit("FATAL: CLO_API_KEY must be set when ENVIRONMENT=production.")

app = FastAPI(
    title="DKIG CLO Fund Data API",
    description=(
        "REST API serving all 8 CLO fund data products (DP-01 – DP-08) "
        "for funds managed by **DKIG Asset Management LLC**.\n\n"
        "**Authentication:** Supply your API key in the `X-API-Key` request header.\n\n"
        "| Data Product | Endpoint |\n"
        "|---|---|\n"
        "| DP-01 Fund Static Profile | `GET /funds/{fund_id}` |\n"
        "| DP-02 Portfolio Snapshot | `GET /funds/{fund_id}/portfolio` |\n"
        "| DP-03 Performance | `GET /funds/{fund_id}/performance` |\n"
        "| DP-04 Compliance | `GET /funds/{fund_id}/compliance` |\n"
        "| DP-05 Cashflows | `GET /funds/{fund_id}/cashflows` |\n"
        "| DP-06 Fees | `GET /funds/{fund_id}/fees` |\n"
        "| DP-07 Key Metrics | `GET /funds/{fund_id}/metrics` |\n"
        "| DP-08 Liability Structure | `GET /funds/{fund_id}/liability` |\n"
    ),
    version="1.1.0",
    contact={"name": "DKIG Asset Management LLC"},
    # Disable interactive docs in production  (F-07)
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    # Global auth dependency — applies to every route  (F-01, F-11)
    dependencies=[Depends(_verify_api_key)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,          # no wildcard  (F-02)
    allow_methods=["GET"],
    allow_headers=["X-API-Key"],
)

# ---------------------------------------------------------------------------
# Request logging middleware  (F-09)
# ---------------------------------------------------------------------------
@app.middleware("http")
async def _log_requests(request: Request, call_next: Any) -> Response:
    start = time.time()
    response = await call_next(request)
    logger.info(
        "method=%s path=%s status=%d duration_ms=%.1f client=%s",
        request.method,
        request.url.path,
        response.status_code,
        round((time.time() - start) * 1000, 1),
        request.client.host if request.client else "unknown",
    )
    return response


# ---------------------------------------------------------------------------
# Rate limiting middleware  (F-08)
# ---------------------------------------------------------------------------
_RATE_WINDOW = 60     # seconds
_RATE_LIMIT   = 60    # max requests per window per IP
_rate_buckets: dict[str, list[float]] = defaultdict(list)


@app.middleware("http")
async def _rate_limit(request: Request, call_next: Any) -> Response:
    client = request.client.host if request.client else "unknown"
    now = time.time()
    cutoff = now - _RATE_WINDOW
    bucket = _rate_buckets[client]
    _rate_buckets[client] = [t for t in bucket if t > cutoff]
    if len(_rate_buckets[client]) >= _RATE_LIMIT:
        logger.warning("Rate limit exceeded for client=%s", client)
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded. Maximum 60 requests per minute."},
        )
    _rate_buckets[client].append(now)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Global exception handler — suppress stack traces  (F-18)
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def _generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception on %s", request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error. Please contact the administrator."},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _serial(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


def _resp(data: Any) -> JSONResponse:
    return JSONResponse(content=json.loads(json.dumps(data, default=_serial)))


def _fund_or_404(fund_id: str) -> None:
    """Raise 404 without disclosing the fund list.  (F-05)"""
    if fund_id not in da.list_funds():
        raise HTTPException(status_code=404, detail="Fund not found.")


# ---------------------------------------------------------------------------
# Root — API overview
# ---------------------------------------------------------------------------
@app.get("/", tags=["Info"], summary="API overview")
def root() -> JSONResponse:
    """Returns API metadata and endpoint map."""
    return _resp({
        "api": "DKIG CLO Fund Data API",
        "version": "1.1.0",
        "endpoints": {
            "list_funds":          "GET /funds",
            "static_profile":      "GET /funds/{fund_id}",
            "portfolio":           "GET /funds/{fund_id}/portfolio",
            "performance_latest":  "GET /funds/{fund_id}/performance/latest",
            "performance_history": "GET /funds/{fund_id}/performance?start_date=&end_date=",
            "compliance":          "GET /funds/{fund_id}/compliance",
            "cashflows":           "GET /funds/{fund_id}/cashflows",
            "equity_distribution": "GET /funds/{fund_id}/cashflows/equity-distribution/latest",
            "fees":                "GET /funds/{fund_id}/fees",
            "metrics_latest":      "GET /funds/{fund_id}/metrics/latest",
            "metrics_history":     "GET /funds/{fund_id}/metrics?start_date=&end_date=",
            "liability_structure": "GET /funds/{fund_id}/liability",
        },
    })


# ---------------------------------------------------------------------------
# /funds  (F-11 — protected by global auth dependency)
# ---------------------------------------------------------------------------
@app.get("/funds", tags=["Funds"], summary="List available fund IDs")
def list_funds() -> JSONResponse:
    """Returns all fund IDs present in the database."""
    return _resp({"funds": da.list_funds()})


# ---------------------------------------------------------------------------
# DP-01 Fund Static Profile
# ---------------------------------------------------------------------------
@app.get("/funds/{fund_id}", tags=["DP-01 Static Profile"],
         summary="Fund static profile (DP-01)")
def get_static_profile(fund_id: str) -> JSONResponse:
    """
    **DP-01 Fund Static Profile** — immutable reference data for the fund.

    Fields: fund name, manager, vintage year, closing date, reinvestment period end,
    non-call period end, legal final maturity, target par amount, base currency,
    management fee rate, incentive hurdle.
    """
    _fund_or_404(fund_id)
    return _resp(da.static_profile(fund_id))


# ---------------------------------------------------------------------------
# DP-02 Portfolio Snapshot
# ---------------------------------------------------------------------------
@app.get("/funds/{fund_id}/portfolio", tags=["DP-02 Portfolio"],
         summary="Loan-level portfolio snapshot (DP-02)")
def get_portfolio(fund_id: str) -> JSONResponse:
    """
    **DP-02 Portfolio Snapshot** — current loan positions.

    Fields: obligor name, facility CUSIP, industry, par amount, market value,
    price (% par), SOFR spread, maturity date, ratings, PIK flag,
    covenant-lite flag, days past due.
    """
    _fund_or_404(fund_id)
    return _resp(da.portfolio(fund_id))


# ---------------------------------------------------------------------------
# DP-03 Performance
# ---------------------------------------------------------------------------
@app.get("/funds/{fund_id}/performance/latest", tags=["DP-03 Performance"],
         summary="Latest performance snapshot (DP-03)")
def get_latest_performance(fund_id: str) -> JSONResponse:
    """
    **DP-03 Performance** — most recent snapshot.

    Fields: total fund NAV, equity NAV, gross/net IRR, DPI, RVPI, TVPI,
    inception-to-date P&L, current period P&L, unrealised/realised G&L,
    total interest income, benchmark return, excess return.
    """
    _fund_or_404(fund_id)
    rows = da.performance(fund_id)
    if not rows:
        raise HTTPException(status_code=404, detail="No performance data found.")
    return _resp(rows[-1])


@app.get("/funds/{fund_id}/performance", tags=["DP-03 Performance"],
         summary="Performance history (DP-03)")
def get_performance_history(
    fund_id: str,
    start_date: date | None = Query(        # F-12: validated date type
        None,
        description="Filter from this date inclusive (YYYY-MM-DD)",
    ),
    end_date: date | None = Query(
        None,
        description="Filter to this date inclusive (YYYY-MM-DD)",
    ),
) -> JSONResponse:
    """
    **DP-03 Performance** — full history, optionally filtered by date range.

    Use `start_date` and `end_date` (YYYY-MM-DD) to narrow the range.
    Returns HTTP 422 for malformed dates.
    """
    _fund_or_404(fund_id)
    rows = da.performance(fund_id)
    if start_date:
        rows = [r for r in rows if r["Reporting Date"] >= start_date.isoformat()]
    if end_date:
        rows = [r for r in rows if r["Reporting Date"] <= end_date.isoformat()]
    return _resp(rows)


# ---------------------------------------------------------------------------
# DP-04 Compliance Dashboard
# ---------------------------------------------------------------------------
@app.get("/funds/{fund_id}/compliance", tags=["DP-04 Compliance"],
         summary="Covenant compliance dashboard (DP-04)")
def get_compliance(fund_id: str) -> JSONResponse:
    """
    **DP-04 Compliance Dashboard** — status of every covenant test.

    Fields: test ID, name, type (OC/IC/Quality/Concentration), tranche class,
    current value, threshold, cushion, PASS/FAIL, breach consequence, last tested.
    """
    _fund_or_404(fund_id)
    return _resp(da.compliance(fund_id))


# ---------------------------------------------------------------------------
# DP-05 Cashflows
# ---------------------------------------------------------------------------
@app.get("/funds/{fund_id}/cashflows/equity-distribution/latest",
         tags=["DP-05 Cashflows"],
         summary="Latest equity distribution (DP-05)")
def get_latest_equity_distribution(fund_id: str) -> JSONResponse:
    """
    **DP-05 Cashflows** — most recent equity distribution waterfall step.

    Returns the last 'Equity Distribution' row from the cashflow waterfall.
    """
    _fund_or_404(fund_id)
    rows = da.cashflows(fund_id)
    eq = [r for r in rows if "Equity Distribution" in str(r.get("Waterfall Step", ""))]
    if not eq:
        raise HTTPException(status_code=404, detail="No equity distribution rows found.")
    return _resp(eq[-1])


@app.get("/funds/{fund_id}/cashflows", tags=["DP-05 Cashflows"],
         summary="Full cashflow waterfall history (DP-05)")
def get_cashflows(fund_id: str) -> JSONResponse:
    """
    **DP-05 Cashflows** — complete waterfall across all recent payment dates.

    Fields: payment date, collection period, interest/principal proceeds,
    waterfall step, recipient, amount disbursed, OC diversion, equity
    distribution, fees paid.
    """
    _fund_or_404(fund_id)
    return _resp(da.cashflows(fund_id))


# ---------------------------------------------------------------------------
# DP-06 Fees
# ---------------------------------------------------------------------------
@app.get("/funds/{fund_id}/fees", tags=["DP-06 Fees"],
         summary="Fee & expense ledger (DP-06)")
def get_fees(fund_id: str) -> JSONResponse:
    """
    **DP-06 Fee & Expense Ledger** — current period fee breakdown.

    Fee types: Management (Senior & Subordinated), Incentive, Trustee,
    Admin, Legal, Rating Agency, Tax Provision, TER.
    """
    _fund_or_404(fund_id)
    return _resp(da.fees(fund_id))


# ---------------------------------------------------------------------------
# DP-07 Key Metrics
# ---------------------------------------------------------------------------
@app.get("/funds/{fund_id}/metrics/latest", tags=["DP-07 Key Metrics"],
         summary="Latest portfolio quality metrics (DP-07)")
def get_latest_metrics(fund_id: str) -> JSONResponse:
    """
    **DP-07 Key Metrics Tracker** — most recent portfolio quality snapshot.

    Fields: WAS, WARF, WAL, WAC, weighted avg recovery rate, par build/loss,
    % floating, % PIK, % CCC/Caa, % covenant-lite, diversity score,
    obligor and industry counts, top-10 concentration.
    """
    _fund_or_404(fund_id)
    rows = da.key_metrics(fund_id)
    if not rows:
        raise HTTPException(status_code=404, detail="No metrics data found.")
    return _resp(rows[-1])


@app.get("/funds/{fund_id}/metrics", tags=["DP-07 Key Metrics"],
         summary="Portfolio quality metrics history (DP-07)")
def get_metrics_history(
    fund_id: str,
    start_date: date | None = Query(        # F-12: validated date type
        None,
        description="Filter from this date inclusive (YYYY-MM-DD)",
    ),
    end_date: date | None = Query(
        None,
        description="Filter to this date inclusive (YYYY-MM-DD)",
    ),
) -> JSONResponse:
    """
    **DP-07 Key Metrics Tracker** — history, optionally filtered by date range.

    Returns HTTP 422 for malformed dates.
    """
    _fund_or_404(fund_id)
    rows = da.key_metrics(fund_id)
    if start_date:
        rows = [r for r in rows if r["Reporting Date"] >= start_date.isoformat()]
    if end_date:
        rows = [r for r in rows if r["Reporting Date"] <= end_date.isoformat()]
    return _resp(rows)


# ---------------------------------------------------------------------------
# DP-08 Liability Structure
# ---------------------------------------------------------------------------
@app.get("/funds/{fund_id}/liability", tags=["DP-08 Liability Structure"],
         summary="Tranche / liability structure (DP-08)")
def get_liability_structure(fund_id: str) -> JSONResponse:
    """
    **DP-08 Fund Liability Structure** — full tranche stack.

    Fields: CUSIP, initial/current notional, coupon type and rate,
    ratings, subordination level, OC/IC cushion, waterfall priority,
    cumulative principal repaid, interest paid, accrued interest, rating outlook.
    """
    _fund_or_404(fund_id)
    return _resp(da.liability_structure(fund_id))

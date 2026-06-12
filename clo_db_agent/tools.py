"""Typed tool surface for the CLO DB agent.

Works against any fund present in the PostgreSQL database — not limited to
the two funds that were loaded initially.  fund_id is a required parameter
on every data tool so the agent always queries a specific fund.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from typing import Any

import clo_analytics
from anthropic import beta_tool

from . import data_access as da

logger = logging.getLogger(__name__)

_EQUITY_DISTRIBUTION_STEP = "Equity Distribution"

# ---------------------------------------------------------------------------
# AI-09: Maximum rows returned per tool call  (configurable via env var)
# ---------------------------------------------------------------------------
_MAX_HISTORY_ROWS: int = int(os.environ.get("CLO_MAX_HISTORY_ROWS", "200"))

# ---------------------------------------------------------------------------
# AI-02 / AI-08: Tool result sanitization
# Strips common injection markers and normalises whitespace in text fields
# before the data is re-ingested by the model.
# ---------------------------------------------------------------------------
_INJECTION_MARKER_RE = re.compile(
    r"\[/?(?:SYSTEM|USER|HUMAN|ASSISTANT|INST|SYS)\]\s*:?",
    re.IGNORECASE,
)
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_HEADING_SYNTAX_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)


def _clean_str(value: str) -> str:
    """Remove injection markers and normalise whitespace in a string field."""
    value = _INJECTION_MARKER_RE.sub("", value)
    value = _HEADING_SYNTAX_RE.sub("", value)
    value = _MULTI_NEWLINE_RE.sub("\n\n", value)
    return value.strip()


def _sanitise_value(obj: Any) -> Any:
    """Recursively sanitize string values in a tool result before serialization."""
    if isinstance(obj, str):
        return _clean_str(obj)
    if isinstance(obj, dict):
        return {k: _sanitise_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitise_value(item) for item in obj]
    return obj


def _to_json(obj: Any) -> str:
    """Sanitize and serialize a tool return value to JSON.

    AI-02/AI-08: Sanitizes free-text fields before model re-ingestion.
    AI-09: Caps list results at _MAX_HISTORY_ROWS with a truncation note.
    """
    sanitized = _sanitise_value(obj)
    if isinstance(sanitized, list) and len(sanitized) > _MAX_HISTORY_ROWS:
        total = len(sanitized)
        logger.warning(
            "Tool result truncated from %d to %d rows (CLO_MAX_HISTORY_ROWS=%d).",
            total, _MAX_HISTORY_ROWS, _MAX_HISTORY_ROWS,
        )
        sanitized = sanitized[:_MAX_HISTORY_ROWS]
        sanitized.append({
            "__truncated__": True,
            "__total_rows_available__": total,
            "__note__": (
                f"Results capped at {_MAX_HISTORY_ROWS} rows. "
                "Use start_date/end_date to narrow the range."
            ),
        })
    return json.dumps(sanitized, default=str)


def _no_data(fund_id: str, data_product: str) -> str:
    """AI-14: Return a structured sentinel when no records are found."""
    return json.dumps({
        "status": "no_data",
        "fund_id": fund_id,
        "data_product": data_product,
        "message": "No records found for the requested fund and period.",
    })


def _filter_by_date(
    rows: list[dict[str, Any]],
    date_field: str,
    start: str | None,
    end: str | None,
) -> list[dict[str, Any]]:
    out = rows
    if start:
        out = [r for r in out if r[date_field] >= start]
    if end:
        out = [r for r in out if r[date_field] <= end]
    return out


# ---------------------------------------------------------------------------
# Fund discovery
# ---------------------------------------------------------------------------
@beta_tool
def list_available_funds() -> list[str]:
    """Return all fund_id values present in the database.

    Call this whenever the user has not specified a fund, or to enumerate
    funds for a comparative analysis.  The returned fund_ids are the valid
    values to pass to every other tool.
    """
    return _to_json(da.list_funds())


# ---------------------------------------------------------------------------
# DP-01 Static profile
# ---------------------------------------------------------------------------
@beta_tool
def get_fund_static_profile(fund_id: str) -> dict[str, Any]:
    """Return the fund's immutable reference data (DP-01 Fund Static Profile).

    Use for: fund name, manager, vintage year, closing date, reinvestment
    period end, non-call period end, legal final maturity, target par,
    base currency, management fee rate, incentive hurdle. Anchor data that
    contextualises every other answer.

    Args:
        fund_id: Fund identifier — call list_available_funds to enumerate valid values.
    """
    result = da.static_profile(fund_id)
    if not result:
        return _no_data(fund_id, "DP-01")
    return _to_json(result)


# ---------------------------------------------------------------------------
# DP-03 Performance
# ---------------------------------------------------------------------------
@beta_tool
def get_latest_performance(fund_id: str) -> dict[str, Any]:
    """Return the most recent performance snapshot (DP-03).

    Includes total fund NAV, equity NAV, gross/net IRR, DPI, RVPI, TVPI,
    inception-to-date P&L, current period P&L, realised/unrealised G&L,
    interest income, benchmark return and excess return for the latest
    reporting date.

    Args:
        fund_id: Fund identifier — call list_available_funds to enumerate valid values.
    """
    rows = da.performance(fund_id)
    if not rows:
        return _no_data(fund_id, "DP-03")
    return _to_json(rows[-1])


@beta_tool
def get_performance_history(
    fund_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Return the full performance history, optionally filtered by date range (DP-03).

    Args:
        fund_id:    Fund identifier — call list_available_funds to enumerate valid values.
        start_date: ISO date (YYYY-MM-DD) inclusive lower bound. Optional.
        end_date:   ISO date (YYYY-MM-DD) inclusive upper bound. Optional.
    """
    rows = _filter_by_date(da.performance(fund_id), "Reporting Date", start_date, end_date)
    if not rows:
        return _no_data(fund_id, "DP-03")
    return _to_json(rows)


@beta_tool
def compute_period_return(
    fund_id: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Compute simple % change in total NAV and equity NAV between two reporting dates.

    Args:
        fund_id:    Fund identifier — call list_available_funds to enumerate valid values.
        start_date: ISO date present in DP-03 history (YYYY-MM-DD).
        end_date:   ISO date present in DP-03 history (YYYY-MM-DD), > start_date.
    """
    rows = {r["Reporting Date"]: r for r in da.performance(fund_id)}
    if start_date not in rows or end_date not in rows:
        return _to_json({
            "error": "date not found in performance history",
            "available_dates": list(rows.keys()),
        })
    start_row, end_row = rows[start_date], rows[end_date]
    nav_s = float(start_row["Total Fund NAV (USD)"])
    nav_e = float(end_row["Total Fund NAV (USD)"])
    eq_s  = float(start_row["Equity NAV (USD)"])
    eq_e  = float(end_row["Equity NAV (USD)"])
    if nav_s == 0 or eq_s == 0:
        return _to_json({"error": "Starting NAV is zero — cannot compute period return."})
    return _to_json({
        "fund_id": fund_id,
        "start_date": start_date,
        "end_date": end_date,
        "total_nav_start": nav_s,
        "total_nav_end": nav_e,
        "total_nav_change_pct": round((nav_e - nav_s) / nav_s * 100, 4),
        "equity_nav_start": eq_s,
        "equity_nav_end": eq_e,
        "equity_nav_change_pct": round((eq_e - eq_s) / eq_s * 100, 4),
    })


# ---------------------------------------------------------------------------
# DP-04 Compliance
# ---------------------------------------------------------------------------
@beta_tool
def get_compliance_status(fund_id: str) -> list[dict[str, Any]]:
    """Return the current status of every covenant test (DP-04 Compliance Dashboard).

    Each row: test ID, name, type (OC/IC/Quality/Concentration), tranche class,
    current value, threshold, cushion, PASS/FAIL, breach consequence, last tested.
    Failing tests divert cash from equity — check this whenever asked about fund
    health or whether equity is currently receiving distributions.

    Args:
        fund_id: Fund identifier — call list_available_funds to enumerate valid values.
    """
    rows = da.compliance(fund_id)
    if not rows:
        return _no_data(fund_id, "DP-04")
    return _to_json(rows)


# ---------------------------------------------------------------------------
# DP-05 Cashflows
# ---------------------------------------------------------------------------
@beta_tool
def get_cashflow_history(fund_id: str) -> list[dict[str, Any]]:
    """Return all waterfall cashflow rows across recent payment dates (DP-05).

    Each row is one waterfall step on one payment date — payment date,
    collection period, total interest/principal proceeds, waterfall step,
    recipient, amount disbursed, OC diversion amount, equity distribution,
    fees paid (management/incentive/trustee).

    Args:
        fund_id: Fund identifier — call list_available_funds to enumerate valid values.
    """
    rows = da.cashflows(fund_id)
    if not rows:
        return _no_data(fund_id, "DP-05")
    return _to_json(rows)


@beta_tool
def get_latest_equity_distribution(fund_id: str) -> dict[str, Any]:
    """Return the most recent equity distribution row from the waterfall (DP-05).

    Scans cashflows for the latest 'Equity Distribution' waterfall step.
    Use for 'how much did equity receive last quarter' questions.

    Args:
        fund_id: Fund identifier — call list_available_funds to enumerate valid values.
    """
    rows = da.cashflows(fund_id)
    eq = [r for r in rows if _EQUITY_DISTRIBUTION_STEP in str(r.get("Waterfall Step", ""))]
    if not eq:
        return _no_data(fund_id, "DP-05")
    return _to_json(eq[-1])


# ---------------------------------------------------------------------------
# DP-06 Fees
# ---------------------------------------------------------------------------
@beta_tool
def get_fee_summary(fund_id: str) -> list[dict[str, Any]]:
    """Return the fund's fee & expense ledger for the current period (DP-06).

    Each row: period, fee type (Management/Incentive/Trustee/Admin/Legal/
    Rating Agency/Tax/TER), rate or amount, accrued YTD, accrued and paid
    in current period, cumulative paid, hurdle and catch-up rates, tax
    provision, effective tax rate, total expense ratio.

    Args:
        fund_id: Fund identifier — call list_available_funds to enumerate valid values.
    """
    rows = da.fees(fund_id)
    if not rows:
        return _no_data(fund_id, "DP-06")
    return _to_json(rows)


# ---------------------------------------------------------------------------
# DP-07 Key Metrics
# ---------------------------------------------------------------------------
@beta_tool
def get_latest_key_metrics(fund_id: str) -> dict[str, Any]:
    """Return the most recent portfolio quality snapshot (DP-07 Key Metrics Tracker).

    Includes WAS (bps over SOFR), WARF, WAL, WAC, weighted average recovery
    rate, par build/loss vs target, % floating, % PIK, % CCC/Caa,
    % covenant-lite, diversity score, number of obligors and industries,
    largest obligor and industry %, top-10 obligor concentration.

    Args:
        fund_id: Fund identifier — call list_available_funds to enumerate valid values.
    """
    rows = da.key_metrics(fund_id)
    if not rows:
        return _no_data(fund_id, "DP-07")
    return _to_json(rows[-1])


@beta_tool
def get_key_metrics_history(
    fund_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Return portfolio-quality history filtered by date range (DP-07).

    Use for trend questions on WARF, WAS, diversity, concentrations.

    Args:
        fund_id:    Fund identifier — call list_available_funds to enumerate valid values.
        start_date: ISO date (YYYY-MM-DD) inclusive lower bound. Optional.
        end_date:   ISO date (YYYY-MM-DD) inclusive upper bound. Optional.
    """
    rows = _filter_by_date(da.key_metrics(fund_id), "Reporting Date", start_date, end_date)
    if not rows:
        return _no_data(fund_id, "DP-07")
    return _to_json(rows)


# ---------------------------------------------------------------------------
# DP-08 Liability structure
# ---------------------------------------------------------------------------
@beta_tool
def get_liability_structure(fund_id: str) -> list[dict[str, Any]]:
    """Return the fund's tranche stack (DP-08 Fund Liability Structure).

    One row per debt class plus Sub Notes and Equity: class designation,
    CUSIP, initial and current notional, coupon type and rate, payment frequency,
    ratings (Moody's/S&P/Fitch), subordination level, OC and IC cushion per
    class, waterfall priority, cumulative principal repaid, interest paid in
    current period, accrued interest, rating outlook.

    Args:
        fund_id: Fund identifier — call list_available_funds to enumerate valid values.
    """
    rows = da.liability_structure(fund_id)
    if not rows:
        return _no_data(fund_id, "DP-08")
    return _to_json(rows)


# ---------------------------------------------------------------------------
# DP-02 Portfolio Snapshot & Loan-Level Analysis
# ---------------------------------------------------------------------------
@beta_tool
def get_portfolio_loans(fund_id: str) -> list[dict[str, Any]]:
    """Return all current loan positions in the portfolio (DP-02 Portfolio Snapshot).

    Each row is one loan: Position ID, Obligor Name, Industry (Moody's), Country,
    Loan Type, Par Amount (USD), Market Value (USD), Price (% par),
    Spread (SOFR+ bps), Maturity Date, Moody's/S&P/Fitch ratings,
    PIK/LBO/Covenant-Lite flags, Days Past Due.

    Use this tool to inspect individual loan positions, filter by rating or
    industry, or supply loan data to the simulation and attribution tools.

    Args:
        fund_id: Fund identifier — call list_available_funds to enumerate valid values.
    """
    rows = da.portfolio(fund_id)
    if not rows:
        return _no_data(fund_id, "DP-02")
    return _to_json(rows)


@beta_tool
def simulate_loan_replacement(
    fund_id: str,
    remove_position_id: str,
    new_loan_par_usd: float,
    new_loan_spread_bps: int,
    new_loan_moodys_rating: str,
    new_loan_maturity_date: str,
) -> dict[str, Any]:
    """Compute the impact on WARF, WAS, and WAL of replacing one loan with a new one.

    Fetches the current DP-02 portfolio, removes the specified position, adds a
    synthetic new loan with the provided parameters, then recomputes WARF, WAS
    and WAL using par-weighted averages.  Returns current metrics, simulated
    metrics, and absolute deltas for all three indicators.

    Args:
        fund_id: Fund identifier — call list_available_funds to enumerate valid values.
        remove_position_id: Position ID of the loan to remove (e.g. "P0001"). Must match
            a position in the current portfolio — call get_portfolio_loans first if unsure.
        new_loan_par_usd: Par amount of the replacement loan in USD (e.g. 12000000.0).
            Must be > 0 and <= 500,000,000.
        new_loan_spread_bps: Spread over SOFR in basis points (e.g. 350). Must be 0–2000.
        new_loan_moodys_rating: Moody's rating of the replacement loan (e.g. "B1", "Ba2").
            Must be a standard Moody's rating symbol present in the WARF factor table.
        new_loan_maturity_date: Maturity date of the replacement loan (YYYY-MM-DD).
            Must be a future date.
    """
    if new_loan_par_usd <= 0 or new_loan_par_usd > 500_000_000:
        return _to_json({"error": "new_loan_par_usd must be > 0 and <= 500,000,000."})
    if not (0 <= new_loan_spread_bps <= 2000):
        return _to_json({"error": "new_loan_spread_bps must be between 0 and 2000."})
    if new_loan_moodys_rating not in clo_analytics.MOODYS_RATING_FACTORS:
        return _to_json({
            "error": f"Invalid Moody's rating {new_loan_moodys_rating!r}.",
            "valid_ratings": sorted(clo_analytics.MOODYS_RATING_FACTORS),
        })
    try:
        maturity = date.fromisoformat(new_loan_maturity_date)
    except ValueError:
        return _to_json({"error": f"Invalid date {new_loan_maturity_date!r}. Use YYYY-MM-DD."})
    if maturity <= date.today():
        return _to_json({"error": "new_loan_maturity_date must be a future date."})

    loans = da.portfolio(fund_id)
    if not loans:
        return _no_data(fund_id, "DP-02")

    valid_ids = {loan["Position ID"] for loan in loans}
    if remove_position_id not in valid_ids:
        return _to_json({
            "error": f"Position {remove_position_id!r} not found in {fund_id!r} portfolio.",
            "valid_position_ids": sorted(valid_ids),
        })

    new_loan: dict[str, Any] = {
        "Position ID": "NEW",
        "Obligor Name": "(replacement loan)",
        "Industry (Moody's)": "Unknown",
        "Par Amount (USD)": new_loan_par_usd,
        "Market Value (USD)": new_loan_par_usd,
        "Price (% par)": 100.0,
        "Spread (SOFR+ bps)": new_loan_spread_bps,
        "Maturity Date": new_loan_maturity_date,
        "Moody's Rating": new_loan_moodys_rating,
    }
    try:
        result = clo_analytics.simulate_replacement(
            loans, remove_position_id, new_loan, date.today().isoformat()
        )
    except ValueError as exc:
        return _to_json({"error": str(exc)})
    return _to_json(result)


@beta_tool
def get_asset_return_contribution(fund_id: str) -> list[dict[str, Any]]:
    """Return per-loan return contribution metrics for the current portfolio (DP-02).

    For each loan computes: par weight (% of total par), mark-to-market P&L
    (market value minus par), MTM contribution to total par (%), spread
    contribution to WAS (bps), and annualised spread income estimate (USD).
    Results are sorted by MTM P&L descending — best performers first.

    Use to answer questions like: which loans drive portfolio returns, which
    positions have the largest unrealised gains/losses, which loans contribute
    most to spread income.

    Note: annualised_spread_income_est_usd uses spread × par only; SOFR base
    rate is not stored in DP-02 and is excluded from this estimate.

    Args:
        fund_id: Fund identifier — call list_available_funds to enumerate valid values.
    """
    loans = da.portfolio(fund_id)
    if not loans:
        return _no_data(fund_id, "DP-02")
    result = clo_analytics.compute_asset_contributions(loans)
    return _to_json(result)


@beta_tool
def optimize_portfolio_returns(fund_id: str) -> dict[str, Any]:
    """Run the portfolio return optimizer for a fund (up to 150 greedy iterations).

    Simulates all pairwise sell/buy trades within the current portfolio, accepting
    only trades that (a) improve equity spread yield AND (b) keep every compliance
    test passing.  The optimizer applies the best qualifying trade at each step
    and repeats until no improvement is possible or 150 iterations are reached.

    All trades are restricted to assets already present in the initial portfolio
    — no external hypothetical positions are introduced.

    Returns a scenario table with every accepted trade, the yield impact of each,
    recomputed compliance values, the final recommended portfolio configuration,
    and the reasoning behind the recommendation.

    Args:
        fund_id: Fund identifier — call list_available_funds to enumerate valid values.
    """
    from portfolio_optimizer.optimizer import run_optimization

    result = run_optimization(fund_id)

    accepted = [
        {
            "iteration": s.iteration,
            "sell_position_id": s.trade.sell_position_id,
            "sell_obligor_name": s.sell_obligor_name,
            "sell_fraction_pct": int(s.trade.sell_fraction * 100),
            "buy_position_id": s.trade.buy_position_id,
            "buy_obligor_name": s.buy_obligor_name,
            "equity_yield_before_pct": s.equity_yield_before_pct,
            "equity_yield_after_pct": s.equity_yield_after_pct,
            "equity_yield_delta_pp": s.equity_yield_delta_pp,
            "all_compliance_pass": s.all_compliance_pass,
            "compliance_detail": [
                {
                    "test_id": c.test_id,
                    "test_name": c.test_name,
                    "test_type": c.test_type,
                    "baseline_value": c.baseline_value,
                    "new_value": c.new_value,
                    "threshold": c.threshold,
                    "new_cushion": c.new_cushion,
                    "pass_fail": c.pass_fail,
                }
                for c in s.compliance_results
            ],
        }
        for s in result.accepted_scenarios
    ]

    final_portfolio = [
        {
            "position_id": loan["Position ID"],
            "obligor_name": loan.get("Obligor Name", ""),
            "industry": loan.get("Industry (Moody's)", ""),
            "moodys_rating": loan.get("Moody's Rating", ""),
            "par_amount_usd": float(loan["Par Amount (USD)"]),
            "market_value_usd": float(loan["Market Value (USD)"]),
            "spread_sofr_bps": int(float(loan["Spread (SOFR+ bps)"])),
            "maturity_date": str(loan.get("Maturity Date", "")),
        }
        for loan in result.final_portfolio
    ]

    output = {
        "fund_id": result.fund_id,
        "baseline_equity_yield_pct": result.baseline_equity_yield_pct,
        "final_equity_yield_pct": result.final_equity_yield_pct,
        "total_yield_improvement_pp": result.total_yield_improvement_pp,
        "iterations_run": result.iterations_run,
        "converged": result.converged,
        "evaluated_per_iteration": result.evaluated_per_iteration,
        "recommendation_reason": result.recommendation_reason,
        "accepted_trades": accepted,
        "final_portfolio": final_portfolio,
        "note": (
            "Equity yield is a spread-over-SOFR proxy (SOFR base rate excluded from both "
            "sides). Absolute values are not the fund net IRR; yield deltas between "
            "scenarios are accurate and directly comparable."
        ),
    }
    return _to_json(output)


ALL_TOOLS = [
    list_available_funds,
    get_fund_static_profile,
    get_latest_performance,
    get_performance_history,
    compute_period_return,
    get_compliance_status,
    get_cashflow_history,
    get_latest_equity_distribution,
    get_fee_summary,
    get_latest_key_metrics,
    get_key_metrics_history,
    get_liability_structure,
    get_portfolio_loans,
    simulate_loan_replacement,
    get_asset_return_contribution,
    optimize_portfolio_returns,
]

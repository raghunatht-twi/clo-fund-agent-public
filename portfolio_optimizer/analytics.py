"""Pure-computation utilities for the portfolio return optimizer.

All functions are stateless and operate on the same dict shapes produced by
clo_db_agent.data_access. No I/O, no LLM calls — every function is unit-testable
in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import clo_analytics

_CCC_RATINGS: frozenset[str] = frozenset({"Caa1", "Caa2", "Caa3", "Ca", "C"})
_UPPER_BOUND_KEYWORDS: tuple[str, ...] = (
    "warf", "ccc", "caa", "wal", "concentration", "largest", "top 10", "top-10", "fixed",
    "pik", "dip",
)


@dataclass(frozen=True)
class Trade:
    sell_position_id: str
    sell_fraction: float       # proportion of par to sell: (0, 1]
    buy_position_id: str       # must differ from sell_position_id


@dataclass
class ComplianceResult:
    test_id: str
    test_name: str
    test_type: str
    baseline_value: float
    new_value: float
    threshold: float
    new_cushion: float
    pass_fail: str


@dataclass
class ScenarioRecord:
    iteration: int
    trade: Trade
    sell_obligor_name: str
    buy_obligor_name: str
    equity_yield_before_pct: float
    equity_yield_after_pct: float
    equity_yield_delta_pp: float
    compliance_results: list[ComplianceResult]
    all_compliance_pass: bool
    accepted: bool
    rejection_reason: str


# ---------------------------------------------------------------------------
# Portfolio helpers
# ---------------------------------------------------------------------------

def _find_loan(loans: list[dict[str, Any]], position_id: str) -> dict[str, Any] | None:
    return next((loan for loan in loans if loan["Position ID"] == position_id), None)


def _total_par(loans: list[dict[str, Any]]) -> float:
    return sum(float(loan["Par Amount (USD)"]) for loan in loans)


def _spread_income(loans: list[dict[str, Any]]) -> float:
    return sum(
        float(loan["Par Amount (USD)"]) * float(loan["Spread (SOFR+ bps)"]) / 10_000
        for loan in loans
    )


def _group_par(loans: list[dict[str, Any]], key: str) -> dict[str, float]:
    buckets: dict[str, float] = {}
    for loan in loans:
        name = str(loan.get(key, "Unknown"))
        buckets[name] = buckets.get(name, 0.0) + float(loan["Par Amount (USD)"])
    return buckets


def _max_par_by_obligor(loans: list[dict[str, Any]]) -> float:
    buckets = _group_par(loans, "Obligor Name")
    return max(buckets.values(), default=0.0)


def _max_par_by_industry(loans: list[dict[str, Any]]) -> float:
    buckets = _group_par(loans, "Industry (Moody's)")
    return max(buckets.values(), default=0.0)


def _top10_par_by_obligor(loans: list[dict[str, Any]]) -> float:
    buckets = _group_par(loans, "Obligor Name")
    return sum(sorted(buckets.values(), reverse=True)[:10])


# ---------------------------------------------------------------------------
# Trade application
# ---------------------------------------------------------------------------

def apply_trade(
    loans: list[dict[str, Any]],
    trade: Trade,
) -> list[dict[str, Any]] | None:
    """Return the portfolio after selling sell_fraction of sell_loan and investing into buy_loan.

    Proceeds reinvested at the buy loan's current market price, so par received
    differs from par sold whenever prices differ from 100%.
    Returns None if either position is not found or the trade is self-referential.
    """
    if trade.sell_position_id == trade.buy_position_id:
        return None
    sell_loan = _find_loan(loans, trade.sell_position_id)
    buy_loan = _find_loan(loans, trade.buy_position_id)
    if sell_loan is None or buy_loan is None:
        return None

    sell_price = float(sell_loan.get("Price (% par)") or 100.0)
    buy_price = float(buy_loan.get("Price (% par)") or 100.0)
    if buy_price <= 0:
        return None

    sell_par = float(sell_loan["Par Amount (USD)"]) * trade.sell_fraction
    proceeds = sell_par * sell_price / 100.0
    additional_par = proceeds * 100.0 / buy_price

    result: list[dict[str, Any]] = []
    for loan in loans:
        pid = loan["Position ID"]
        if pid == trade.sell_position_id:
            remaining = float(loan["Par Amount (USD)"]) * (1.0 - trade.sell_fraction)
            if remaining < 1.0:
                continue  # fully sold — drop position
            updated = dict(loan)
            updated["Par Amount (USD)"] = remaining
            updated["Market Value (USD)"] = remaining * sell_price / 100.0
            result.append(updated)
        elif pid == trade.buy_position_id:
            new_par = float(loan["Par Amount (USD)"]) + additional_par
            updated = dict(loan)
            updated["Par Amount (USD)"] = new_par
            updated["Market Value (USD)"] = new_par * buy_price / 100.0
            result.append(updated)
        else:
            result.append(loan)
    return result


# ---------------------------------------------------------------------------
# Equity yield
# ---------------------------------------------------------------------------

def compute_equity_yield(
    loans: list[dict[str, Any]],
    liability_rows: list[dict[str, Any]],
    equity_nav_usd: float,
) -> float:
    """Return annualized equity spread yield as % of equity NAV.

    Equity spread yield = (portfolio spread income − floating debt spread cost) / equity NAV.
    SOFR base rate cancels out in delta computations, so the absolute value is a
    spread-only proxy. Deltas between scenarios are accurate.
    """
    if equity_nav_usd <= 0:
        return 0.0
    debt_cost = sum(
        float(row.get("Current Notional (USD)") or 0)
        * float(row.get("Coupon Rate (SOFR+ bps)") or 0)
        / 10_000
        for row in liability_rows
        if str(row.get("Coupon Type", "")).lower() == "floating"
    )
    return (_spread_income(loans) - debt_cost) / equity_nav_usd * 100.0


# ---------------------------------------------------------------------------
# Compliance test value recomputation — per-type handlers
# ---------------------------------------------------------------------------

def _is_upper_bound(test_name: str, test_type: str) -> bool:
    """Return True when the test passes only if current_value ≤ threshold."""
    if test_type in ("OC", "IC"):
        return False
    return any(kw in test_name.lower() for kw in _UPPER_BOUND_KEYWORDS)


def _recompute_oc(
    current_value: float,
    baseline_loans: list[dict[str, Any]],
    new_loans: list[dict[str, Any]],
    _ref: str,
) -> float:
    old_par = _total_par(baseline_loans)
    return current_value * (_total_par(new_loans) / old_par) if old_par > 0 else current_value


def _recompute_ic(
    current_value: float,
    baseline_loans: list[dict[str, Any]],
    new_loans: list[dict[str, Any]],
    _ref: str,
    interest_income_usd: float = 0.0,
) -> float:
    if current_value <= 0 or interest_income_usd <= 0:
        return current_value
    implied_expense = interest_income_usd / current_value
    delta_income = _spread_income(new_loans) - _spread_income(baseline_loans)
    return (interest_income_usd + delta_income) / implied_expense


def _scale_ccc(
    current_value: float,
    baseline_loans: list[dict[str, Any]],
    new_loans: list[dict[str, Any]],
    _ref: str,
) -> float:
    baseline_ccc = sum(
        float(loan["Par Amount (USD)"])
        for loan in baseline_loans
        if str(loan.get("Moody's Rating", "NR")) in _CCC_RATINGS
    )
    new_ccc = sum(
        float(loan["Par Amount (USD)"])
        for loan in new_loans
        if str(loan.get("Moody's Rating", "NR")) in _CCC_RATINGS
    )
    if baseline_ccc == 0:
        # No CCC loans at baseline — use portfolio par as proxy denominator so a
        # trade that buys a CCC loan produces a nonzero (not silently-passing) value.
        new_par = _total_par(new_loans)
        return new_ccc / new_par if new_par > 0 else 0.0
    return current_value * (new_ccc / baseline_ccc)


def _scale_max_obligor(
    current_value: float,
    baseline_loans: list[dict[str, Any]],
    new_loans: list[dict[str, Any]],
    _ref: str,
) -> float:
    baseline_max = _max_par_by_obligor(baseline_loans)
    if baseline_max == 0:
        return current_value
    return current_value * (_max_par_by_obligor(new_loans) / baseline_max)


def _scale_max_industry(
    current_value: float,
    baseline_loans: list[dict[str, Any]],
    new_loans: list[dict[str, Any]],
    _ref: str,
) -> float:
    baseline_max = _max_par_by_industry(baseline_loans)
    if baseline_max == 0:
        return current_value
    return current_value * (_max_par_by_industry(new_loans) / baseline_max)


def _scale_top10(
    current_value: float,
    baseline_loans: list[dict[str, Any]],
    new_loans: list[dict[str, Any]],
    _ref: str,
) -> float:
    baseline_top10 = _top10_par_by_obligor(baseline_loans)
    if baseline_top10 == 0:
        return current_value
    return current_value * (_top10_par_by_obligor(new_loans) / baseline_top10)


def _metrics_key(key: str) -> Callable[..., float]:
    return lambda cv, bl, nl, ref: float(
        clo_analytics.compute_portfolio_metrics(nl, ref)[key]
    )


# Ordered dispatch: first matching keyword wins.
# Handler signature: (current_value, baseline_loans, new_loans, ref_date) -> float
_QUALITY_HANDLERS: list[tuple[str, Callable[..., float]]] = [
    ("warf",     _metrics_key("warf")),
    ("was",      _metrics_key("was_bps")),
    ("wal",      _metrics_key("wal_years")),
    ("maturity", _metrics_key("wal_years")),
    ("ccc",      _scale_ccc),
    ("caa",      _scale_ccc),
    ("top 10",   _scale_top10),
    ("top-10",   _scale_top10),
    ("obligor",  _scale_max_obligor),
    ("issuer",   _scale_max_obligor),
    ("industry", _scale_max_industry),
]


def _recompute_test_value(
    test: dict[str, Any],
    baseline_loans: list[dict[str, Any]],
    new_loans: list[dict[str, Any]],
    interest_income_usd: float,
    ref_date: str,
) -> float:
    test_type = str(test.get("Test Type", ""))
    current_value = float(test["Current Value"])

    if test_type == "OC":
        return _recompute_oc(current_value, baseline_loans, new_loans, ref_date)
    if test_type == "IC":
        return _recompute_ic(
            current_value, baseline_loans, new_loans, ref_date, interest_income_usd
        )

    name = str(test.get("Test Name", "")).lower()
    for keyword, handler in _QUALITY_HANDLERS:
        if keyword in name:
            return handler(current_value, baseline_loans, new_loans, ref_date)
    return current_value


def _recompute_compliance(
    baseline_loans: list[dict[str, Any]],
    new_loans: list[dict[str, Any]],
    compliance_tests: list[dict[str, Any]],
    interest_income_usd: float,
    ref_date: str,
) -> tuple[list[ComplianceResult], bool]:
    results: list[ComplianceResult] = []
    all_pass = True
    for test in compliance_tests:
        new_val = _recompute_test_value(
            test, baseline_loans, new_loans, interest_income_usd, ref_date
        )
        threshold = float(test["Threshold"])
        upper = _is_upper_bound(str(test.get("Test Name", "")), str(test.get("Test Type", "")))
        passes = new_val <= threshold if upper else new_val >= threshold
        cushion = (threshold - new_val) if upper else (new_val - threshold)
        if not passes:
            all_pass = False
        results.append(ComplianceResult(
            test_id=str(test.get("Test ID", "")),
            test_name=str(test.get("Test Name", "")),
            test_type=str(test.get("Test Type", "")),
            baseline_value=float(test["Current Value"]),
            new_value=round(new_val, 6),
            threshold=threshold,
            new_cushion=round(cushion, 6),
            pass_fail="PASS" if passes else "FAIL",
        ))
    return results, all_pass


def evaluate_trade(
    trade: Trade,
    baseline_loans: list[dict[str, Any]],
    compliance_tests: list[dict[str, Any]],
    liability_rows: list[dict[str, Any]],
    equity_nav_usd: float,
    interest_income_usd: float,
    iteration: int,
    baseline_yield: float,
    ref_date: str,
) -> ScenarioRecord:
    """Evaluate one trade candidate and return a fully-populated ScenarioRecord."""
    sell_loan = _find_loan(baseline_loans, trade.sell_position_id) or {}
    buy_loan = _find_loan(baseline_loans, trade.buy_position_id) or {}
    sell_name = str(sell_loan.get("Obligor Name", trade.sell_position_id))
    buy_name = str(buy_loan.get("Obligor Name", trade.buy_position_id))

    new_loans = apply_trade(baseline_loans, trade)
    if new_loans is None:
        return ScenarioRecord(
            iteration=iteration, trade=trade,
            sell_obligor_name=sell_name, buy_obligor_name=buy_name,
            equity_yield_before_pct=baseline_yield, equity_yield_after_pct=baseline_yield,
            equity_yield_delta_pp=0.0, compliance_results=[], all_compliance_pass=False,
            accepted=False, rejection_reason="invalid trade",
        )

    new_yield = compute_equity_yield(new_loans, liability_rows, equity_nav_usd)
    delta = new_yield - baseline_yield
    compliance_results, all_pass = _recompute_compliance(
        baseline_loans, new_loans, compliance_tests, interest_income_usd, ref_date
    )

    accepted = delta > 0 and all_pass
    if not accepted:
        if delta <= 0:
            rejection_reason = f"equity yield delta {delta:+.4f}pp ≤ 0"
        else:
            failed = [r.test_name for r in compliance_results if r.pass_fail == "FAIL"]
            rejection_reason = f"compliance breach: {', '.join(failed)}"
    else:
        rejection_reason = ""

    return ScenarioRecord(
        iteration=iteration, trade=trade,
        sell_obligor_name=sell_name, buy_obligor_name=buy_name,
        equity_yield_before_pct=round(baseline_yield, 4),
        equity_yield_after_pct=round(new_yield, 4),
        equity_yield_delta_pp=round(delta, 4),
        compliance_results=compliance_results,
        all_compliance_pass=all_pass,
        accepted=accepted,
        rejection_reason=rejection_reason,
    )

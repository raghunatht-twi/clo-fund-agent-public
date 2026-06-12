"""Greedy hill-climbing portfolio return optimizer for CLO funds.

Algorithm per iteration:
  1. Enumerate all (sell_position, buy_position, sell_fraction) combinations
     where sell_fraction ∈ {0.25, 0.50, 1.00} and sell.spread < buy.spread
     (pre-filter: selling a lower-spread asset into a higher-spread one is the
     only direction that can improve equity yield).
  2. Evaluate each candidate via analytics.evaluate_trade.
  3. Keep only candidates that improve equity yield AND pass every compliance test.
  4. Apply the best candidate permanently; record it in session memory.
  5. Repeat until no candidate passes both criteria OR max_iterations is hit.

Session memory: _SESSION stores the most recent OptimizationResult per fund_id
so the LLM can retrieve it without re-running if the user asks a follow-up.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from clo_db_agent import data_access as da

from .analytics import (
    ScenarioRecord,
    Trade,
    apply_trade,
    compute_equity_yield,
    evaluate_trade,
)

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 150
_SELL_FRACTIONS: list[float] = [0.25, 0.50, 1.00]

_SESSION: dict[str, "OptimizationResult"] = {}


@dataclass
class OptimizationResult:
    fund_id: str
    baseline_equity_yield_pct: float
    final_equity_yield_pct: float
    total_yield_improvement_pp: float
    iterations_run: int
    converged: bool
    accepted_scenarios: list[ScenarioRecord]
    final_portfolio: list[dict[str, Any]]
    recommendation_reason: str
    evaluated_per_iteration: list[int] = field(default_factory=list)


def run_optimization(
    fund_id: str,
    max_iterations: int = MAX_ITERATIONS,
) -> OptimizationResult:
    """Run the optimizer and persist the result in session memory."""
    result = _run(fund_id, max_iterations)
    _SESSION[fund_id] = result
    return result


def get_session_result(fund_id: str) -> OptimizationResult | None:
    """Return the most recent optimization result for fund_id without re-running."""
    return _SESSION.get(fund_id)


def _run(fund_id: str, max_iterations: int) -> OptimizationResult:
    loans = da.portfolio(fund_id)
    compliance_tests = da.compliance(fund_id)
    liability_rows = da.liability_structure(fund_id)
    perf_rows = da.performance(fund_id)

    if not loans or not compliance_tests or not perf_rows:
        return OptimizationResult(
            fund_id=fund_id,
            baseline_equity_yield_pct=0.0,
            final_equity_yield_pct=0.0,
            total_yield_improvement_pp=0.0,
            iterations_run=0,
            converged=False,
            accepted_scenarios=[],
            final_portfolio=loans,
            recommendation_reason=(
                "Insufficient data — portfolio, compliance, or performance records missing."
            ),
        )

    latest_perf = perf_rows[-1]
    equity_nav = float(latest_perf.get("Equity NAV (USD)") or 1.0)
    interest_income = float(latest_perf.get("Total Interest Income (USD)") or 0.0)

    ref_date = date.today().isoformat()
    current_loans: list[dict[str, Any]] = [dict(loan) for loan in loans]
    baseline_yield = compute_equity_yield(current_loans, liability_rows, equity_nav)
    current_yield = baseline_yield

    accepted_scenarios: list[ScenarioRecord] = []
    evaluated_per_iteration: list[int] = []
    converged = False

    for iteration in range(1, max_iterations + 1):
        spread_map = {
            loan["Position ID"]: int(float(loan["Spread (SOFR+ bps)"]))
            for loan in current_loans
        }
        position_ids = list(spread_map.keys())

        candidates: list[ScenarioRecord] = []
        evaluated = 0
        for sell_id in position_ids:
            for buy_id in position_ids:
                if sell_id == buy_id:
                    continue
                # Pre-filter: only trades that move par into a higher-spread asset can
                # improve spread income and therefore equity yield.
                if spread_map[buy_id] <= spread_map[sell_id]:
                    continue
                for fraction in _SELL_FRACTIONS:
                    scenario = evaluate_trade(
                        trade=Trade(sell_id, fraction, buy_id),
                        baseline_loans=current_loans,
                        compliance_tests=compliance_tests,
                        liability_rows=liability_rows,
                        equity_nav_usd=equity_nav,
                        interest_income_usd=interest_income,
                        iteration=iteration,
                        baseline_yield=current_yield,
                        ref_date=ref_date,
                    )
                    evaluated += 1
                    if scenario.accepted:
                        candidates.append(scenario)

        evaluated_per_iteration.append(evaluated)

        if not candidates:
            logger.info("Optimizer converged at iteration %d.", iteration)
            converged = True
            break

        best = max(candidates, key=lambda s: s.equity_yield_delta_pp)
        accepted_scenarios.append(best)
        new_loans = apply_trade(current_loans, best.trade)
        if new_loans is None:
            converged = False
            break
        current_loans = new_loans
        current_yield = best.equity_yield_after_pct
        logger.info(
            "Iteration %d: sell %s → buy %s (%.0f%%), yield %+.4fpp → %.4f%%",
            iteration,
            best.trade.sell_position_id,
            best.trade.buy_position_id,
            best.trade.sell_fraction * 100,
            best.equity_yield_delta_pp,
            current_yield,
        )
    else:
        converged = False

    recommendation_reason = _build_reason(
        accepted_scenarios, baseline_yield, current_yield, max_iterations, converged
    )

    return OptimizationResult(
        fund_id=fund_id,
        baseline_equity_yield_pct=round(baseline_yield, 4),
        final_equity_yield_pct=round(current_yield, 4),
        total_yield_improvement_pp=round(current_yield - baseline_yield, 4),
        iterations_run=len(accepted_scenarios),
        converged=converged,
        accepted_scenarios=accepted_scenarios,
        final_portfolio=current_loans,
        recommendation_reason=recommendation_reason,
        evaluated_per_iteration=evaluated_per_iteration,
    )


def _build_reason(
    accepted: list[ScenarioRecord],
    baseline: float,
    final: float,
    max_iter: int,
    converged: bool,
) -> str:
    if not accepted:
        return (
            "No trades found that simultaneously improve equity spread yield and keep all "
            "compliance tests passing. The current portfolio is already at or near the "
            "constrained optimum."
        )
    delta = final - baseline
    stop_reason = (
        "no further improvement was possible without breaching compliance tests."
        if converged
        else f"the maximum of {max_iter} iterations was reached."
    )
    trade_lines = [
        f"({i}) Sell {int(s.trade.sell_fraction * 100)}% of "
        f"{s.sell_obligor_name} ({s.trade.sell_position_id}), "
        f"reinvest into {s.buy_obligor_name} ({s.trade.buy_position_id}): "
        f"yield {s.equity_yield_delta_pp:+.4f}pp"
        for i, s in enumerate(accepted, 1)
    ]
    return (
        f"Applied {len(accepted)} trade(s), lifting equity spread yield by "
        f"{delta:+.4f}pp (from {baseline:.4f}% to {final:.4f}%). "
        f"All compliance tests pass after each accepted trade. "
        f"Trades in order: {'; '.join(trade_lines)}. "
        f"Optimization stopped because {stop_reason}"
    )

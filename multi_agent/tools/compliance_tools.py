"""Compliance stress-testing tools extending the base clo_db_agent compliance tool.

Ontology classes served: clo:ComplianceTest, clo:OCTest, clo:ICTest
Axioms applied: clo:OCTestFormulaAxiom, clo:WaterfallPriorityAxiom
Data products: dp:DP-04, dp:DP-05
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from anthropic import beta_tool

import clo_analytics
from clo_db_agent import data_access as da

# clo:OCTestFormulaAxiom.cccAdjustment — CCC above threshold haircut to market value
_CCC_RATINGS: frozenset[str] = frozenset({"Caa1", "Caa2", "Caa3", "Ca", "C"})
_CCC_BUCKET_THRESHOLD_PCT = 7.5


def _eligible_par(loans: list[dict[str, Any]]) -> float:
    """Compute OC-eligible par applying the CCC haircut (clo:OCTestFormulaAxiom)."""
    total_par = sum(float(loan["Par Amount (USD)"]) for loan in loans)
    if total_par == 0:
        return 0.0
    ccc_loans = [loan for loan in loans if loan.get("Moody's Rating", "") in _CCC_RATINGS]
    ccc_par = sum(float(loan["Par Amount (USD)"]) for loan in ccc_loans)
    ccc_pct = ccc_par / total_par * 100
    if ccc_pct <= _CCC_BUCKET_THRESHOLD_PCT:
        return total_par
    # Excess CCC par is haircut to market value proportionally
    threshold_par = total_par * _CCC_BUCKET_THRESHOLD_PCT / 100
    excess_par = ccc_par - threshold_par
    ccc_mv = sum(float(loan["Market Value (USD)"]) for loan in ccc_loans)
    mv_ratio = ccc_mv / ccc_par if ccc_par else 1.0
    haircut = excess_par * (1.0 - mv_ratio)
    return total_par - haircut


@beta_tool
def stress_test_oc_cushion(fund_id: str, downgrade_scenarios_json: str) -> str:
    """Simulate rating downgrades and estimate OC cushion impact (clo:OCTestFormulaAxiom).

    Applies the CCC haircut: assets rated Caa1 or below that push the CCC bucket
    above 7.5% of pool par are valued at market price (not par) for OC ratio purposes,
    reducing eligible par and compressing OC cushion.

    Args:
        fund_id: Fund identifier.
        downgrade_scenarios_json: JSON array of {"position_id": "P001", "new_rating": "Caa1"}.
    """
    try:
        scenarios: list[dict[str, str]] = json.loads(downgrade_scenarios_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "downgrade_scenarios_json must be a valid JSON array."})

    loans = da.portfolio(fund_id)
    compliance_tests = da.compliance(fund_id)
    if not loans or not compliance_tests:
        return json.dumps({"status": "no_data", "fund_id": fund_id})

    downgrade_map = {s["position_id"]: s["new_rating"] for s in scenarios}
    stressed_loans = [
        {**loan, "Moody's Rating": downgrade_map.get(
            loan["Position ID"], loan.get("Moody's Rating", "NR")
        )}
        for loan in loans
    ]

    baseline_eligible = _eligible_par(loans)
    stressed_eligible = _eligible_par(stressed_loans)
    eligible_delta = stressed_eligible - baseline_eligible

    ref_date = date.today().isoformat()
    baseline_metrics = clo_analytics.compute_portfolio_metrics(loans, ref_date)
    stressed_metrics = clo_analytics.compute_portfolio_metrics(stressed_loans, ref_date)

    oc_tests = [t for t in compliance_tests if t.get("Test Type") == "OC"]
    tranche_impacts = [
        {
            "tranche_class": t["Tranche Class"],
            "current_cushion_pct": float(t.get("Cushion", 0)),
            "threshold_pct": float(t.get("Threshold", 0)),
            "eligible_par_delta_usd": eligible_delta,
            "cushion_at_risk": (
                eligible_delta < 0 and float(t.get("Cushion", 0)) < abs(eligible_delta) / 1e6
            ),
        }
        for t in oc_tests
    ]

    return json.dumps({
        "fund_id": fund_id,
        "data_product": "dp:DP-04",
        "ontology_class": "clo:OCTest",
        "ontology_rule": "clo:OCTestFormulaAxiom.cccAdjustment",
        "downgrade_scenarios": scenarios,
        "baseline_eligible_par_usd": baseline_eligible,
        "stressed_eligible_par_usd": stressed_eligible,
        "eligible_par_delta_usd": eligible_delta,
        "tranche_oc_impacts": tranche_impacts,
        "baseline_warf": baseline_metrics["warf"],
        "stressed_warf": stressed_metrics["warf"],
        "warf_delta": stressed_metrics["warf"] - baseline_metrics["warf"],
    })


@beta_tool
def compute_oc_diversion_amount(fund_id: str) -> str:
    """Compute cash diversion amounts for any currently failing OC/IC tests (dp:DP-04 + dp:DP-05).

    Per clo:WaterfallPriorityAxiom: failing tests redirect interest and principal proceeds
    to repay the most senior tranche until the test passes. Equity distributions cease.

    Args:
        fund_id: Fund identifier.
    """
    compliance_tests = da.compliance(fund_id)
    cashflows = da.cashflows(fund_id)
    if not compliance_tests:
        return json.dumps({"status": "no_data", "fund_id": fund_id})

    failing = [t for t in compliance_tests if t.get("Pass/Fail") == "FAIL"]
    if not failing:
        return json.dumps({
            "fund_id": fund_id,
            "data_product": "dp:DP-04",
            "all_tests_passing": True,
            "diversion_required": False,
            "diversion_amount_usd": 0.0,
            "equity_distribution_blocked": False,
        })

    latest_date = max((r["Payment Date"] for r in cashflows), default=None) if cashflows else None
    latest_diversions = [
        {
            "payment_date": r["Payment Date"],
            "waterfall_step": r.get("Waterfall Step", ""),
            "diversion_amount_usd": float(r.get("OC Diversion Amount (USD)") or 0),
        }
        for r in cashflows
        if r["Payment Date"] == latest_date and float(r.get("OC Diversion Amount (USD)") or 0) > 0
    ] if latest_date else []

    return json.dumps({
        "fund_id": fund_id,
        "data_product": "dp:DP-04 + dp:DP-05",
        "ontology_class": "clo:OCTest",
        "ontology_rule": "clo:WaterfallPriorityAxiom",
        "failing_test_count": len(failing),
        "failing_tests": [
            {
                "test_id": t["Test ID"],
                "test_name": t["Test Name"],
                "tranche_class": t["Tranche Class"],
                "current_value": float(t["Current Value"]),
                "threshold": float(t["Threshold"]),
                "cushion": float(t["Cushion"]),
                "breach_consequence": t.get("Breach Consequence", ""),
            }
            for t in failing
        ],
        "latest_payment_date": latest_date,
        "historical_diversions": latest_diversions,
        "equity_distribution_blocked": True,
        "waterfall_rule": (
            "clo:WaterfallPriorityAxiom: all interest and principal proceeds diverted "
            "to repay senior tranche principal until failing tests recover."
        ),
    })


COMPLIANCE_TOOLS: list = [
    stress_test_oc_cushion,
    compute_oc_diversion_amount,
]

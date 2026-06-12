"""Cashflow and waterfall analysis tools extending clo_db_agent.

Ontology classes served: clo:Waterfall, clo:EquityDistribution, clo:TrancheDistribution
Axioms applied: clo:WaterfallPriorityAxiom
Data products: dp:DP-05
"""
from __future__ import annotations

import json

from anthropic import beta_tool

from clo_db_agent import data_access as da

_EQUITY_STEP = "Equity Distribution"


@beta_tool
def compute_equity_entitlement(fund_id: str) -> str:
    """Determine whether equity is entitled to a distribution and the expected amount (dp:DP-05).

    Applies clo:WaterfallPriorityAxiom: clo:EquityPiece receives the residual
    only after all clo:ComplianceTest pass. Returns the compliance gate status
    and the most recent equity distribution for comparison.

    Args:
        fund_id: Fund identifier.
    """
    compliance_tests = da.compliance(fund_id)
    cashflows = da.cashflows(fund_id)
    if not compliance_tests:
        return json.dumps({"status": "no_data", "fund_id": fund_id})

    failing = [t for t in compliance_tests if t.get("Pass/Fail") == "FAIL"]
    equity_blocked = len(failing) > 0

    eq_rows = [r for r in cashflows if _EQUITY_STEP in str(r.get("Waterfall Step", ""))]
    latest_equity = eq_rows[-1] if eq_rows else None

    return json.dumps({
        "fund_id": fund_id,
        "data_product": "dp:DP-04 + dp:DP-05",
        "ontology_class": "clo:EquityDistribution",
        "ontology_rule": "clo:WaterfallPriorityAxiom — equity receives residual after all tests pass",  # noqa: E501
        "equity_distribution_blocked": equity_blocked,
        "failing_test_count": len(failing),
        "failing_tests": [t["Test Name"] for t in failing],
        "latest_equity_distribution": {
            "payment_date": latest_equity["Payment Date"],
            "amount_usd": float(latest_equity.get("Equity Distribution Amount (USD)") or 0),
            "waterfall_step": latest_equity.get("Waterfall Step", ""),
        } if latest_equity else None,
    })


@beta_tool
def model_waterfall_diversion(fund_id: str) -> str:
    """Model the full payment waterfall for the latest payment date (dp:DP-05).

    Returns each clo:Waterfall step in priority order per clo:WaterfallPriorityAxiom,
    with amounts disbursed, OC diversions applied, and equity distribution received.

    Args:
        fund_id: Fund identifier.
    """
    cashflows = da.cashflows(fund_id)
    if not cashflows:
        return json.dumps({"status": "no_data", "fund_id": fund_id, "data_product": "dp:DP-05"})

    latest_date = max(r["Payment Date"] for r in cashflows)
    latest_rows = [r for r in cashflows if r["Payment Date"] == latest_date]

    total_diverted = sum(float(r.get("OC Diversion Amount (USD)") or 0) for r in latest_rows)
    total_equity = sum(float(r.get("Equity Distribution Amount (USD)") or 0) for r in latest_rows)
    first = latest_rows[0] if latest_rows else {}

    return json.dumps({
        "fund_id": fund_id,
        "data_product": "dp:DP-05",
        "ontology_class": "clo:Waterfall",
        "ontology_rule": "clo:WaterfallPriorityAxiom",
        "payment_date": latest_date,
        "total_interest_proceeds_usd": float(first.get("Total Interest Proceeds (USD)") or 0),
        "total_principal_proceeds_usd": float(first.get("Total Principal Proceeds (USD)") or 0),
        "total_oc_diversion_usd": total_diverted,
        "total_equity_distribution_usd": total_equity,
        "waterfall_steps": [
            {
                "waterfall_step": r.get("Waterfall Step", ""),
                "recipient": r.get("Recipient", ""),
                "amount_disbursed_usd": float(r.get("Amount Disbursed (USD)") or 0),
                "oc_diversion_usd": float(r.get("OC Diversion Amount (USD)") or 0),
                "equity_distribution_usd": float(r.get("Equity Distribution Amount (USD)") or 0),
                "management_fee_paid_usd": float(r.get("Management Fee Paid (USD)") or 0),
                "incentive_fee_paid_usd": float(r.get("Incentive Fee Paid (USD)") or 0),
            }
            for r in latest_rows
        ],
    })


CASHFLOW_TOOLS: list = [
    compute_equity_entitlement,
    model_waterfall_diversion,
]

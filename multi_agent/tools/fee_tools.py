"""Fee analysis tools extending the clo_db_agent fee tool.

Ontology classes served: clo:FeeExpense, clo:ManagementFee, clo:IncentiveFee
Data products: dp:DP-06, dp:DP-03
"""
from __future__ import annotations

import json

from anthropic import beta_tool

from clo_db_agent import data_access as da


@beta_tool
def compute_ytd_fees(fund_id: str) -> str:
    """Compute year-to-date fees by type from the fund fee ledger (dp:DP-06).

    Aggregates clo:ManagementFee, clo:IncentiveFee, trustee, admin, rating agency,
    and tax provisions. Returns the breakdown and grand total.

    Args:
        fund_id: Fund identifier.
    """
    rows = da.fees(fund_id)
    if not rows:
        return json.dumps({"status": "no_data", "fund_id": fund_id, "data_product": "dp:DP-06"})

    totals: dict[str, float] = {}
    for row in rows:
        fee_type = str(row.get("Fee Type") or "Unknown")
        ytd = float(row.get("Accrued YTD (USD)") or 0)
        totals[fee_type] = max(totals.get(fee_type, 0.0), ytd)

    grand_total = sum(totals.values())
    return json.dumps({
        "fund_id": fund_id,
        "data_product": "dp:DP-06",
        "ontology_class": "clo:FeeExpense",
        "total_ytd_fees_usd": grand_total,
        "ytd_fees_by_type": [
            {
                "fee_type": k,
                "accrued_ytd_usd": v,
                "pct_of_total": round(v / grand_total * 100, 2) if grand_total else 0.0,
            }
            for k, v in sorted(totals.items(), key=lambda x: -x[1])
        ],
    })


@beta_tool
def compute_fee_drag(fund_id: str) -> str:
    """Estimate fee drag on performance by comparing gross and net IRR (dp:DP-03 + dp:DP-06).

    clo:grossIRR minus clo:netIRR gives the inception-to-date fee impact.
    Also returns the Total Expense Ratio from the latest DP-06 period.

    Args:
        fund_id: Fund identifier.
    """
    fee_rows = da.fees(fund_id)
    perf_rows = da.performance(fund_id)
    if not fee_rows or not perf_rows:
        return json.dumps({"status": "no_data", "fund_id": fund_id})

    latest_perf = perf_rows[-1]
    gross_irr = float(latest_perf.get("Gross IRR (%)", 0) or 0)
    net_irr = float(latest_perf.get("Net IRR (%)", 0) or 0)

    ter_rows = [r for r in fee_rows if r.get("Fee Type") == "TER"]
    latest_ter = float(ter_rows[-1].get("Total Expense Ratio (%)") or 0) if ter_rows else None

    return json.dumps({
        "fund_id": fund_id,
        "data_product": "dp:DP-03 + dp:DP-06",
        "ontology_class": "clo:FeeExpense",
        "reporting_date": latest_perf.get("Reporting Date", ""),
        "gross_irr_pct": gross_irr,
        "net_irr_pct": net_irr,
        "irr_fee_drag_pp": round(gross_irr - net_irr, 4),
        "total_expense_ratio_pct": latest_ter,
        "note": (
            "Fee drag = clo:grossIRR minus clo:netIRR (inception-to-date). "
            "TER from latest dp:DP-06 period."
        ),
    })


FEE_TOOLS: list = [
    compute_ytd_fees,
    compute_fee_drag,
]

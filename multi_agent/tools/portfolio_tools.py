"""New portfolio analysis tools extending the clo_db_agent tool set.

Ontology classes served: clo:LoanAsset, clo:Obligor, clo:RatingAssessment
Data products: dp:DP-02, dp:DP-07
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from anthropic import beta_tool

from clo_db_agent import data_access as da

# clo:RatingDerivedRulesAxiom — Caa1 and below are CCC assets
_CCC_RATINGS: frozenset[str] = frozenset({"Caa1", "Caa2", "Caa3", "Ca", "C"})
_CCC_BUCKET_THRESHOLD_PCT = 7.5


@beta_tool
def identify_ccc_loans(fund_id: str) -> str:
    """Identify all CCC/Caa-rated loans per clo:RatingDerivedRulesAxiom (dp:DP-02).

    Per the ontology: any asset rated Caa1 or below is a CCC Asset. Assets above
    the 7.5% bucket threshold are haircut to market value (not par) in OC tests,
    directly reducing OC cushion (clo:OCTestFormulaAxiom.cccAdjustment).

    Args:
        fund_id: Fund identifier — call list_available_funds to enumerate valid values.
    """
    loans = da.portfolio(fund_id)
    if not loans:
        return json.dumps({"status": "no_data", "fund_id": fund_id, "data_product": "dp:DP-02"})

    total_par = sum(float(loan["Par Amount (USD)"]) for loan in loans)
    ccc_loans = [
        {
            "position_id": loan["Position ID"],
            "obligor_name": loan.get("Obligor Name", ""),
            "moodys_rating": loan.get("Moody's Rating", "NR"),
            "par_amount_usd": float(loan["Par Amount (USD)"]),
            "market_value_usd": float(loan["Market Value (USD)"]),
            "price_pct_par": float(loan.get("Price (% par)") or 100.0),
            "oc_haircut_usd": float(loan["Par Amount (USD)"]) - float(loan["Market Value (USD)"]),
        }
        for loan in loans
        if loan.get("Moody's Rating", "") in _CCC_RATINGS
    ]
    ccc_par = sum(c["par_amount_usd"] for c in ccc_loans)
    ccc_pct = round(ccc_par / total_par * 100, 2) if total_par else 0.0

    return json.dumps({
        "fund_id": fund_id,
        "data_product": "dp:DP-02",
        "ontology_class": "clo:LoanAsset",
        "ontology_rule": "clo:RatingDerivedRulesAxiom.cccDefinition",
        "ccc_bucket_threshold_pct": _CCC_BUCKET_THRESHOLD_PCT,
        "ccc_loan_count": len(ccc_loans),
        "ccc_par_usd": ccc_par,
        "ccc_pct_of_pool": ccc_pct,
        "exceeds_threshold": ccc_pct > _CCC_BUCKET_THRESHOLD_PCT,
        "total_pool_par_usd": total_par,
        "ccc_loans": ccc_loans,
    })


@beta_tool
def identify_maturing_loans(fund_id: str, within_days: int = 365) -> str:
    """Identify loans maturing within the specified number of days (dp:DP-02).

    Maturing positions reduce pool par, affecting OC ratios and — for funds still in
    the reinvestment period (clo:ReinvestmentPeriodAxiom) — create reinvestment pressure.

    Args:
        fund_id:     Fund identifier.
        within_days: Calendar days from today. Default: 365.
    """
    loans = da.portfolio(fund_id)
    if not loans:
        return json.dumps({"status": "no_data", "fund_id": fund_id, "data_product": "dp:DP-02"})

    cutoff = date.today() + timedelta(days=within_days)
    maturing = []
    for loan in loans:
        try:
            mat = date.fromisoformat(str(loan["Maturity Date"])[:10])
        except (ValueError, TypeError):
            continue
        if mat <= cutoff:
            maturing.append({
                "position_id": loan["Position ID"],
                "obligor_name": loan.get("Obligor Name", ""),
                "moodys_rating": loan.get("Moody's Rating", "NR"),
                "par_amount_usd": float(loan["Par Amount (USD)"]),
                "spread_sofr_bps": int(float(loan["Spread (SOFR+ bps)"])),
                "maturity_date": str(loan["Maturity Date"])[:10],
                "days_to_maturity": (mat - date.today()).days,
            })

    maturing.sort(key=lambda x: x["days_to_maturity"])
    return json.dumps({
        "fund_id": fund_id,
        "data_product": "dp:DP-02",
        "ontology_class": "clo:LoanAsset",
        "ontology_property": "clo:maturityDate",
        "within_days": within_days,
        "cutoff_date": cutoff.isoformat(),
        "maturing_loan_count": len(maturing),
        "maturing_par_usd": sum(m["par_amount_usd"] for m in maturing),
        "loans": maturing,
    })


@beta_tool
def compute_industry_concentration(fund_id: str) -> str:
    """Compute par-weighted industry concentration from the portfolio (dp:DP-02).

    Uses clo:industryCode (Moody's taxonomy). Flags any industry exceeding 15% of pool
    — the typical indenture concentration limit per clo:ComplianceTest (concentration type).

    Args:
        fund_id: Fund identifier.
    """
    loans = da.portfolio(fund_id)
    if not loans:
        return json.dumps({"status": "no_data", "fund_id": fund_id, "data_product": "dp:DP-02"})

    total_par = sum(float(loan["Par Amount (USD)"]) for loan in loans)
    if total_par == 0:
        return json.dumps({"status": "no_data", "fund_id": fund_id})

    buckets: dict[str, float] = {}
    for loan in loans:
        industry = str(loan.get("Industry (Moody's)") or "Unknown")
        buckets[industry] = buckets.get(industry, 0.0) + float(loan["Par Amount (USD)"])

    rows = sorted(
        [
            {
                "industry": ind,
                "par_usd": par,
                "pct_of_pool": round(par / total_par * 100, 2),
                "exceeds_15pct_limit": (par / total_par * 100) > 15.0,
            }
            for ind, par in buckets.items()
        ],
        key=lambda x: -x["par_usd"],
    )

    return json.dumps({
        "fund_id": fund_id,
        "data_product": "dp:DP-02",
        "ontology_class": "clo:LoanAsset",
        "ontology_property": "clo:industryCode",
        "total_par_usd": total_par,
        "industry_count": len(rows),
        "concentration_limit_pct": 15.0,
        "industries_exceeding_limit": [r["industry"] for r in rows if r["exceeds_15pct_limit"]],
        "industries": rows,
    })


PORTFOLIO_TOOLS: list = [
    identify_ccc_loans,
    identify_maturing_loans,
    compute_industry_concentration,
]

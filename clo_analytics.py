"""Shared loan-level computation utilities for CLO portfolio analysis.

All functions operate on loan lists in the same dict format returned by
data_access.portfolio() in both clo_agent and clo_db_agent.
"""

from __future__ import annotations

from datetime import date
from typing import Any

# Standard Moody's WARF factor table (industry convention).
# Maps each rating symbol to its default-probability factor on the 1–10000 scale.
MOODYS_RATING_FACTORS: dict[str, int] = {
    "Aaa": 1,
    "Aa1": 10,  "Aa2": 20,   "Aa3": 40,
    "A1":  70,  "A2":  120,  "A3":  180,
    "Baa1": 260, "Baa2": 360, "Baa3": 610,
    "Ba1": 940,  "Ba2": 1350, "Ba3": 1766,
    "B1":  2220, "B2":  2720, "B3":  3490,
    "Caa1": 4770, "Caa2": 6500, "Caa3": 8070,
    "Ca": 10000, "C": 10000,
    "NR": 10000, "WR": 10000,
}


def _rating_factor(rating: str | None) -> int:
    if not rating:
        return MOODYS_RATING_FACTORS["NR"]
    return MOODYS_RATING_FACTORS.get(str(rating).strip(), MOODYS_RATING_FACTORS["NR"])


def _parse_date(d: Any) -> date:
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def compute_portfolio_metrics(
    loans: list[dict[str, Any]],
    reference_date: str,
) -> dict[str, Any]:
    """Compute WARF, WAS (bps), and WAL (years) via par-weighted averages.

    Args:
        loans: loan dicts in the format returned by data_access.portfolio().
        reference_date: ISO date string (YYYY-MM-DD) used as base for WAL.
    """
    total_par = sum(float(loan["Par Amount (USD)"]) for loan in loans)
    if total_par == 0:
        return {
            "warf": 0, "was_bps": 0, "wal_years": 0.0,
            "total_par_usd": 0.0, "loan_count": 0,
        }
    ref = date.fromisoformat(reference_date)
    warf = was = wal = 0.0
    for loan in loans:
        par = float(loan["Par Amount (USD)"])
        w = par / total_par
        warf += w * _rating_factor(loan.get("Moody's Rating"))
        was += w * float(loan["Spread (SOFR+ bps)"])
        years = max(0.0, (_parse_date(loan["Maturity Date"]) - ref).days / 365.25)
        wal += w * years
    return {
        "warf": round(warf),
        "was_bps": round(was),
        "wal_years": round(wal, 2),
        "total_par_usd": total_par,
        "loan_count": len(loans),
    }


def simulate_replacement(
    loans: list[dict[str, Any]],
    remove_position_id: str,
    new_loan: dict[str, Any],
    reference_date: str,
) -> dict[str, Any]:
    """Compute portfolio metrics before and after replacing one loan.

    Args:
        loans: current portfolio loan list.
        remove_position_id: Position ID to remove; must exist in loans.
        new_loan: dict with "Par Amount (USD)", "Spread (SOFR+ bps)",
                  "Moody's Rating", "Maturity Date" at minimum.
        reference_date: ISO date string (YYYY-MM-DD) for WAL calculation.

    Raises:
        ValueError: if remove_position_id is not found in the portfolio.
    """
    removed = next((loan for loan in loans if loan["Position ID"] == remove_position_id), None)
    if removed is None:
        valid = sorted(loan["Position ID"] for loan in loans)
        raise ValueError(
            f"Position {remove_position_id!r} not found in portfolio. Valid IDs: {valid}"
        )
    remaining_plus_new = (
        [loan for loan in loans if loan["Position ID"] != remove_position_id] + [new_loan]
    )
    current = compute_portfolio_metrics(loans, reference_date)
    simulated = compute_portfolio_metrics(remaining_plus_new, reference_date)
    return {
        "current": current,
        "simulated": simulated,
        "delta": {
            "warf": simulated["warf"] - current["warf"],
            "was_bps": simulated["was_bps"] - current["was_bps"],
            "wal_years": round(simulated["wal_years"] - current["wal_years"], 2),
        },
        "removed_loan": {
            "position_id": removed["Position ID"],
            "obligor_name": removed.get("Obligor Name", ""),
            "par_usd": float(removed["Par Amount (USD)"]),
            "spread_bps": int(float(removed["Spread (SOFR+ bps)"])),
            "moodys_rating": removed.get("Moody's Rating", "NR"),
            "maturity_date": str(removed["Maturity Date"])[:10],
        },
        "new_loan_spec": {
            "par_usd": float(new_loan["Par Amount (USD)"]),
            "spread_bps": int(float(new_loan["Spread (SOFR+ bps)"])),
            "moodys_rating": new_loan.get("Moody's Rating", "NR"),
            "maturity_date": str(new_loan["Maturity Date"])[:10],
        },
        "reference_date": reference_date,
    }


def compute_asset_contributions(loans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute per-loan return-contribution metrics, sorted by MTM P&L descending.

    Returns:
        List of dicts with: position_id, obligor_name, industry, moodys_rating,
        par_usd, par_weight_pct, market_value_usd, price_pct_par, mtm_pnl_usd,
        mtm_contribution_to_par_pct, spread_bps, spread_contribution_to_was_bps,
        annualized_spread_income_est_usd.

    Note: annualized_spread_income_est_usd is par × spread_bps / 10000 (spread
    component only — the SOFR base rate is not stored in DP-02).
    """
    total_par = sum(float(loan["Par Amount (USD)"]) for loan in loans)
    if total_par == 0:
        return []
    results = []
    for loan in loans:
        par = float(loan["Par Amount (USD)"])
        mv = float(loan["Market Value (USD)"])
        spread = int(float(loan["Spread (SOFR+ bps)"]))
        par_weight = par / total_par
        mtm_pnl = mv - par
        results.append({
            "position_id": loan["Position ID"],
            "obligor_name": loan.get("Obligor Name", ""),
            "industry": loan.get("Industry (Moody's)", ""),
            "moodys_rating": loan.get("Moody's Rating", "NR"),
            "par_usd": par,
            "par_weight_pct": round(par_weight * 100, 3),
            "market_value_usd": mv,
            "price_pct_par": float(loan.get("Price (% par)") or 100.0),
            "mtm_pnl_usd": round(mtm_pnl, 2),
            "mtm_contribution_to_par_pct": round(mtm_pnl / total_par * 100, 4),
            "spread_bps": spread,
            "spread_contribution_to_was_bps": round(par_weight * spread, 2),
            "annualized_spread_income_est_usd": round(par * spread / 10_000, 2),
        })
    results.sort(key=lambda x: x["mtm_pnl_usd"], reverse=True)
    return results

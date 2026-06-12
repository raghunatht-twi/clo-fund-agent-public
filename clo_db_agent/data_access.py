"""PostgreSQL-backed data access for the CLO DB agent.

Returns the same dict shapes as clo_agent/data_access.py (Excel reader) so
the tools layer is identical between the two agents.  Column aliases in each
query map snake_case DB names back to the original Excel header strings.

Supports any fund present in the dp01_fund_static_profile table.
"""

from __future__ import annotations

import threading
from typing import Any

import psycopg2
import psycopg2.extras
from cachetools import TTLCache
from cachetools.keys import hashkey
from psycopg2.pool import ThreadedConnectionPool

from . import DB_DSN

# ---------------------------------------------------------------------------
# Connection pool  (F-10)
# ---------------------------------------------------------------------------
_pool_lock = threading.Lock()
_pool: ThreadedConnectionPool | None = None


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=DB_DSN)
    return _pool


def _query(sql: str, fund_id: str) -> list[dict[str, Any]]:
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (fund_id,))
            return [dict(row) for row in cur.fetchall()]
    finally:
        pool.putconn(conn)


# ---------------------------------------------------------------------------
# TTL cache  (F-10, F-17)
# 5-minute TTL ensures live data is served after a reload without a restart
# ---------------------------------------------------------------------------
_CACHE_TTL = 300  # seconds
_cache: TTLCache = TTLCache(maxsize=256, ttl=_CACHE_TTL)
_cache_lock = threading.Lock()


def _cached(key, fn):
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    result = fn()
    with _cache_lock:
        _cache[key] = result
    return result


# ---------------------------------------------------------------------------
# DP-00 Fund discovery  (F-17: now cached with 60s TTL)
# ---------------------------------------------------------------------------
_fund_list_cache: TTLCache = TTLCache(maxsize=1, ttl=60)
_fund_list_lock = threading.Lock()


def list_funds() -> list[str]:
    """Return all distinct fund_id values present in the database."""
    with _fund_list_lock:
        if "funds" in _fund_list_cache:
            return _fund_list_cache["funds"]
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT fund_id FROM dp01_fund_static_profile ORDER BY fund_id"
            )
            result = [row[0] for row in cur.fetchall()]
    finally:
        pool.putconn(conn)
    with _fund_list_lock:
        _fund_list_cache["funds"] = result
    return result


def static_profile(fund_id: str = "DKIG-2024-VII") -> dict[str, Any]:
    def _fetch():
        rows = _query(
            "SELECT attribute, value FROM dp01_fund_static_profile "
            "WHERE fund_id = %s ORDER BY id",
            fund_id,
        )
        return {r["attribute"]: r["value"] for r in rows}
    return _cached(hashkey("static_profile", fund_id), _fetch)


def portfolio(fund_id: str = "DKIG-2024-VII") -> list[dict[str, Any]]:
    def _fetch():
        return _query(
            """
            SELECT
                position_id          AS "Position ID",
                obligor_name         AS "Obligor Name",
                facility_cusip       AS "Facility CUSIP",
                industry             AS "Industry (Moody's)",
                country              AS "Country",
                loan_type            AS "Loan Type",
                par_amount_usd       AS "Par Amount (USD)",
                market_value_usd     AS "Market Value (USD)",
                price_pct_par        AS "Price (%% par)",
                spread_sofr_bps      AS "Spread (SOFR+ bps)",
                maturity_date::text  AS "Maturity Date",
                moodys_rating        AS "Moody's Rating",
                sp_rating            AS "S&P Rating",
                fitch_rating         AS "Fitch Rating",
                pik_flag             AS "PIK Flag",
                lbo_flag             AS "LBO Flag",
                covenant_lite_flag   AS "Covenant-Lite Flag",
                days_past_due        AS "Days Past Due"
            FROM dp02_portfolio_snapshot
            WHERE fund_id = %s
            ORDER BY position_id
            """,
            fund_id,
        )
    return _cached(hashkey("portfolio", fund_id), _fetch)


def performance(fund_id: str = "DKIG-2024-VII") -> list[dict[str, Any]]:
    def _fetch():
        return _query(
            """
            SELECT
                reporting_date::text          AS "Reporting Date",
                total_fund_nav_usd            AS "Total Fund NAV (USD)",
                equity_nav_usd                AS "Equity NAV (USD)",
                gross_irr_pct                 AS "Gross IRR (%%)",
                net_irr_pct                   AS "Net IRR (%%)",
                dpi                           AS "DPI",
                rvpi                          AS "RVPI",
                tvpi                          AS "TVPI",
                itd_pl_usd                    AS "Inception-to-Date P&L (USD)",
                current_period_pl_usd         AS "Current Period P&L (USD)",
                unrealised_gl_usd             AS "Unrealised G/L (USD)",
                realised_gl_usd               AS "Realised G/L (USD)",
                total_interest_income_usd     AS "Total Interest Income (USD)",
                benchmark_return_pct          AS "Benchmark Return (%%)",
                excess_return_pct             AS "Excess Return vs Benchmark (%%)"
            FROM dp03_performance
            WHERE fund_id = %s
            ORDER BY reporting_date
            """,
            fund_id,
        )
    return _cached(hashkey("performance", fund_id), _fetch)


def compliance(fund_id: str = "DKIG-2024-VII") -> list[dict[str, Any]]:
    def _fetch():
        return _query(
            """
            SELECT
                test_id              AS "Test ID",
                test_name            AS "Test Name",
                test_type            AS "Test Type",
                tranche_class        AS "Tranche Class",
                current_value        AS "Current Value",
                threshold            AS "Threshold",
                cushion              AS "Cushion",
                pass_fail            AS "Pass/Fail",
                breach_consequence   AS "Breach Consequence",
                last_tested::text    AS "Last Tested"
            FROM dp04_compliance
            WHERE fund_id = %s
            ORDER BY test_id
            """,
            fund_id,
        )
    return _cached(hashkey("compliance", fund_id), _fetch)


def cashflows(fund_id: str = "DKIG-2024-VII") -> list[dict[str, Any]]:
    def _fetch():
        return _query(
            """
            SELECT
                payment_date::text                  AS "Payment Date",
                collection_period                   AS "Collection Period",
                total_interest_proceeds_usd         AS "Total Interest Proceeds (USD)",
                total_principal_proceeds_usd        AS "Total Principal Proceeds (USD)",
                reinvestment_proceeds_usd           AS "Reinvestment Proceeds (USD)",
                recoveries_usd                      AS "Recoveries (USD)",
                waterfall_step                      AS "Waterfall Step",
                recipient                           AS "Recipient",
                amount_disbursed_usd                AS "Amount Disbursed (USD)",
                oc_diversion_amount_usd             AS "OC Diversion Amount (USD)",
                equity_distribution_amount_usd      AS "Equity Distribution Amount (USD)",
                management_fee_paid_usd             AS "Management Fee Paid (USD)",
                incentive_fee_paid_usd              AS "Incentive Fee Paid (USD)",
                trustee_fee_paid_usd                AS "Trustee Fee Paid (USD)"
            FROM dp05_cashflows
            WHERE fund_id = %s
            ORDER BY payment_date, id
            """,
            fund_id,
        )
    return _cached(hashkey("cashflows", fund_id), _fetch)


def fees(fund_id: str = "DKIG-2024-VII") -> list[dict[str, Any]]:
    def _fetch():
        return _query(
            """
            SELECT
                period                          AS "Period",
                fee_type                        AS "Fee Type",
                fee_rate_amount                 AS "Fee Rate / Amount",
                accrued_ytd_usd                 AS "Accrued YTD (USD)",
                accrued_current_period_usd      AS "Accrued Current Period (USD)",
                amount_paid_current_period_usd  AS "Amount Paid Current Period (USD)",
                cumulative_amount_paid_usd      AS "Cumulative Amount Paid (USD)",
                hurdle_rate_pct                 AS "Hurdle Rate (%%)",
                catchup_pct                     AS "Catch-up (%%)",
                tax_provision_usd               AS "Tax Provision (USD)",
                effective_tax_rate_pct          AS "Effective Tax Rate (%%)",
                total_expense_ratio_pct         AS "Total Expense Ratio (%%)"
            FROM dp06_fees
            WHERE fund_id = %s
            ORDER BY id
            """,
            fund_id,
        )
    return _cached(hashkey("fees", fund_id), _fetch)


def key_metrics(fund_id: str = "DKIG-2024-VII") -> list[dict[str, Any]]:
    def _fetch():
        return _query(
            """
            SELECT
                reporting_date::text                AS "Reporting Date",
                was_bps_over_sofr                   AS "WAS (bps over SOFR)",
                warf                                AS "WARF",
                wal_years                           AS "WAL (years)",
                wac_pct                             AS "WAC (%%)",
                weighted_avg_recovery_rate_pct      AS "Weighted Avg Recovery Rate (%%)",
                par_build_loss_vs_target_usd        AS "Par Build/Loss vs Target (USD)",
                pct_floating_rate                   AS "%% Floating Rate",
                pct_fixed_rate                      AS "%% Fixed Rate",
                pct_pik                             AS "%% PIK",
                pct_ccc_caa                         AS "%% CCC/Caa",
                pct_covenant_lite                   AS "%% Covenant-Lite",
                diversity_score                     AS "Diversity Score",
                number_of_obligors                  AS "Number of Obligors",
                number_of_industries                AS "Number of Industries",
                largest_single_obligor_pct          AS "Largest Single Obligor (%%)",
                largest_single_industry_pct         AS "Largest Single Industry (%%)",
                top10_obligor_concentration_pct     AS "Top 10 Obligor Concentration (%%)"
            FROM dp07_key_metrics
            WHERE fund_id = %s
            ORDER BY reporting_date
            """,
            fund_id,
        )
    return _cached(hashkey("key_metrics", fund_id), _fetch)


def liability_structure(fund_id: str = "DKIG-2024-VII") -> list[dict[str, Any]]:
    def _fetch():
        return _query(
            """
            SELECT
                tranche_class                       AS "Tranche Class",
                cusip                               AS "CUSIP",
                initial_notional_usd                AS "Initial Notional (USD)",
                current_notional_usd                AS "Current Notional (USD)",
                coupon_type                         AS "Coupon Type",
                coupon_rate_sofr_bps                AS "Coupon Rate (SOFR+ bps)",
                payment_frequency                   AS "Payment Frequency",
                moodys_rating                       AS "Moody's Rating",
                sp_rating                           AS "S&P Rating",
                fitch_rating                        AS "Fitch Rating",
                subordination_level_pct             AS "Subordination Level (%%)",
                oc_cushion_pct                      AS "OC Cushion (%%)",
                ic_cushion_pct                      AS "IC Cushion (%%)",
                waterfall_priority                  AS "Waterfall Priority",
                cumulative_principal_repaid_usd     AS "Cumulative Principal Repaid (USD)",
                interest_paid_current_period_usd    AS "Interest Paid Current Period (USD)",
                interest_accrued_usd                AS "Interest Accrued (USD)",
                rating_outlook                      AS "Rating Outlook"
            FROM dp08_liability_structure
            WHERE fund_id = %s
            ORDER BY waterfall_priority
            """,
            fund_id,
        )
    return _cached(hashkey("liability_structure", fund_id), _fetch)

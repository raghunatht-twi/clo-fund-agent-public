"""Load all CLO fund synthetic data from generate_data.py into PostgreSQL.

Usage:
    python -m db.load_data

Connects to the local socket-based PostgreSQL (host=/tmp, port=5432).
Truncates and reloads all 8 DP tables on each run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Resolve project root so we can import generate_data
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

import generate_data as gd  # noqa: E402

# F-03: DSN from environment — override for non-local deployments
DSN = os.environ.get("DATABASE_URL", "host=/tmp port=5432 dbname=postgres")


def connect() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    return conn


def _val(v: object) -> str | None:
    return None if v is None else str(v)


def load_dp01(cur: Any, fund_id: str, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp01_fund_static_profile WHERE fund_id = %s", (fund_id,))
    cur.executemany(
        """
        INSERT INTO dp01_fund_static_profile (fund_id, attribute, value)
        VALUES (%s, %s, %s)
        ON CONFLICT (fund_id, attribute) DO UPDATE SET value = EXCLUDED.value
        """,
        [(fund_id, attr, _val(val)) for attr, val in rows],
    )


def load_dp02(cur: Any, fund_id: str, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp02_portfolio_snapshot WHERE fund_id = %s", (fund_id,))
    cur.executemany(
        """
        INSERT INTO dp02_portfolio_snapshot
          (fund_id, position_id, obligor_name, facility_cusip, industry,
           country, loan_type, par_amount_usd, market_value_usd,
           price_pct_par, spread_sofr_bps, maturity_date,
           moodys_rating, sp_rating, fitch_rating,
           pik_flag, lbo_flag, covenant_lite_flag, days_past_due)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (fund_id, position_id) DO UPDATE SET
          obligor_name = EXCLUDED.obligor_name,
          market_value_usd = EXCLUDED.market_value_usd
        """,
        [
            (fund_id, r[0], r[1], r[2], r[3], r[4], r[5],
             r[6], r[7], r[8], r[9], r[10],
             r[11], r[12], r[13], r[14], r[15], r[16], r[17])
            for r in rows
        ],
    )


def load_dp03(cur: Any, fund_id: str, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp03_performance WHERE fund_id = %s", (fund_id,))
    cur.executemany(
        """
        INSERT INTO dp03_performance
          (fund_id, reporting_date, total_fund_nav_usd, equity_nav_usd,
           gross_irr_pct, net_irr_pct, dpi, rvpi, tvpi,
           itd_pl_usd, current_period_pl_usd, unrealised_gl_usd,
           realised_gl_usd, total_interest_income_usd,
           benchmark_return_pct, excess_return_pct)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (fund_id, reporting_date) DO UPDATE SET
          total_fund_nav_usd = EXCLUDED.total_fund_nav_usd,
          equity_nav_usd = EXCLUDED.equity_nav_usd
        """,
        [(fund_id, *r) for r in rows],
    )


def load_dp04(cur: Any, fund_id: str, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp04_compliance WHERE fund_id = %s", (fund_id,))
    cur.executemany(
        """
        INSERT INTO dp04_compliance
          (fund_id, test_id, test_name, test_type, tranche_class,
           current_value, threshold, cushion, pass_fail,
           breach_consequence, last_tested)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (fund_id, test_id) DO UPDATE SET
          current_value = EXCLUDED.current_value,
          pass_fail = EXCLUDED.pass_fail
        """,
        [(fund_id, *r) for r in rows],
    )


def load_dp05(cur: Any, fund_id: str, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp05_cashflows WHERE fund_id = %s", (fund_id,))
    cur.executemany(
        """
        INSERT INTO dp05_cashflows
          (fund_id, payment_date, collection_period,
           total_interest_proceeds_usd, total_principal_proceeds_usd,
           reinvestment_proceeds_usd, recoveries_usd,
           waterfall_step, recipient, amount_disbursed_usd,
           oc_diversion_amount_usd, equity_distribution_amount_usd,
           management_fee_paid_usd, incentive_fee_paid_usd,
           trustee_fee_paid_usd)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        [(fund_id, *r) for r in rows],
    )


def load_dp06(cur: Any, fund_id: str, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp06_fees WHERE fund_id = %s", (fund_id,))
    cur.executemany(
        """
        INSERT INTO dp06_fees
          (fund_id, period, fee_type, fee_rate_amount,
           accrued_ytd_usd, accrued_current_period_usd,
           amount_paid_current_period_usd, cumulative_amount_paid_usd,
           hurdle_rate_pct, catchup_pct, tax_provision_usd,
           effective_tax_rate_pct, total_expense_ratio_pct)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        [(fund_id, *r) for r in rows],
    )


def load_dp07(cur: Any, fund_id: str, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp07_key_metrics WHERE fund_id = %s", (fund_id,))
    cur.executemany(
        """
        INSERT INTO dp07_key_metrics
          (fund_id, reporting_date, was_bps_over_sofr, warf, wal_years,
           wac_pct, weighted_avg_recovery_rate_pct,
           par_build_loss_vs_target_usd,
           pct_floating_rate, pct_fixed_rate, pct_pik, pct_ccc_caa,
           pct_covenant_lite, diversity_score, number_of_obligors,
           number_of_industries, largest_single_obligor_pct,
           largest_single_industry_pct, top10_obligor_concentration_pct)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (fund_id, reporting_date) DO UPDATE SET
          warf = EXCLUDED.warf, was_bps_over_sofr = EXCLUDED.was_bps_over_sofr
        """,
        [(fund_id, *r) for r in rows],
    )


def load_dp08(cur: Any, fund_id: str, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp08_liability_structure WHERE fund_id = %s", (fund_id,))
    cur.executemany(
        """
        INSERT INTO dp08_liability_structure
          (fund_id, tranche_class, cusip, initial_notional_usd,
           current_notional_usd, coupon_type, coupon_rate_sofr_bps,
           payment_frequency, moodys_rating, sp_rating, fitch_rating,
           subordination_level_pct, oc_cushion_pct, ic_cushion_pct,
           waterfall_priority, cumulative_principal_repaid_usd,
           interest_paid_current_period_usd, interest_accrued_usd,
           rating_outlook)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (fund_id, tranche_class) DO UPDATE SET
          current_notional_usd = EXCLUDED.current_notional_usd,
          cumulative_principal_repaid_usd = EXCLUDED.cumulative_principal_repaid_usd
        """,
        [(fund_id, *r) for r in rows],
    )


FUND1 = "DKIG-2024-VII"
FUND2 = "DKIG-2016-I"


def main() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            print(f"Loading {FUND1}...")
            load_dp01(cur, FUND1, gd.DP01_ROWS)
            load_dp02(cur, FUND1, gd.DP02_ROWS)
            load_dp03(cur, FUND1, gd.DP03_ROWS)
            load_dp04(cur, FUND1, gd.DP04_ROWS)
            load_dp05(cur, FUND1, gd.DP05_ROWS)
            load_dp06(cur, FUND1, gd.DP06_ROWS)
            load_dp07(cur, FUND1, gd.DP07_ROWS)
            load_dp08(cur, FUND1, gd.DP08_ROWS)

            print(f"Loading {FUND2}...")
            load_dp01(cur, FUND2, gd.F2_DP01_ROWS)
            load_dp02(cur, FUND2, gd.F2_DP02_ROWS)
            load_dp03(cur, FUND2, gd.F2_DP03_ROWS)
            load_dp04(cur, FUND2, gd.F2_DP04_ROWS)
            load_dp05(cur, FUND2, gd.F2_DP05_ROWS)
            load_dp06(cur, FUND2, gd.F2_DP06_ROWS)
            load_dp07(cur, FUND2, gd.F2_DP07_ROWS)
            load_dp08(cur, FUND2, gd.F2_DP08_ROWS)

        conn.commit()
        print("All data loaded successfully.")
    except psycopg2.DatabaseError as e:
        conn.rollback()
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

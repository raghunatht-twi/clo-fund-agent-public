-- CLO Fund Domain Data — PostgreSQL schema
-- Covers all 8 data products for both funds:
--   DKIG-2024-VII  and  DKIG-2016-I

-- DP-01 Fund Static Profile
CREATE TABLE IF NOT EXISTS dp01_fund_static_profile (
    id          SERIAL PRIMARY KEY,
    fund_id     VARCHAR(20)  NOT NULL,
    attribute   TEXT         NOT NULL,
    value       TEXT,
    UNIQUE (fund_id, attribute)
);

-- DP-02 Fund Portfolio Snapshot
CREATE TABLE IF NOT EXISTS dp02_portfolio_snapshot (
    id                  SERIAL PRIMARY KEY,
    fund_id             VARCHAR(20)   NOT NULL,
    position_id         VARCHAR(10)   NOT NULL,
    obligor_name        VARCHAR(150),
    facility_cusip      VARCHAR(20),
    industry            VARCHAR(100),
    country             VARCHAR(10),
    loan_type           VARCHAR(20),
    par_amount_usd      NUMERIC(18,2),
    market_value_usd    NUMERIC(18,2),
    price_pct_par       NUMERIC(8,4),
    spread_sofr_bps     INTEGER,
    maturity_date       DATE,
    moodys_rating       VARCHAR(10),
    sp_rating           VARCHAR(10),
    fitch_rating        VARCHAR(10),
    pik_flag            CHAR(1),
    lbo_flag            CHAR(1),
    covenant_lite_flag  CHAR(1),
    days_past_due       INTEGER,
    UNIQUE (fund_id, position_id)
);

-- DP-03 Fund Performance Metrics
CREATE TABLE IF NOT EXISTS dp03_performance (
    id                          SERIAL PRIMARY KEY,
    fund_id                     VARCHAR(20)   NOT NULL,
    reporting_date              DATE          NOT NULL,
    total_fund_nav_usd          NUMERIC(18,2),
    equity_nav_usd              NUMERIC(18,2),
    gross_irr_pct               NUMERIC(8,4),
    net_irr_pct                 NUMERIC(8,4),
    dpi                         NUMERIC(8,4),
    rvpi                        NUMERIC(8,4),
    tvpi                        NUMERIC(8,4),
    itd_pl_usd                  NUMERIC(18,2),
    current_period_pl_usd       NUMERIC(18,2),
    unrealised_gl_usd           NUMERIC(18,2),
    realised_gl_usd             NUMERIC(18,2),
    total_interest_income_usd   NUMERIC(18,2),
    benchmark_return_pct        NUMERIC(8,4),
    excess_return_pct           NUMERIC(8,4),
    UNIQUE (fund_id, reporting_date)
);

-- DP-04 Fund Compliance Dashboard
CREATE TABLE IF NOT EXISTS dp04_compliance (
    id                  SERIAL PRIMARY KEY,
    fund_id             VARCHAR(20)   NOT NULL,
    test_id             VARCHAR(10)   NOT NULL,
    test_name           VARCHAR(150),
    test_type           VARCHAR(20),
    tranche_class       VARCHAR(20),
    current_value       NUMERIC(12,6),
    threshold           NUMERIC(12,6),
    cushion             NUMERIC(12,6),
    pass_fail           VARCHAR(4),
    breach_consequence  TEXT,
    last_tested         DATE,
    UNIQUE (fund_id, test_id)
);

-- DP-05 Fund Cashflow Statement (one row per waterfall step per payment date)
CREATE TABLE IF NOT EXISTS dp05_cashflows (
    id                              SERIAL PRIMARY KEY,
    fund_id                         VARCHAR(20)   NOT NULL,
    payment_date                    DATE,
    collection_period               VARCHAR(60),
    total_interest_proceeds_usd     NUMERIC(18,2),
    total_principal_proceeds_usd    NUMERIC(18,2),
    reinvestment_proceeds_usd       NUMERIC(18,2),
    recoveries_usd                  NUMERIC(18,2),
    waterfall_step                  VARCHAR(120),
    recipient                       VARCHAR(120),
    amount_disbursed_usd            NUMERIC(18,2),
    oc_diversion_amount_usd         NUMERIC(18,2),
    equity_distribution_amount_usd  NUMERIC(18,2),
    management_fee_paid_usd         NUMERIC(18,2),
    incentive_fee_paid_usd          NUMERIC(18,2),
    trustee_fee_paid_usd            NUMERIC(18,2)
);

-- DP-06 Fund Fee & Expense Ledger
CREATE TABLE IF NOT EXISTS dp06_fees (
    id                              SERIAL PRIMARY KEY,
    fund_id                         VARCHAR(20)   NOT NULL,
    period                          VARCHAR(20),
    fee_type                        VARCHAR(120),
    fee_rate_amount                 VARCHAR(60),
    accrued_ytd_usd                 NUMERIC(18,2),
    accrued_current_period_usd      NUMERIC(18,2),
    amount_paid_current_period_usd  NUMERIC(18,2),
    cumulative_amount_paid_usd      NUMERIC(18,2),
    hurdle_rate_pct                 NUMERIC(8,4),
    catchup_pct                     NUMERIC(8,4),
    tax_provision_usd               NUMERIC(18,2),
    effective_tax_rate_pct          NUMERIC(8,4),
    total_expense_ratio_pct         NUMERIC(8,4)
);

-- DP-07 Fund Key Metrics Tracker
CREATE TABLE IF NOT EXISTS dp07_key_metrics (
    id                                  SERIAL PRIMARY KEY,
    fund_id                             VARCHAR(20)   NOT NULL,
    reporting_date                      DATE          NOT NULL,
    was_bps_over_sofr                   INTEGER,
    warf                                INTEGER,
    wal_years                           NUMERIC(6,2),
    wac_pct                             NUMERIC(8,4),
    weighted_avg_recovery_rate_pct      NUMERIC(8,4),
    par_build_loss_vs_target_usd        NUMERIC(18,2),
    pct_floating_rate                   NUMERIC(8,4),
    pct_fixed_rate                      NUMERIC(8,4),
    pct_pik                             NUMERIC(8,4),
    pct_ccc_caa                         NUMERIC(8,4),
    pct_covenant_lite                   NUMERIC(8,4),
    diversity_score                     NUMERIC(6,1),
    number_of_obligors                  INTEGER,
    number_of_industries                INTEGER,
    largest_single_obligor_pct          NUMERIC(8,4),
    largest_single_industry_pct         NUMERIC(8,4),
    top10_obligor_concentration_pct     NUMERIC(8,4),
    UNIQUE (fund_id, reporting_date)
);

-- DP-08 Fund Liability Structure
CREATE TABLE IF NOT EXISTS dp08_liability_structure (
    id                              SERIAL PRIMARY KEY,
    fund_id                         VARCHAR(20)   NOT NULL,
    tranche_class                   VARCHAR(20)   NOT NULL,
    cusip                           VARCHAR(20),
    initial_notional_usd            NUMERIC(18,2),
    current_notional_usd            NUMERIC(18,2),
    coupon_type                     VARCHAR(20),
    coupon_rate_sofr_bps            INTEGER,
    payment_frequency               VARCHAR(20),
    moodys_rating                   VARCHAR(10),
    sp_rating                       VARCHAR(10),
    fitch_rating                    VARCHAR(10),
    subordination_level_pct         NUMERIC(8,4),
    oc_cushion_pct                  NUMERIC(8,4),
    ic_cushion_pct                  NUMERIC(8,4),
    waterfall_priority              INTEGER,
    cumulative_principal_repaid_usd NUMERIC(18,2),
    interest_paid_current_period_usd NUMERIC(18,2),
    interest_accrued_usd            NUMERIC(18,2),
    rating_outlook                  VARCHAR(20),
    UNIQUE (fund_id, tranche_class)
);

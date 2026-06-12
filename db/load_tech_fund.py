"""
Load synthetic CLO data for DKIG Technology CLO 2019-I LLC into PostgreSQL.

Fund   : DKIG-2019-TECH
Vintage: March 2019  |  Size: $400M  |  Focus: Technology Sector Broadly Syndicated Loans
History: 29 quarterly performance snapshots — 2019-06-30 through 2026-05-29

Sector focus: Enterprise Software/SaaS, Cybersecurity, IT Services/MSP,
              Cloud Infrastructure & Data Centers, Fintech & Payments,
              Semiconductors & Hardware

Performance narrative:
  2019 Q2-Q4  Ramp-up; portfolio reaches full deployment; tech sector strong
  2020 Q1     COVID shock; tech loans sold off (-18% NAV); digital-infra names
               recover faster than broader market
  2020 Q2-Q4  Tech rebound (WFH/cloud demand); NAV exceeds pre-COVID levels
  2021        Peak tech valuations; distributions accelerate; strong equity returns
  2022        Fed rate-hike cycle; tech multiple compression; CCC bucket rises
               to 4.5% but income surges as SOFR hits 4.5%
  2023        Rates peak at 5.33%; high interest income; some credit stress in
               lower-rated names; WARF stable; reinvestment period continues
  2024        Reinvestment period ends Mar 2024; amortisation begins; principal
               proceeds directed to Class A repayment
  2025-2026   Continued amortisation; Class A significantly paid down;
               OC cushions increase; equity distributions sustained

Run:  python -m db.load_tech_fund
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2  # noqa: E402

DSN = os.environ.get("DATABASE_URL", "host=/tmp port=5432 dbname=postgres")
FUND_ID = "DKIG-2019-TECH"
REPORTING_DATE = "2026-05-29"
_EQ_INITIAL = 24_000_000
_INITIAL_PORTFOLIO_NAV = 388_000_000


# ── DP-01  Fund Static Profile ────────────────────────────────────────────────

DP01_ROWS = [
    ("Fund ID",                                   FUND_ID),
    ("Fund Name",                                 "DKIG Technology CLO 2019-I LLC"),
    ("CUSIP / ISIN",                              "17325TAA1 / US17325TAA18"),
    ("Manager Name",                              "DKIG Asset Management LLC"),
    ("Trustee",                                   "U.S. Bank Trust Company, N.A."),
    ("Vintage Year",                              2019),
    ("Closing Date",                              "2019-03-22"),
    ("Reinvestment Period End",                   "2024-03-22"),
    ("Non-Call Period End",                       "2021-03-22"),
    ("Legal Final Maturity",                      "2032-03-22"),
    ("Target Collateral Type",                    "Senior Secured Broadly Syndicated Loans — Technology Sector"),
    ("Governing Law",                             "State of New York"),
    ("Base Currency",                             "USD"),
    ("Senior Management Fee Rate (% p.a.)",       0.0015),
    ("Subordinated Management Fee Rate (% p.a.)", 0.0025),
    ("Incentive Fee Hurdle (IRR %)",              0.12),
    ("Incentive Fee Catch-up",                    0.20),
    ("Target Par Amount (USD)",                   400_000_000),
    ("Sector Focus",                              "Technology: Enterprise Software, SaaS, Cybersecurity, IT Services, Cloud, Fintech, Semiconductors"),
    ("Portfolio Concentration Limit",             "No single industry > 35%; No single obligor > 10%"),
    ("CCC/Caa Bucket Limit",                      "7.5% of Collateral Par"),
    ("WARF Covenant",                             "2,850 maximum"),
    ("Diversity Score Minimum",                   "35"),
    ("Status",                                    "Amortising (reinvestment period ended 2024-03-22)"),
    ("As Of Date",                                REPORTING_DATE),
]


# ── DP-08  Liability Structure ─────────────────────────────────────────────────
# $400M: 60% A / 10% B / 7% C / 6% D / 5% E / 6% Sub Notes / 6% Equity
# Class A has been amortising since March 2024; $78M repaid by 2026-05-29.

DP08_ROWS = [
    # class       cusip        init_notl    cur_notl   type     bps  freq
    # mdy   sp    fitch  sub%   oc_cush  ic_cush  pri  cum_repaid   int_paid    int_accrued  outlook
    ("A",   "17325TAB9", 240_000_000, 162_000_000, "Floating", 135, "Quarterly",
     "Aaa", "AAA", "AAA",  40.0, 19.8, 52.4, 1,  78_000_000, 1_915_650, 1_241_640, "Stable"),
    ("B",   "17325TAC7",  40_000_000,  40_000_000, "Floating", 185, "Quarterly",
     "Aa2",  "AA",  "AA",  30.0, 19.8, 52.4, 2,           0,   523_000,   340_000, "Stable"),
    ("C",   "17325TAD5",  28_000_000,  28_000_000, "Floating", 250, "Quarterly",
      "A2",   "A",   "A",  23.0, 16.0, 43.2, 3,           0,   411_600,   268_520, "Stable"),
    ("D",   "17325TAE3",  24_000_000,  24_000_000, "Floating", 325, "Quarterly",
     "Baa3","BBB-","BBB-", 17.0, 14.3, 32.8, 4,           0,   397_800,   260_000, "Stable"),
    ("E",   "17325TAF0",  20_000_000,  20_000_000, "Floating", 615, "Quarterly",
      "Ba3",  "BB-", "BB-", 12.0, 13.3, 25.2, 5,           0,   476_500,   313_267, "Negative"),
    ("Sub Notes", "17325TAG8", 24_000_000, 24_000_000, "Residual", 0, "Quarterly",
       "NR",   "NR",  "NR",  6.0,  None,  None, 6,          0,   280_000,   183_000, "NR"),
    ("Equity",    "17325TAH6", 24_000_000, 24_000_000, "Residual", 0, "Quarterly",
       "NR",   "NR",  "NR",  0.0,  None,  None, 7,          0,         0,         0, "NR"),
]


# ── DP-02  Portfolio Snapshot — 30 tech BSL positions as of 2026-05-29 ─────────
# Total par ~$376M across 6 technology sub-sectors.
# Two stressed positions (Caa1): Alteryx (~data analytics), Rackspace (cloud).
# 26 of 30 positions are covenant-lite (86.7%).

DP02_ROWS = [
    # ── Enterprise Software & SaaS (8 positions, ~$94M par) ─────────────────
    # pos_id  obligor                       cusip          industry                        cty  type     par        mktval   price  sprd   maturity        mdy    sp     fitch   pik lbo cov  dpd
    ("P0001", "Mimecast Holdings LLC",      "60282XAA4", "Technology: Enterprise Software", "USA", "1st Lien",
     12_000_000, 11_340_000,  94.50, 365, "2029-08-15", "B2",   "B",    "B",    "N", "Y", "Y", 0),
    ("P0002", "Ping Identity Corp.",        "72343FAA8", "Technology: Enterprise Software", "USA", "1st Lien",
     11_000_000, 10_230_000,  93.00, 375, "2028-11-30", "B2",   "B-",   "B",    "N", "Y", "Y", 0),
    ("P0003", "Informatica LLC",            "45670BAA2", "Technology: Enterprise Software", "USA", "1st Lien",
     13_000_000, 12_480_000,  96.00, 325, "2030-02-20", "B1",   "B+",   "B+",   "N", "Y", "Y", 0),
    ("P0004", "Datto Holdings Inc.",        "23812CAA5", "Technology: Enterprise Software", "USA", "1st Lien",
     12_000_000, 11_280_000,  94.00, 355, "2029-06-15", "B2",   "B",    "B",    "N", "Y", "Y", 0),
    ("P0005", "Alteryx Inc.",               "02136BAA9", "Technology: Enterprise Software", "USA", "1st Lien",
      9_000_000,  7_155_000,  79.50, 565, "2028-03-01", "Caa1", "CCC+", "CCC",  "Y", "Y", "Y", 0),
    ("P0006", "Verint Systems Inc.",        "92343LAA6", "Technology: Enterprise Software", "USA", "1st Lien",
     13_000_000, 12_545_000,  96.50, 310, "2030-09-12", "B1",   "B+",   "B+",   "N", "Y", "Y", 0),
    ("P0007", "Hyland Software Inc.",       "44832TAA3", "Technology: Enterprise Software", "USA", "1st Lien",
     12_000_000, 11_220_000,  93.50, 360, "2029-07-22", "B2",   "B",    "B",    "N", "Y", "Y", 0),
    ("P0008", "Compuware Corp.",            "20588CAA7", "Technology: Enterprise Software", "USA", "1st Lien",
     12_000_000, 11_040_000,  92.00, 385, "2028-10-18", "B2",   "B-",   "B",    "N", "Y", "Y", 0),
    # ── Cybersecurity (5 positions, ~$64M par) ──────────────────────────────
    ("P0009", "Optiv Security Inc.",        "68402RAA1", "Technology: Cybersecurity",       "USA", "1st Lien",
     13_000_000, 12_090_000,  93.00, 375, "2029-01-15", "B2",   "B",    "B",    "N", "Y", "Y", 0),
    ("P0010", "Entrust Holdings Inc.",      "29380TAA8", "Technology: Cybersecurity",       "USA", "1st Lien",
     14_000_000, 13_440_000,  96.00, 320, "2030-05-28", "B1",   "B+",   "B+",   "N", "Y", "Y", 0),
    ("P0011", "Telos Corp.",                "87962BAA4", "Technology: Cybersecurity",       "USA", "1st Lien",
     11_000_000,  9_680_000,  88.00, 450, "2028-09-30", "B3",   "B-",   "B-",   "N", "Y", "Y", 0),
    ("P0012", "Veracode Inc.",              "92341LAA2", "Technology: Cybersecurity",       "USA", "1st Lien",
     14_000_000, 13_510_000,  96.50, 315, "2030-04-10", "B1",   "B+",   "B+",   "N", "Y", "Y", 0),
    ("P0013", "SailPoint Technologies LLC","78612PAA5", "Technology: Cybersecurity",       "USA", "1st Lien",
     12_000_000, 11_700_000,  97.50, 275, "2030-08-15", "Ba3",  "BB-",  "BB-",  "N", "Y", "Y", 0),
    # ── IT Services & Managed Services (6 positions, ~$75M par) ─────────────
    ("P0014", "Presidio LLC",               "74064WAA3", "Technology: IT Services",         "USA", "1st Lien",
     14_000_000, 13_090_000,  93.50, 360, "2029-03-15", "B2",   "B",    "B",    "N", "Y", "Y", 0),
    ("P0015", "Ahead LLC",                  "00810TAA6", "Technology: IT Services",         "USA", "1st Lien",
     13_000_000, 12_090_000,  93.00, 370, "2029-05-20", "B2",   "B",    "B-",   "N", "Y", "Y", 0),
    ("P0016", "Sirius Computer Solutions", "82908FAA2", "Technology: IT Services",         "USA", "1st Lien",
     13_000_000, 12_220_000,  94.00, 355, "2029-08-30", "B2",   "B",    "B",    "N", "Y", "Y", 0),
    ("P0017", "Logicalis US Inc.",          "54081TAA9", "Technology: IT Services",         "USA", "1st Lien",
     11_000_000,  9_790_000,  89.00, 435, "2028-11-15", "B3",   "B-",   "B-",   "N", "Y", "Y", 0),
    ("P0018", "Trace3 LLC",                 "89237TAA7", "Technology: IT Services",         "USA", "1st Lien",
     11_000_000,  9_735_000,  88.50, 445, "2028-07-10", "B3",   "B-",   "B-",   "N", "Y", "Y", 0),
    ("P0019", "Computacenter Holdings LLC","20633TAA4", "Technology: IT Services",         "USA", "1st Lien",
     13_000_000, 12_610_000,  97.00, 300, "2030-06-15", "B1",   "B+",   "B+",   "N", "Y", "Y", 0),
    # ── Cloud Infrastructure & Data Centers (4 positions, ~$56M par) ─────────
    ("P0020", "Rackspace Technology Inc.", "75010TAA8", "Technology: Cloud Infrastructure", "USA", "1st Lien",
     10_000_000,  7_800_000,  78.00, 550, "2028-05-15", "Caa1", "CCC+", "CCC-", "Y", "Y", "Y", 0),
    ("P0021", "QTS Data Centers LLC",      "74736TAA2", "Technology: Cloud Infrastructure", "USA", "1st Lien",
     16_000_000, 15_840_000,  99.00, 220, "2031-01-20", "Ba2",  "BB",   "BB",   "N", "N", "Y", 0),
    ("P0022", "Cyxtera Technologies LLC",  "23248TAA6", "Technology: Cloud Infrastructure", "USA", "1st Lien",
     14_000_000, 12_390_000,  88.50, 425, "2029-03-25", "B3",   "B-",   "B-",   "N", "Y", "Y", 0),
    ("P0023", "Sungard Availability LLC",  "86749TAA1", "Technology: Cloud Infrastructure", "USA", "1st Lien",
     16_000_000, 14_960_000,  93.50, 355, "2030-07-08", "B2",   "B",    "B",    "N", "Y", "Y", 0),
    # ── Fintech & Payments (4 positions, ~$53M par) ──────────────────────────
    ("P0024", "WEX Inc.",                   "92937TAA3", "Technology: Fintech & Payments",  "USA", "1st Lien",
     15_000_000, 14_700_000,  98.00, 265, "2030-04-15", "Ba3",  "BB-",  "BB-",  "N", "N", "N", 0),
    ("P0025", "NCR Atleos LLC",             "62889TAA4", "Technology: Fintech & Payments",  "USA", "1st Lien",
     14_000_000, 13_020_000,  93.00, 365, "2029-09-28", "B2",   "B",    "B",    "N", "Y", "Y", 0),
    ("P0026", "Blucora Inc.",               "09588TAA8", "Technology: Fintech & Payments",  "USA", "1st Lien",
     12_000_000, 11_100_000,  92.50, 380, "2028-12-15", "B2",   "B",    "B-",   "N", "Y", "Y", 0),
    ("P0027", "Jack Henry & Assoc. LLC",   "42682TAA5", "Technology: Fintech & Payments",  "USA", "1st Lien",
     12_000_000, 11_820_000,  98.50, 235, "2031-03-10", "Ba2",  "BB+",  "BB+",  "N", "N", "N", 0),
    # ── Semiconductors & Hardware (3 positions, ~$34M par) ───────────────────
    ("P0028", "Benchmark Electronics LLC", "08172TAA3", "Technology: Semiconductors",      "USA", "1st Lien",
     12_000_000, 11_580_000,  96.50, 310, "2030-02-15", "B1",   "B+",   "B+",   "N", "Y", "N", 0),
    ("P0029", "Knowles Corp.",              "49926TAA7", "Technology: Semiconductors",      "USA", "1st Lien",
     12_000_000, 11_760_000,  98.00, 260, "2030-10-20", "Ba3",  "BB-",  "BB-",  "N", "N", "N", 0),
    ("P0030", "Coherent Corp.",             "19247TAA6", "Technology: Semiconductors",      "USA", "1st Lien",
     10_000_000,  9_700_000,  97.00, 300, "2029-11-08", "B1",   "B+",   "B+",   "N", "Y", "N", 0),
]


# ── DP-03 & DP-07  Quarterly Performance and Key Metrics ─────────────────────
# 29 quarters: 2019-Q2 (Jun) through 2026-Q2 partial (May 29).

_QUARTERLY_DATES = [
    (2019, 6, 30), (2019, 9, 30), (2019, 12, 31),
    (2020, 3, 31), (2020, 6, 30), (2020, 9, 30), (2020, 12, 31),
    (2021, 3, 31), (2021, 6, 30), (2021, 9, 30), (2021, 12, 31),
    (2022, 3, 31), (2022, 6, 30), (2022, 9, 30), (2022, 12, 31),
    (2023, 3, 31), (2023, 6, 30), (2023, 9, 30), (2023, 12, 31),
    (2024, 3, 31), (2024, 6, 30), (2024, 9, 30), (2024, 12, 31),
    (2025, 3, 31), (2025, 6, 30), (2025, 9, 30), (2025, 12, 31),
    (2026, 3, 31), (2026, 5, 29),
]


def _build_dp03() -> list[tuple]:
    # (y, m) → (total_fund_nav, gross_irr, dpi, qtr_interest, benchmark_return)
    # equity_nav is derived as total_fund_nav − debt_notional_at_quarter (see _DEBT
    # below) so that the balance-sheet identity NAV = Debt + Equity holds exactly.
    # dpi: cumulative distributions-to-paid-in (equity capital = $24M)
    # benchmark_return: US Leveraged Loan Index annualised return (decimal)
    _perf: dict[tuple, tuple] = {
        # 2019 — ramp-up; tech sector strong; SOFR declining from 2.4% to 1.7%
        (2019, 6):  (390_000_000, 0.018, 0.000,  6_000_000, 0.058),
        (2019, 9):  (393_000_000, 0.048, 0.000,  6_100_000, 0.062),
        (2019, 12): (395_500_000, 0.072, 0.048,  5_800_000, 0.065),
        # 2020 — COVID shock in Q1; tech digital-acceleration recovery Q2-Q4
        (2020, 3):  (325_000_000, 0.052, 0.048,  4_900_000, 0.040),
        (2020, 6):  (352_000_000, 0.062, 0.048,  3_800_000, 0.045),
        (2020, 9):  (378_000_000, 0.082, 0.048,  3_700_000, 0.052),
        (2020, 12): (398_000_000, 0.102, 0.102,  3_700_000, 0.060),
        # 2021 — tech boom; peak valuations; SOFR ~0.05%
        (2021, 3):  (404_000_000, 0.108, 0.102,  3_700_000, 0.062),
        (2021, 6):  (408_000_000, 0.112, 0.158,  3_700_000, 0.064),
        (2021, 9):  (410_000_000, 0.115, 0.158,  3_700_000, 0.065),
        (2021, 12): (412_000_000, 0.118, 0.218,  3_700_000, 0.066),
        # 2022 — Fed rate-hike cycle; tech multiple compression; income surge
        (2022, 3):  (405_000_000, 0.116, 0.218,  4_500_000, 0.066),
        (2022, 6):  (392_000_000, 0.113, 0.218,  6_200_000, 0.066),
        (2022, 9):  (388_000_000, 0.112, 0.278,  8_100_000, 0.066),
        (2022, 12): (391_000_000, 0.113, 0.345,  9_500_000, 0.067),
        # 2023 — SOFR peak ~5.33%; high income; credit broadly stable
        (2023, 3):  (395_000_000, 0.114, 0.345,  9_800_000, 0.070),
        (2023, 6):  (397_000_000, 0.115, 0.418,  9_900_000, 0.071),
        (2023, 9):  (399_000_000, 0.116, 0.418,  9_900_000, 0.072),
        (2023, 12): (401_000_000, 0.117, 0.490, 10_000_000, 0.073),
        # 2024 — reinvestment ends Mar 2024; Class A amortisation begins Jun 2024
        (2024, 3):  (399_000_000, 0.117, 0.490,  9_800_000, 0.072),
        (2024, 6):  (396_000_000, 0.117, 0.575,  9_500_000, 0.072),
        (2024, 9):  (392_000_000, 0.118, 0.575,  9_100_000, 0.071),
        (2024, 12): (388_000_000, 0.118, 0.665,  8_700_000, 0.071),
        # 2025 — rate cuts; equity NAV grows rapidly as Class A is paid down
        (2025, 3):  (384_000_000, 0.118, 0.665,  8_400_000, 0.070),
        (2025, 6):  (380_000_000, 0.119, 0.758,  8_100_000, 0.070),
        (2025, 9):  (376_000_000, 0.119, 0.758,  7_800_000, 0.069),
        (2025, 12): (372_000_000, 0.119, 0.858,  7_400_000, 0.069),
        # 2026 — continued amortisation; near end-of-life for first-vintage loans
        (2026, 3):  (368_000_000, 0.119, 0.858,  7_100_000, 0.068),
        (2026, 5):  (366_000_000, 0.119, 0.948,  4_800_000, 0.067),
    }

    # Debt notional at each reporting date (A+B+C+D+E+Sub Notes, excl. Equity).
    # Class A is the only amortising tranche; B–E and Sub Notes are bullet.
    # equity_nav = total_fund_nav − debt_notional, ensuring NAV = Debt + Equity.
    #
    # Amortisation schedule (Class A only, starting Jun 2024):
    #   Jun–Dec 2024, Mar 2025: −$11.25M/quarter (first four payments, $45M total)
    #   Jun 2025 – Mar 2026:   per DP-05 cashflows ($9M / $8.5M / $8M / $7.5M)
    #   May 2026 (partial):     no payment between Mar and May reporting dates
    #   Cumulative repaid by May 2026: $78M → Class A = $162M  (matches DP-08 ✓)
    _DEBT: dict[tuple, int] = {
        (2019,  6): 376_000_000, (2019,  9): 376_000_000, (2019, 12): 376_000_000,
        (2020,  3): 376_000_000, (2020,  6): 376_000_000, (2020,  9): 376_000_000,
        (2020, 12): 376_000_000,
        (2021,  3): 376_000_000, (2021,  6): 376_000_000, (2021,  9): 376_000_000,
        (2021, 12): 376_000_000,
        (2022,  3): 376_000_000, (2022,  6): 376_000_000, (2022,  9): 376_000_000,
        (2022, 12): 376_000_000,
        (2023,  3): 376_000_000, (2023,  6): 376_000_000, (2023,  9): 376_000_000,
        (2023, 12): 376_000_000,
        (2024,  3): 376_000_000,   # reinvestment ends; first payment in Jun 2024
        (2024,  6): 364_750_000,   # Class A = $228.75M  (−$11.25M)
        (2024,  9): 353_500_000,   # Class A = $217.50M  (−$11.25M)
        (2024, 12): 342_250_000,   # Class A = $206.25M  (−$11.25M)
        (2025,  3): 331_000_000,   # Class A = $195.00M  (−$11.25M)
        (2025,  6): 322_000_000,   # Class A = $186.00M  (− $9.00M, from DP-05)
        (2025,  9): 313_500_000,   # Class A = $177.50M  (− $8.50M)
        (2025, 12): 305_500_000,   # Class A = $169.50M  (− $8.00M)
        (2026,  3): 298_000_000,   # Class A = $162.00M  (− $7.50M) ← matches DP-08 ✓
        (2026,  5): 298_000_000,   # no payment between Mar and May reporting dates
    }

    # Cumulative realised G/L — small gains early, COVID losses in 2020,
    # recovery 2021, rate-hike stress 2022, net positive by 2023-2026
    _realised: dict[tuple, int] = {
        (2019, 6): 180_000,   (2019, 9): 360_000,   (2019, 12): 540_000,
        (2020, 3): -1_800_000, (2020, 6): -3_200_000, (2020, 9): -2_800_000, (2020, 12): -1_900_000,
        (2021, 3): -800_000,  (2021, 6): 400_000,   (2021, 9): 1_200_000,  (2021, 12): 2_100_000,
        (2022, 3): 2_800_000, (2022, 6): 2_200_000, (2022, 9): 1_500_000,  (2022, 12): 900_000,
        (2023, 3): 1_200_000, (2023, 6): 1_800_000, (2023, 9): 2_500_000,  (2023, 12): 3_300_000,
        (2024, 3): 3_800_000, (2024, 6): 4_200_000, (2024, 9): 4_500_000,  (2024, 12): 4_200_000,
        (2025, 3): 3_800_000, (2025, 6): 3_500_000, (2025, 9): 3_200_000,  (2025, 12): 2_900_000,
        (2026, 3): 2_600_000, (2026, 5): 2_800_000,
    }

    rows = []
    cum_interest = 0
    prev_nav = None
    prev_dpi = 0.0

    for y, m, d in _QUARTERLY_DATES:
        rdate = f"{y:04d}-{m:02d}-{d:02d}"
        nav, g_irr, dpi, qtr_int, bench = _perf[(y, m)]
        eq_nav = nav - _DEBT[(y, m)]          # balance-sheet residual: NAV − Debt
        n_irr  = round(max(g_irr - 0.015, 0.0), 4)
        rvpi   = round(eq_nav / _EQ_INITIAL, 4)
        tvpi   = round(dpi + rvpi, 4)

        cum_interest += qtr_int
        dist_this_period = (dpi - prev_dpi) * _EQ_INITIAL

        if prev_nav is None:
            period_pl   = nav - _INITIAL_PORTFOLIO_NAV
        else:
            period_pl   = (nav - prev_nav) + dist_this_period

        unrealised  = nav - _INITIAL_PORTFOLIO_NAV + dpi * _EQ_INITIAL
        realised_gl = _realised[(y, m)]
        itd_pl      = nav - _INITIAL_PORTFOLIO_NAV + dpi * _EQ_INITIAL
        excess      = round(g_irr - bench, 4)

        rows.append((
            rdate, nav, eq_nav,
            round(g_irr, 4), n_irr,
            round(dpi, 3), round(rvpi, 3), round(tvpi, 3),
            int(itd_pl), int(period_pl),
            int(unrealised), realised_gl,
            cum_interest,
            round(bench, 4), excess,
        ))
        prev_nav = nav
        prev_dpi = dpi

    return rows


DP03_ROWS = _build_dp03()


# ── DP-04  Compliance Dashboard — current state as of 2026-05-29 ──────────────
# All tests passing. OC cushions are elevated post-amortisation as Class A
# notional ($162M) is well below initial ($240M), widening the OC ratio.

DP04_ROWS = [
    # OC tests: ratio = eligible collateral par / covered tranche notional
    # Class A repaid $78M → OC-A denominator shrunk → large cushion
    ("OC-A", "Class A/B OC Test",         "OC",          "A/B",   1.428, 1.230, 0.198, "PASS",
     "Divert principal & interest to repay Class A until test cures",   REPORTING_DATE),
    ("OC-C", "Class C OC Test",           "OC",          "C",     1.325, 1.165, 0.160, "PASS",
     "Divert proceeds to repay senior tranches in waterfall priority",  REPORTING_DATE),
    ("OC-D", "Class D OC Test",           "OC",          "D",     1.248, 1.105, 0.143, "PASS",
     "Divert proceeds to repay senior tranches in priority order",      REPORTING_DATE),
    ("OC-E", "Class E OC Test",           "OC",          "E",     1.188, 1.055, 0.133, "PASS",
     "Divert proceeds to repay senior tranches in priority order",      REPORTING_DATE),
    # IC tests: interest income / interest payable on covered tranches
    ("IC-A", "Class A/B IC Test",         "IC",          "A/B",   2.258, 1.200, 1.058, "PASS",
     "Divert proceeds to repay Class A principal if breached",          REPORTING_DATE),
    ("IC-C", "Class C IC Test",           "IC",          "C",     2.015, 1.150, 0.865, "PASS",
     "Divert proceeds to repay senior tranches",                        REPORTING_DATE),
    ("IC-D", "Class D IC Test",           "IC",          "D",     1.812, 1.105, 0.707, "PASS",
     "Divert proceeds to repay senior tranches",                        REPORTING_DATE),
    ("IC-E", "Class E IC Test",           "IC",          "E",     1.628, 1.085, 0.543, "PASS",
     "Divert proceeds to repay senior tranches",                        REPORTING_DATE),
    # Quality tests
    ("WARF", "Moody's WARF Covenant",     "Quality",     "Fund",  2582,  2850,  268,   "PASS",
     "Trading restrictions; tighter eligible asset criteria",           REPORTING_DATE),
    ("DIV",  "Moody's Diversity Score",   "Quality",     "Fund",  41.5,  35.0,    6.5, "PASS",
     "Trading restrictions if score falls below 35",                    REPORTING_DATE),
    # Concentration tests
    ("CCC",  "CCC/Caa Bucket %",          "Concentration","Fund",  0.058, 0.075, 0.017, "PASS",
     "Excess CCC assets haircut to market value in OC test calculation",REPORTING_DATE),
    ("OBL",  "Largest Single Obligor %",  "Concentration","Fund",  0.043, 0.100, 0.057, "PASS",
     "Trading restrictions until cured; new purchase ineligibility",    REPORTING_DATE),
    ("IND",  "Largest Single Industry %", "Concentration","Fund",  0.253, 0.350, 0.097, "PASS",
     "Sector concentration limit; trading restrictions if breached",    REPORTING_DATE),
    ("PIK",  "DIP/PIK Loan %",            "Concentration","Fund",  0.028, 0.075, 0.047, "PASS",
     "Excess treated as defaulted for OC test purposes",                REPORTING_DATE),
]


# ── DP-05  Cashflows — last 4 quarterly waterfall payments ───────────────────
# Payment dates: Jun / Sep / Dec 2025, Mar 2026
# Class A current notional: $162M (post-amortisation)
# Debt interest at SOFR ~4.1% / 3.84% / 3.62% / 3.38% for respective quarters

def _tech_waterfall(
    payment_date: str,
    collection_period: str,
    interest: int,
    principal: int,
    equity_dist: int,
    mgmt_fee: int,
    trustee_fee: int,
) -> list[tuple]:
    a_int     = int(162_000_000 * 0.0545 / 4)   # Class A: SOFR+135bps ≈ 5.45%/4
    bcde_int  = (
        int(40_000_000  * 0.0585 / 4) +          # B: SOFR+185bps
        int(28_000_000  * 0.0650 / 4) +           # C: SOFR+250bps
        int(24_000_000  * 0.0725 / 4) +           # D: SOFR+325bps
        int(20_000_000  * 0.1015 / 4)             # E: SOFR+615bps
    )
    sub_int   = 300_000
    base      = (payment_date, collection_period, interest, principal, 0, 0)
    return [
        (*base, "1. Senior Expenses",            "Trustee + Rating Agency + Admin",   trustee_fee + 28_000,    0, 0,          0, 0,            trustee_fee),
        (*base, "2. Class A Interest",           "Class A Tranche",                   a_int,                   0, 0,          0, 0,            0),
        (*base, "3. Class A OC Test",            "Test passes — no diversion",        0,                       0, 0,          0, 0,            0),
        (*base, "4. Class A IC Test",            "Test passes — no diversion",        0,                       0, 0,          0, 0,            0),
        (*base, "5. Class B–E Interest & Tests", "Class B/C/D/E Tranches",            bcde_int,                0, 0,          0, 0,            0),
        (*base, "6. Senior Management Fee",      "DKIG Asset Management",             int(mgmt_fee * 0.375),   0, 0,          int(mgmt_fee * 0.375), 0, 0),
        (*base, "7. Subordinated Notes Interest","Sub Notes Holders",                 sub_int,                 0, 0,          0, 0,            0),
        (*base, "8. Incentive Fee / Sub Mgmt Fee","DKIG Asset Management",            int(mgmt_fee * 0.625),   0, 0,          int(mgmt_fee * 0.625), 0, 0),
        (*base, "9. Equity Distribution",        "Preference Shareholders (Equity)",  equity_dist,             0, equity_dist,0, 0,            0),
    ]


DP05_ROWS: list[tuple] = []
DP05_ROWS += _tech_waterfall(
    "2025-06-20", "2025-03-20 → 2025-06-20",
    interest=7_200_000, principal=9_000_000, equity_dist=2_100_000,
    mgmt_fee=400_000, trustee_fee=50_000,
)
DP05_ROWS += _tech_waterfall(
    "2025-09-20", "2025-06-20 → 2025-09-20",
    interest=7_000_000, principal=8_500_000, equity_dist=2_000_000,
    mgmt_fee=400_000, trustee_fee=50_000,
)
DP05_ROWS += _tech_waterfall(
    "2025-12-20", "2025-09-20 → 2025-12-20",
    interest=6_800_000, principal=8_000_000, equity_dist=1_900_000,
    mgmt_fee=400_000, trustee_fee=50_000,
)
DP05_ROWS += _tech_waterfall(
    "2026-03-20", "2025-12-20 → 2026-03-20",
    interest=6_600_000, principal=7_500_000, equity_dist=1_800_000,
    mgmt_fee=400_000, trustee_fee=50_000,
)


# ── DP-06  Fee & Expense Ledger — 2026 Q1 (Jan–Mar 2026) ─────────────────────
# Cumulative fees approximate 7 years of accrual (2019-2026).

DP06_ROWS = [
    ("2026 Q1", "Management Fee — Senior",       "0.15% p.a.",       150_000,  150_000,  150_000,  4_200_000, None, None,   None,    None,   None),
    ("2026 Q1", "Management Fee — Subordinated", "0.25% p.a.",       250_000,  250_000,  250_000,  7_000_000, None, None,   None,    None,   None),
    ("2026 Q1", "Incentive Fee",                 "20% above 12% IRR",      0,        0,        0,          0, 0.12, 0.20,   None,    None,   None),
    ("2026 Q1", "Trustee Fee",                   "USD 200,000 p.a.",  50_000,   50_000,   50_000,  1_400_000, None, None,   None,    None,   None),
    ("2026 Q1", "Admin / Accounting Fee",        "USD 90,000 p.a.",   22_500,   22_500,   22_500,    630_000, None, None,   None,    None,   None),
    ("2026 Q1", "Legal Fee",                     "Variable",          30_000,   30_000,   22_500,    385_000, None, None,   None,    None,   None),
    ("2026 Q1", "Rating Agency Fee",             "USD 200,000 p.a.",  50_000,   50_000,   50_000,  1_400_000, None, None,   None,    None,   None),
    ("2026 Q1", "Tax Provision",                 "Effective",              0,        0,        0,          0, None, None, 220_000,  0.0180, None),
    ("2026 YTD","Total Expense Ratio (TER)",     "Aggregate",        552_500,  552_500,  494_500, 15_015_000, None, None, 220_000,  0.0180, 0.0095),
]


# ── DP-07  Key Metrics — 29 quarterly snapshots ────────────────────────────────
# Technology CLO characteristics:
#   WAS ~365-395 bps — higher than diversified CLO (sector concentration premium)
#   WARF ~2430-2690 (B1/B2 avg; some Ba2-Ba3 anchors in fintech/cloud)
#   WAL: starts ~6.5 yrs, declines steadily as loans amortise
#   Diversity score ~38-42 (concentrated: 6 tech sub-industries, ~30-35 obligors)
#   % CCC: 0% initially, spikes to 6.2% in COVID, stabilises ~5.8% by 2026
#   % PIK: 0% initially, rises to 2.8% as two names become PIK
#   % Covenant-lite: ~82-87% (tech companies prefer cov-lite structures)

def _build_dp07() -> list[tuple]:
    # (y, m) → (was, warf, wal, wac, warr, par_build,
    #            pct_float, pct_fixed, pct_pik, pct_ccc,
    #            pct_cov_lite, div_score, n_obl, n_ind,
    #            lg_obl, lg_ind, top10)
    # wac is (SOFR + WAS) / 100 expressed as decimal (e.g. 0.0622)
    _metrics: dict[tuple, tuple] = {
        # 2019: ramp-up; SOFR 2.4% → 1.7%
        (2019, 6):  (382, 2430, 6.5, 0.0622, 0.57,  -2_000_000, 1.00, 0.00, 0.000, 0.008, 0.82, 38.0, 32, 6, 0.042, 0.310, 0.372),
        (2019, 9):  (385, 2445, 6.3, 0.0603, 0.57,   1_500_000, 1.00, 0.00, 0.000, 0.010, 0.83, 38.5, 33, 6, 0.041, 0.308, 0.370),
        (2019, 12): (388, 2448, 6.1, 0.0561, 0.57,   3_500_000, 1.00, 0.00, 0.000, 0.010, 0.83, 39.0, 34, 6, 0.040, 0.308, 0.368),
        # 2020: COVID — spreads widen, WARF spikes, CCC surges, PIK rises
        (2020, 3):  (398, 2680, 5.8, 0.0508, 0.55, -18_000_000, 1.00, 0.00, 0.028, 0.062, 0.83, 37.0, 34, 6, 0.043, 0.312, 0.378),
        (2020, 6):  (392, 2620, 5.6, 0.0401, 0.56, -12_000_000, 1.00, 0.00, 0.022, 0.048, 0.83, 37.5, 34, 6, 0.042, 0.310, 0.375),
        (2020, 9):  (390, 2580, 5.4, 0.0399, 0.56,  -2_000_000, 1.00, 0.00, 0.016, 0.035, 0.83, 38.0, 34, 6, 0.041, 0.308, 0.372),
        (2020, 12): (388, 2548, 5.2, 0.0397, 0.57,   1_500_000, 1.00, 0.00, 0.012, 0.025, 0.83, 38.5, 34, 6, 0.041, 0.308, 0.370),
        # 2021: tech boom; SOFR ~0.05%; WARF declines as ratings improve
        (2021, 3):  (386, 2530, 5.0, 0.0391, 0.57,   3_000_000, 1.00, 0.00, 0.010, 0.020, 0.83, 39.0, 34, 6, 0.040, 0.306, 0.368),
        (2021, 6):  (384, 2515, 4.8, 0.0389, 0.57,   5_000_000, 1.00, 0.00, 0.010, 0.018, 0.84, 39.5, 35, 6, 0.040, 0.305, 0.365),
        (2021, 9):  (383, 2508, 4.6, 0.0388, 0.57,   6_000_000, 1.00, 0.00, 0.010, 0.018, 0.84, 40.0, 35, 6, 0.040, 0.304, 0.364),
        (2021, 12): (382, 2500, 4.4, 0.0387, 0.57,   7_500_000, 1.00, 0.00, 0.012, 0.016, 0.84, 40.5, 35, 6, 0.040, 0.303, 0.363),
        # 2022: Fed rate hikes; SOFR 0.05% → 4.5%; tech selloff; CCC rises
        (2022, 3):  (375, 2510, 4.2, 0.0394, 0.57,   4_000_000, 1.00, 0.00, 0.014, 0.022, 0.84, 40.5, 35, 6, 0.040, 0.304, 0.364),
        (2022, 6):  (372, 2548, 4.0, 0.0520, 0.56,  -2_000_000, 1.00, 0.00, 0.018, 0.032, 0.84, 40.0, 35, 6, 0.041, 0.306, 0.366),
        (2022, 9):  (368, 2568, 3.8, 0.0663, 0.56,  -4_000_000, 1.00, 0.00, 0.022, 0.040, 0.84, 39.5, 35, 6, 0.041, 0.307, 0.367),
        (2022, 12): (365, 2575, 3.6, 0.0775, 0.56,  -5_000_000, 1.00, 0.00, 0.024, 0.045, 0.84, 39.5, 35, 6, 0.041, 0.308, 0.368),
        # 2023: SOFR peaks ~5.33%; income surges; credit broadly stable
        (2023, 3):  (363, 2570, 3.4, 0.0821, 0.56,  -4_500_000, 1.00, 0.00, 0.024, 0.042, 0.84, 40.0, 35, 6, 0.041, 0.307, 0.367),
        (2023, 6):  (362, 2565, 3.2, 0.0867, 0.56,  -3_000_000, 1.00, 0.00, 0.022, 0.040, 0.84, 40.5, 35, 6, 0.041, 0.306, 0.366),
        (2023, 9):  (361, 2560, 3.0, 0.0891, 0.56,  -2_000_000, 1.00, 0.00, 0.022, 0.038, 0.85, 41.0, 34, 6, 0.041, 0.305, 0.365),
        (2023, 12): (360, 2558, 2.8, 0.0893, 0.56,  -1_500_000, 1.00, 0.00, 0.020, 0.036, 0.85, 41.0, 34, 6, 0.041, 0.304, 0.364),
        # 2024: reinvestment ends; amortisation; portfolio shrinks
        (2024, 3):  (358, 2560, 2.6, 0.0888, 0.56,  -2_000_000, 1.00, 0.00, 0.020, 0.038, 0.85, 41.0, 33, 6, 0.041, 0.305, 0.364),
        (2024, 6):  (356, 2562, 2.4, 0.0885, 0.56,  -6_000_000, 1.00, 0.00, 0.022, 0.040, 0.85, 40.5, 32, 6, 0.042, 0.308, 0.366),
        (2024, 9):  (354, 2565, 2.3, 0.0865, 0.56,  -8_000_000, 1.00, 0.00, 0.024, 0.044, 0.85, 40.5, 32, 6, 0.042, 0.309, 0.367),
        (2024, 12): (353, 2568, 2.2, 0.0815, 0.57, -12_000_000, 1.00, 0.00, 0.026, 0.048, 0.85, 40.5, 31, 6, 0.042, 0.309, 0.368),
        # 2025: rate cuts; Class A ~40% paid down; WAL declining fast
        (2025, 3):  (352, 2572, 2.1, 0.0784, 0.57, -16_000_000, 1.00, 0.00, 0.026, 0.050, 0.85, 41.0, 31, 5, 0.042, 0.308, 0.368),
        (2025, 6):  (352, 2575, 2.0, 0.0761, 0.57, -18_000_000, 1.00, 0.00, 0.028, 0.052, 0.85, 41.0, 31, 5, 0.042, 0.308, 0.368),
        (2025, 9):  (352, 2578, 1.9, 0.0736, 0.57, -22_000_000, 1.00, 0.00, 0.028, 0.054, 0.85, 41.0, 30, 5, 0.042, 0.308, 0.368),
        (2025, 12): (352, 2580, 1.8, 0.0714, 0.57, -26_000_000, 1.00, 0.00, 0.028, 0.056, 0.85, 41.0, 30, 5, 0.042, 0.308, 0.368),
        # 2026: near end-of-life for 2019-vintage loans; WAL approaching 1.6 yrs
        (2026, 3):  (352, 2580, 1.7, 0.0690, 0.57, -28_500_000, 1.00, 0.00, 0.028, 0.058, 0.87, 41.5, 30, 5, 0.043, 0.308, 0.369),
        (2026, 5):  (352, 2582, 1.6, 0.0677, 0.57, -30_000_000, 1.00, 0.00, 0.028, 0.058, 0.87, 41.5, 30, 5, 0.043, 0.308, 0.369),
    }

    rows = []
    for y, m, d in _QUARTERLY_DATES:
        rdate = f"{y:04d}-{m:02d}-{d:02d}"
        was, warf, wal, wac, warr, pb, pf, px, ppik, pccc, pcl, ds, no, ni, lo, li, t10 = _metrics[(y, m)]
        rows.append((rdate, was, warf, wal, wac, warr, pb, pf, px, ppik, pccc, pcl, ds, no, ni, lo, li, t10))
    return rows


DP07_ROWS = _build_dp07()


# ── Database helpers ──────────────────────────────────────────────────────────

def connect() -> "psycopg2.extensions.connection":
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    return conn


def _val(v: object) -> str | None:
    return None if v is None else str(v)


def load_dp01(cur: Any, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp01_fund_static_profile WHERE fund_id = %s", (FUND_ID,))
    cur.executemany(
        "INSERT INTO dp01_fund_static_profile (fund_id, attribute, value) VALUES (%s,%s,%s) "
        "ON CONFLICT (fund_id, attribute) DO UPDATE SET value = EXCLUDED.value",
        [(FUND_ID, attr, _val(val)) for attr, val in rows],
    )


def load_dp02(cur: Any, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp02_portfolio_snapshot WHERE fund_id = %s", (FUND_ID,))
    cur.executemany(
        "INSERT INTO dp02_portfolio_snapshot "
        "(fund_id,position_id,obligor_name,facility_cusip,industry,country,loan_type,"
        "par_amount_usd,market_value_usd,price_pct_par,spread_sofr_bps,maturity_date,"
        "moodys_rating,sp_rating,fitch_rating,pik_flag,lbo_flag,covenant_lite_flag,days_past_due) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (fund_id, position_id) DO UPDATE SET "
        "obligor_name=EXCLUDED.obligor_name, market_value_usd=EXCLUDED.market_value_usd",
        [(FUND_ID,) + r for r in rows],
    )


def load_dp03(cur: Any, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp03_performance WHERE fund_id = %s", (FUND_ID,))
    cur.executemany(
        "INSERT INTO dp03_performance "
        "(fund_id,reporting_date,total_fund_nav_usd,equity_nav_usd,gross_irr_pct,net_irr_pct,"
        "dpi,rvpi,tvpi,itd_pl_usd,current_period_pl_usd,unrealised_gl_usd,realised_gl_usd,"
        "total_interest_income_usd,benchmark_return_pct,excess_return_pct) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (fund_id, reporting_date) DO UPDATE SET "
        "total_fund_nav_usd=EXCLUDED.total_fund_nav_usd, equity_nav_usd=EXCLUDED.equity_nav_usd",
        [(FUND_ID,) + r for r in rows],
    )


def load_dp04(cur: Any, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp04_compliance WHERE fund_id = %s", (FUND_ID,))
    cur.executemany(
        "INSERT INTO dp04_compliance "
        "(fund_id,test_id,test_name,test_type,tranche_class,current_value,threshold,cushion,"
        "pass_fail,breach_consequence,last_tested) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (fund_id, test_id) DO UPDATE SET "
        "current_value=EXCLUDED.current_value, pass_fail=EXCLUDED.pass_fail",
        [(FUND_ID,) + r for r in rows],
    )


def load_dp05(cur: Any, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp05_cashflows WHERE fund_id = %s", (FUND_ID,))
    cur.executemany(
        "INSERT INTO dp05_cashflows "
        "(fund_id,payment_date,collection_period,total_interest_proceeds_usd,"
        "total_principal_proceeds_usd,reinvestment_proceeds_usd,recoveries_usd,"
        "waterfall_step,recipient,amount_disbursed_usd,oc_diversion_amount_usd,"
        "equity_distribution_amount_usd,management_fee_paid_usd,incentive_fee_paid_usd,"
        "trustee_fee_paid_usd) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [(FUND_ID,) + r for r in rows],
    )


def load_dp06(cur: Any, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp06_fees WHERE fund_id = %s", (FUND_ID,))
    cur.executemany(
        "INSERT INTO dp06_fees "
        "(fund_id,period,fee_type,fee_rate_amount,accrued_ytd_usd,accrued_current_period_usd,"
        "amount_paid_current_period_usd,cumulative_amount_paid_usd,hurdle_rate_pct,catchup_pct,"
        "tax_provision_usd,effective_tax_rate_pct,total_expense_ratio_pct) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [(FUND_ID,) + r for r in rows],
    )


def load_dp07(cur: Any, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp07_key_metrics WHERE fund_id = %s", (FUND_ID,))
    cur.executemany(
        "INSERT INTO dp07_key_metrics "
        "(fund_id,reporting_date,was_bps_over_sofr,warf,wal_years,wac_pct,"
        "weighted_avg_recovery_rate_pct,par_build_loss_vs_target_usd,pct_floating_rate,"
        "pct_fixed_rate,pct_pik,pct_ccc_caa,pct_covenant_lite,diversity_score,"
        "number_of_obligors,number_of_industries,largest_single_obligor_pct,"
        "largest_single_industry_pct,top10_obligor_concentration_pct) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (fund_id, reporting_date) DO UPDATE SET "
        "warf=EXCLUDED.warf, was_bps_over_sofr=EXCLUDED.was_bps_over_sofr",
        [(FUND_ID,) + r for r in rows],
    )


def load_dp08(cur: Any, rows: list[tuple]) -> None:
    cur.execute("DELETE FROM dp08_liability_structure WHERE fund_id = %s", (FUND_ID,))
    cur.executemany(
        "INSERT INTO dp08_liability_structure "
        "(fund_id,tranche_class,cusip,initial_notional_usd,current_notional_usd,coupon_type,"
        "coupon_rate_sofr_bps,payment_frequency,moodys_rating,sp_rating,fitch_rating,"
        "subordination_level_pct,oc_cushion_pct,ic_cushion_pct,waterfall_priority,"
        "cumulative_principal_repaid_usd,interest_paid_current_period_usd,"
        "interest_accrued_usd,rating_outlook) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (fund_id, tranche_class) DO UPDATE SET "
        "current_notional_usd=EXCLUDED.current_notional_usd, "
        "cumulative_principal_repaid_usd=EXCLUDED.cumulative_principal_repaid_usd",
        [(FUND_ID,) + r for r in rows],
    )


def main() -> None:
    print(f"Connecting to PostgreSQL ({DSN})…")
    conn = connect()
    try:
        with conn.cursor() as cur:
            print(f"Loading {FUND_ID} — DP-01 (static profile, {len(DP01_ROWS)} attributes)…")
            load_dp01(cur, DP01_ROWS)
            print(f"Loading {FUND_ID} — DP-02 (portfolio snapshot, {len(DP02_ROWS)} positions)…")
            load_dp02(cur, DP02_ROWS)
            print(f"Loading {FUND_ID} — DP-03 (performance, {len(DP03_ROWS)} quarterly rows)…")
            load_dp03(cur, DP03_ROWS)
            print(f"Loading {FUND_ID} — DP-04 (compliance, {len(DP04_ROWS)} tests)…")
            load_dp04(cur, DP04_ROWS)
            print(f"Loading {FUND_ID} — DP-05 (cashflows, {len(DP05_ROWS)} waterfall rows)…")
            load_dp05(cur, DP05_ROWS)
            print(f"Loading {FUND_ID} — DP-06 (fees, {len(DP06_ROWS)} rows)…")
            load_dp06(cur, DP06_ROWS)
            print(f"Loading {FUND_ID} — DP-07 (key metrics, {len(DP07_ROWS)} quarterly rows)…")
            load_dp07(cur, DP07_ROWS)
            print(f"Loading {FUND_ID} — DP-08 (liability structure, {len(DP08_ROWS)} tranches)…")
            load_dp08(cur, DP08_ROWS)
        conn.commit()
        print(f"\n✓  {FUND_ID} loaded successfully across all 8 data products.")
        print(f"   DP-02: {len(DP02_ROWS)} positions  (total par ~$376M, 6 tech sub-sectors)")
        print(f"   DP-03: {len(DP03_ROWS)} quarterly snapshots  (2019-06-30 → 2026-05-29)")
        print(f"   DP-07: {len(DP07_ROWS)} quarterly snapshots  (2019-06-30 → 2026-05-29)")
        print("   DP-08: Class A amortised from $240M → $162M  ($78M repaid)")
    except psycopg2.DatabaseError as exc:
        conn.rollback()
        print(f"Error: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

"""FeeAgent — specialist for clo:FeeExpense, clo:ManagementFee, clo:IncentiveFee."""
from __future__ import annotations

from clo_db_agent.tools import (
    get_fee_summary,
    get_fund_static_profile,
    get_latest_performance,
    list_available_funds,
)

from .base_agent import BaseAgent
from .tools.fee_tools import FEE_TOOLS
from .tools.memory_tools import MEMORY_TOOLS

_ROLE = """\
You are the CLO Fee Agent, specialised in clo:FeeExpense analysis.

ONTOLOGY TRAVERSAL
━━━━━━━━━━━━━━━━━
Before calling any tool, map the question to the correct ontology path and data product:
  clo:CLOFund → clo:hasFee → clo:FeeExpense                    → dp:DP-06 (get_fee_summary)
  clo:ManagementFee (subclass of clo:FeeExpense)                → dp:DP-06 ("Management Fee" rows)
  clo:IncentiveFee (subclass of clo:FeeExpense)                 → dp:DP-06 ("Incentive Fee" rows)
  Fee rates and hurdle from DP-01 static profile               → get_fund_static_profile
  Fee drag on returns: compare clo:grossIRR vs clo:netIRR      → get_latest_performance

FEE STRUCTURE
━━━━━━━━━━━━
• clo:ManagementFee: fixed % of fund assets (typically ~0.40% p.a.) — senior in waterfall
• clo:IncentiveFee: performance-based, paid above hurdle rate — subordinated in waterfall
  (per clo:WaterfallPriorityAxiom step 8: Incentive Fee paid before equity but after sub notes)
• Total Expense Ratio (TER) includes all fees and expenses as % of NAV

WORKFLOW
━━━━━━━━
1. Call get_fee_summary to retrieve all clo:FeeExpense rows from dp:DP-06.
2. Call compute_ytd_fees for year-to-date totals by fee type.
3. Call compute_fee_drag to compare gross vs net IRR and quantify fee impact.
4. Call get_fund_static_profile for contractual fee rates and hurdle rate from dp:DP-01.
5. Write findings to session memory via write_session_memory before completing.
6. Cite: fund identifier, dp:DP-06, and the period for every fee figure.
"""


class FeeAgent(BaseAgent):
    AGENT_NAME = "fee_agent"

    @property
    def _role_instructions(self) -> str:
        return _ROLE

    @property
    def _tools(self) -> list:
        return [
            list_available_funds,
            get_fee_summary,
            get_fund_static_profile,
            get_latest_performance,
            *FEE_TOOLS,
            *MEMORY_TOOLS,
        ]

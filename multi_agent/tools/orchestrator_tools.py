"""Agent dispatch tools for the OrchestratorAgent.

Each function instantiates the named specialist, runs it against the task,
and returns its final answer. Imports are deferred inside function bodies
to avoid circular imports.
"""
from __future__ import annotations

import json

from anthropic import beta_tool

from clo_db_agent.tools import list_available_funds  # reused directly


@beta_tool
def get_ontology_retrieval_map() -> str:
    """Return clo:retrievalMap from the ontology — maps ontology classes to data products.

    Use this before dispatching to determine which specialist agent owns a given
    ontology class:
      clo:LoanAsset, clo:KeyMetricSnapshot  → call_portfolio_agent  (dp:DP-02, dp:DP-07)
      clo:PerformanceSnapshot               → call_performance_agent (dp:DP-03)
      clo:ComplianceTest, clo:OCTest        → call_compliance_agent  (dp:DP-04)
      clo:Waterfall, clo:EquityDistribution → call_cashflow_agent    (dp:DP-05)
      clo:FeeExpense, clo:ManagementFee     → call_fee_agent         (dp:DP-06)
      Portfolio optimisation                → call_optimizer_agent
      Final report synthesis                → call_reporting_agent
    """
    from multi_agent import ONTOLOGY_PATH
    import json as _json

    ontology = _json.loads(ONTOLOGY_PATH.read_text())
    retrieval_map = next(
        (item for item in ontology.get("@graph", []) if item.get("@id") == "clo:retrievalMap"),
        None,
    )
    return json.dumps(retrieval_map or {"error": "retrieval map not found in ontology"})


@beta_tool
def call_portfolio_agent(fund_id: str, task: str, session_date: str) -> str:
    """Dispatch to the PortfolioAgent (clo:LoanAsset, clo:KeyMetricSnapshot).

    Use for: loan-level analysis (dp:DP-02), WARF/WAS/WAL trends (dp:DP-07),
    CCC bucket identification, industry concentration, return attribution,
    loan replacement simulation.

    Args:
        fund_id:      Fund identifier.
        task:         Plain-text task for the portfolio agent.
        session_date: ISO date (YYYY-MM-DD) for session memory writes.
    """
    from multi_agent.portfolio_agent import PortfolioAgent
    return PortfolioAgent().ask(task, fund_id=fund_id, session_date=session_date)


@beta_tool
def call_compliance_agent(fund_id: str, task: str, session_date: str) -> str:
    """Dispatch to the ComplianceAgent (clo:ComplianceTest, clo:OCTest, clo:ICTest).

    Use for: OC/IC/quality/concentration test status (dp:DP-04), breach consequence
    analysis, OC diversion amounts, and stress-testing cushions under downgrades.

    Args:
        fund_id:      Fund identifier.
        task:         Plain-text task for the compliance agent.
        session_date: ISO date (YYYY-MM-DD) for session memory writes.
    """
    from multi_agent.compliance_agent import ComplianceAgent
    return ComplianceAgent().ask(task, fund_id=fund_id, session_date=session_date)


@beta_tool
def call_cashflow_agent(fund_id: str, task: str, session_date: str) -> str:
    """Dispatch to the CashflowAgent (clo:Waterfall, clo:EquityDistribution).

    Use for: waterfall modelling (dp:DP-05), equity distribution amounts,
    OC diversion analysis, and tranche payment sequencing.

    Per clo:WaterfallPriorityAxiom: always call call_compliance_agent first
    to determine whether equity is blocked before calling this agent.

    Args:
        fund_id:      Fund identifier.
        task:         Plain-text task for the cashflow agent.
        session_date: ISO date (YYYY-MM-DD) for session memory writes.
    """
    from multi_agent.cashflow_agent import CashflowAgent
    return CashflowAgent().ask(task, fund_id=fund_id, session_date=session_date)


@beta_tool
def call_performance_agent(fund_id: str, task: str, session_date: str) -> str:
    """Dispatch to the PerformanceAgent (clo:PerformanceSnapshot).

    Use for: NAV, IRR, DPI, RVPI, TVPI, P&L, benchmark comparison (dp:DP-03),
    period returns, and multi-period performance trends.

    Args:
        fund_id:      Fund identifier.
        task:         Plain-text task for the performance agent.
        session_date: ISO date (YYYY-MM-DD) for session memory writes.
    """
    from multi_agent.performance_agent import PerformanceAgent
    return PerformanceAgent().ask(task, fund_id=fund_id, session_date=session_date)


@beta_tool
def call_fee_agent(fund_id: str, task: str, session_date: str) -> str:
    """Dispatch to the FeeAgent (clo:FeeExpense, clo:ManagementFee, clo:IncentiveFee).

    Use for: fee and expense analysis (dp:DP-06), YTD totals, fee drag on returns,
    incentive fee hurdle and accrual status.

    Args:
        fund_id:      Fund identifier.
        task:         Plain-text task for the fee agent.
        session_date: ISO date (YYYY-MM-DD) for session memory writes.
    """
    from multi_agent.fee_agent import FeeAgent
    return FeeAgent().ask(task, fund_id=fund_id, session_date=session_date)


@beta_tool
def call_optimizer_agent(fund_id: str, task: str, session_date: str) -> str:
    """Dispatch to the OptimizerAgent (greedy hill-climbing portfolio return optimiser).

    Iteratively swaps lower-spread positions for higher-spread ones, accepting trades
    that improve equity yield while keeping all clo:ComplianceTest passing (up to 150
    iterations). Use when OC cushion is thin or equity yield improvement is requested.

    Args:
        fund_id:      Fund identifier.
        task:         Plain-text task for the optimizer agent.
        session_date: ISO date (YYYY-MM-DD) for session memory writes.
    """
    from multi_agent.optimizer_agent import OptimizerAgent
    return OptimizerAgent().ask(task, fund_id=fund_id, session_date=session_date)


@beta_tool
def call_reporting_agent(fund_id: str, session_date: str, task: str) -> str:
    """Dispatch to the ReportingAgent to synthesise all specialist outputs into a report.

    The ReportingAgent reads all agents' session memories for the given fund and date
    and compiles a structured distribution authorisation memo or other report.

    Always call specialist agents first and ensure they have written to session memory
    before calling this agent.

    Args:
        fund_id:      Fund identifier.
        session_date: ISO date (YYYY-MM-DD) used to locate session memory files.
        task:         Plain-text task for the reporting agent.
    """
    from multi_agent.reporting_agent import ReportingAgent
    return ReportingAgent().ask(task, fund_id=fund_id, session_date=session_date)


ORCHESTRATOR_TOOLS: list = [
    get_ontology_retrieval_map,
    list_available_funds,
    call_portfolio_agent,
    call_compliance_agent,
    call_cashflow_agent,
    call_performance_agent,
    call_fee_agent,
    call_optimizer_agent,
    call_reporting_agent,
]

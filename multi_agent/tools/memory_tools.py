"""Filesystem session memory tools — available to all specialist agents."""
from __future__ import annotations

import json
from typing import Any

from anthropic import beta_tool

from multi_agent import memory as _mem


@beta_tool
def write_session_memory(
    agent_name: str,
    fund_id: str,
    session_date: str,
    summary: str,
    data_json: str,
) -> str:
    """Persist this agent's analysis to session memory for coordination with other agents.

    Call this after completing any significant analysis. Other agents and the
    orchestrator read this output via read_session_memory or read_all_agent_memories.

    Args:
        agent_name:   Name of this agent (e.g. "portfolio_agent").
        fund_id:      Fund identifier (e.g. "DKIG-2024-VII").
        session_date: ISO date string for this session (YYYY-MM-DD).
        summary:      One-paragraph plain-text summary of the analysis findings.
        data_json:    JSON string of the structured analysis output.
    """
    try:
        data: Any = json.loads(data_json)
    except json.JSONDecodeError:
        data = {"raw": data_json}
    _mem.write(agent_name, fund_id, session_date, {"summary": summary, "data": data})
    return json.dumps({
        "status": "ok",
        "agent": agent_name,
        "fund_id": fund_id,
        "session_date": session_date,
    })


@beta_tool
def read_session_memory(agent_name: str, fund_id: str, session_date: str) -> str:
    """Read a specific agent's stored analysis from session memory.

    Args:
        agent_name:   Name of the agent whose memory to retrieve.
        fund_id:      Fund identifier.
        session_date: ISO date string (YYYY-MM-DD).
    """
    record = _mem.read(agent_name, fund_id, session_date)
    if record is None:
        return json.dumps({
            "status": "not_found",
            "agent": agent_name,
            "fund_id": fund_id,
            "session_date": session_date,
        })
    return json.dumps(record)


@beta_tool
def read_all_agent_memories(fund_id: str, session_date: str) -> str:
    """Read all agents' stored analyses for a fund on a given session date.

    Used by the ReportingAgent and Orchestrator to synthesise outputs from
    all specialists into a consolidated view.

    Args:
        fund_id:      Fund identifier.
        session_date: ISO date string (YYYY-MM-DD).
    """
    return json.dumps(_mem.read_all(fund_id, session_date))


@beta_tool
def list_session_memories(fund_id: str) -> str:
    """List all session dates for which memory exists for a given fund.

    Args:
        fund_id: Fund identifier.
    """
    return json.dumps({"fund_id": fund_id, "sessions": _mem.list_sessions(fund_id)})


MEMORY_TOOLS: list = [
    write_session_memory,
    read_session_memory,
    read_all_agent_memories,
    list_session_memories,
]

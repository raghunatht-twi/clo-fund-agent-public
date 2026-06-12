"""Filesystem-backed session memory store for multi-agent coordination.

Layout:
    session_memory/{fund_id}/{session_date}/{agent_name}.json

Each file contains the agent's full analysis output for a given fund and date,
enabling agents to share findings without re-querying the database.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from . import MEMORY_DIR

logger = logging.getLogger(__name__)


def _agent_path(agent_name: str, fund_id: str, session_date: str) -> Path:
    return MEMORY_DIR / fund_id / session_date / f"{agent_name}.json"


def write(agent_name: str, fund_id: str, session_date: str, data: dict[str, Any]) -> None:
    """Persist an agent's analysis output to session memory."""
    path = _agent_path(agent_name, fund_id, session_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "agent": agent_name,
        "fund_id": fund_id,
        "session_date": session_date,
        "timestamp": datetime.utcnow().isoformat(),
        **data,
    }
    path.write_text(json.dumps(record, indent=2, default=str))
    logger.debug("Memory written: %s", path)


def read(agent_name: str, fund_id: str, session_date: str) -> dict[str, Any] | None:
    """Read a single agent's session memory. Returns None if not found."""
    path = _agent_path(agent_name, fund_id, session_date)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def read_all(fund_id: str, session_date: str) -> dict[str, Any]:
    """Read all agents' session memories for a fund on a given date."""
    session_dir = MEMORY_DIR / fund_id / session_date
    if not session_dir.exists():
        return {}
    return {
        path.stem: json.loads(path.read_text())
        for path in sorted(session_dir.glob("*.json"))
    }


def list_sessions(fund_id: str) -> list[str]:
    """List all session dates that have stored memory for a fund."""
    fund_dir = MEMORY_DIR / fund_id
    if not fund_dir.exists():
        return []
    return sorted(d.name for d in fund_dir.iterdir() if d.is_dir())

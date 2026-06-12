"""Entry point for the CLO multi-agent system.

Usage:
    uv run python -m multi_agent 'Run distribution report for DKIG-2024-VII'  # one-shot
    uv run python -m multi_agent                                                # REPL
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date

import anthropic

from .orchestrator import OrchestratorAgent
from . import _shared

logging.basicConfig(level=logging.WARNING)

_MAX_SESSION_TOKENS: int = int(os.environ.get("CLO_SESSION_TOKEN_LIMIT", "400000"))

USAGE = """\
CLO Multi-Agent System — Orchestrator entry point

Usage:
  python -m multi_agent 'Run Q2 distribution report for DKIG-2024-VII'   # one-shot
  python -m multi_agent                                                     # interactive REPL

Requires ANTHROPIC_API_KEY in the environment.
PostgreSQL must be running (DATABASE_URL env var, default host=/tmp port=5432 dbname=postgres).

Environment variables:
  CLO_SESSION_TOKEN_LIMIT   Max tokens per REPL session (default 400000)
  CLO_REQUEST_TIMEOUT_SEC        Per-specialist-agent timeout in seconds (default 120)
  CLO_ORCHESTRATOR_TIMEOUT_SEC   Orchestrator outer stream timeout in seconds (default 900)
  CLO_MAX_TOOL_ITERATIONS        Max tool-call cycles per agent (default 10)
  CLO_ONTOLOGY_SHA256            Expected SHA-256 of the ontology file (optional)
"""


def _check_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("error: ANTHROPIC_API_KEY is not set in the environment.", file=sys.stderr)
        sys.exit(2)


def _run_oneshot(question: str) -> int:
    _check_api_key()
    try:
        question = _shared.sanitise_input(question)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    today = date.today().isoformat()
    agent = OrchestratorAgent()
    print(f"\033[1mQ:\033[0m {question}\n")
    print("\033[2m[orchestrating — tool calls will appear below]\033[0m")
    try:
        for chunk in agent.stream(question, session_date=today):
            print(chunk)
    except TimeoutError as e:
        print(f"\ntimeout: {e}", file=sys.stderr)
        return 1
    except anthropic.APIError as e:
        print(f"\nAPI error: {e}", file=sys.stderr)
        return 1
    return 0


def _run_repl() -> int:
    _check_api_key()
    client = anthropic.Anthropic()
    today = date.today().isoformat()
    agent = OrchestratorAgent(client=client)

    print("\033[1mCLO Multi-Agent System\033[0m  (Orchestrator REPL)")
    print(f"Session date: {today}")
    print("Ctrl-D to exit\n")

    session_tokens = 0
    while True:
        if session_tokens >= _MAX_SESSION_TOKENS:
            print(
                f"\n[Session token budget ({_MAX_SESSION_TOKENS:,}) exhausted. "
                "Please start a new session.]",
                file=sys.stderr,
            )
            return 0
        try:
            question = input("\033[1mQ> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            continue
        try:
            question = _shared.sanitise_input(question)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            continue

        print("\033[2m[orchestrating — tool calls will appear below]\033[0m")
        try:
            for chunk in agent.stream(question, session_date=today):
                print(chunk)
            print()
        except TimeoutError as e:
            print(f"\ntimeout: {e}", file=sys.stderr)
        except anthropic.APIError as e:
            print(f"\nAPI error: {e}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if argv and argv[0] in {"-h", "--help"}:
        print(USAGE)
        return 0
    if len(argv) > 1:
        print(
            "error: pass the question as a single quoted argument.\n"
            "  python -m multi_agent 'your question here'",
            file=sys.stderr,
        )
        return 2
    if argv:
        return _run_oneshot(argv[0])
    return _run_repl()


if __name__ == "__main__":
    sys.exit(main())

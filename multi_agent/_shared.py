"""Shared security controls and ontology utilities for the multi-agent system."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata

from . import ONTOLOGY_PATH

logger = logging.getLogger(__name__)

# AI-01: Prompt injection guard
_MAX_QUESTION_LEN = 500
_INJECTION_PATTERNS: list[str] = [
    "ignore previous instructions",
    "ignore prior instructions",
    "disregard previous",
    "forget your instructions",
    "print your system prompt",
    "reveal your system prompt",
    "what is your system prompt",
    "output your instructions",
    "repeat everything above",
    "jailbreak",
    "pretend you are",
    "act as if you have no",
    "you are now",
    "new instructions",
    "override previous",
    "ignore all previous",
    "do not follow",
]

# AI-04/07/12/13: Output safety
_SYSTEM_PROMPT_SENTINELS: frozenset[str] = frozenset([
    "security instructions",
    "fund identification rules",
    "answering rules",
    "===== ontology",
    "loan-level analysis rules",
    "role_instructions",
    "system prompt",
    "tool definitions",
    "internal configuration",
])
_FINANCIAL_METRIC_RE = re.compile(
    r"\$[\d,]+\.?\d*"
    r"|\b\d{4,}(?:\.\d+)?%?"
    r"|\b\d+\.\d{2,}\s*%"
    r"|\b\d+(?:\.\d+)?\s*(?:bps|x\b)"
)
_FUND_ID_RE = re.compile(r"DKIG[-\s](?:Funding\s+)?\d{4}")
_DP_REF_RE = re.compile(r"\bdp?:?DP-0[1-8]\b", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"\b\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b")

_ontology_hash: str | None = None


def sanitise_input(question: str) -> str:
    """Enforce length cap and reject prompt-injection patterns (AI-01)."""
    if len(question) > _MAX_QUESTION_LEN:
        raise ValueError(
            f"Question exceeds {_MAX_QUESTION_LEN} character limit "
            f"({len(question)} characters received)."
        )
    normalised = unicodedata.normalize("NFKC", question).lower()
    for pattern in _INJECTION_PATTERNS:
        if pattern in normalised:
            raise ValueError("Question contains disallowed content.")
    return question.strip()


def check_output(text: str) -> str:
    """Apply output safety checks before returning the final response (AI-04/07/12/13)."""
    text_lower = text.lower()
    for sentinel in _SYSTEM_PROMPT_SENTINELS:
        if sentinel in text_lower:
            logger.warning("Possible system prompt content detected in output; suppressed.")
            return (
                "[Response withheld: output contained disallowed content. "
                "Please rephrase your question and try again.]"
            )
    if _FINANCIAL_METRIC_RE.search(text):
        missing: list[str] = []
        if not _FUND_ID_RE.search(text):
            missing.append("fund identifier")
        if not _DP_REF_RE.search(text):
            missing.append("data product reference (dp:DP-0X)")
        if not _ISO_DATE_RE.search(text):
            missing.append("reporting date")
        if missing:
            text += (
                "\n\n⚠ Citation warning: this response may be missing "
                + ", ".join(missing)
                + ". Please verify figures independently."
            )
    return text


def load_ontology() -> str:
    """Load the JSON-LD ontology, verify hash consistency, return compact JSON (AI-06)."""
    global _ontology_hash
    raw = ONTOLOGY_PATH.read_bytes()
    current_hash = hashlib.sha256(raw).hexdigest()
    expected = os.environ.get("CLO_ONTOLOGY_SHA256", "")
    if expected and current_hash != expected:
        raise EnvironmentError(
            f"Ontology integrity check failed "
            f"(expected …{expected[-12:]}, got …{current_hash[-12:]})."
        )
    if _ontology_hash is None:
        _ontology_hash = current_hash
        logger.info("Ontology loaded. SHA-256: %s…", current_hash[:16])
    elif current_hash != _ontology_hash:
        raise EnvironmentError("Ontology file changed on disk since startup — possible tampering.")
    return json.dumps(json.loads(raw), separators=(",", ":"), sort_keys=True)

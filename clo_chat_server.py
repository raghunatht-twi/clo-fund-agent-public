"""Browser-based chat interface for the CLO Fund Performance Agent.

Run:
    uv run python clo_chat_server.py

Then open: http://localhost:7860

Environment variables:
    ANTHROPIC_API_KEY   Required.
    PORT                HTTP port (default 7860).
    DATABASE_URL        PostgreSQL DSN (default host=/tmp port=5432 dbname=postgres).
    CHAT_CORS_ORIGINS   Comma-separated allowed CORS origins
                        (default "http://localhost:7860").
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
import uvicorn  # noqa: E402

import clo_db_agent.agent as _agent  # noqa: E402

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s  %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("clo_chat")

_ANSI_RE = re.compile(r"\x1b\[\d*m")
_HTML_FILE = ROOT / "CLO_Agent_Chat.html"
_AGENT_SSE_TIMEOUT_SEC = 135
# Multi-agent orchestration involves sequential specialist calls; allow much longer.
_MULTI_AGENT_SSE_TIMEOUT_SEC = int(os.environ.get("CLO_ORCHESTRATOR_TIMEOUT_SEC", "900")) + 60

# ---------------------------------------------------------------------------
# CORS  (LLM02: no wildcard — env-var allowlist)
# ---------------------------------------------------------------------------
_raw_chat_origins = os.environ.get("CHAT_CORS_ORIGINS", "http://localhost:7860")
_chat_origins = [o.strip() for o in _raw_chat_origins.split(",") if o.strip()]

app = FastAPI(title="CLO Agent Chat", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_chat_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Rate limiting  (LLM10: sliding-window per IP, 30 req/min)
# ---------------------------------------------------------------------------
_CHAT_RATE_WINDOW = 60
_CHAT_RATE_LIMIT = 30
_chat_rate_buckets: dict[str, collections.deque] = collections.defaultdict(collections.deque)


@app.middleware("http")
async def _chat_rate_limit(request: Request, call_next: Any) -> Response:
    client = request.client.host if request.client else "unknown"
    now = time.time()
    cutoff = now - _CHAT_RATE_WINDOW
    bucket = _chat_rate_buckets[client]
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    if len(bucket) >= _CHAT_RATE_LIMIT:
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded. Maximum 30 requests per minute."},
        )
    bucket.append(now)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Concurrency cap  (LLM10: max 5 concurrent agent requests)
# ---------------------------------------------------------------------------
_MAX_CONCURRENT_ASKS = 5
_concurrent_asks_sem = threading.Semaphore(_MAX_CONCURRENT_ASKS)


class AskRequest(BaseModel):
    question: str = Field(..., max_length=500)  # LLM01: input length cap
    mode: str = Field("single", pattern="^(single|multi)$")


@app.get("/", response_class=HTMLResponse)
def ui() -> HTMLResponse:
    if not _HTML_FILE.exists():
        return HTMLResponse(
            "<h1>CLO_Agent_Chat.html not found</h1>"
            "<p>Run the project build or place the HTML file in the same directory.</p>",
            status_code=404,
        )
    return HTMLResponse(_HTML_FILE.read_text(encoding="utf-8"))


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _classify_chunk(chunk: str) -> tuple[str, str]:
    """Return (event_type, cleaned_text) for an agent chunk; event_type '' means skip."""
    if "\x1b[2m" in chunk or "\033[2m" in chunk:
        return "tool_call", _ANSI_RE.sub("", chunk).strip()
    text = chunk.lstrip("\n")
    if not text:
        return "", ""
    if text.startswith("[Warning:") or text.startswith("[Session:"):
        return "warning", text
    return "answer", text


@app.post("/ask")
async def ask(body: AskRequest) -> StreamingResponse:
    """Stream agent response as Server-Sent Events.

    Event types emitted:
        {"type": "tool_call", "text": "→ tool_name(args)"}
        {"type": "answer",    "text": "<full markdown answer>"}
        {"type": "warning",   "text": "[Warning: ...]"}
        {"type": "error",     "message": "<error string>"}
        {"type": "done"}
    """
    if not _concurrent_asks_sem.acquire(blocking=False):
        return JSONResponse(
            status_code=503,
            content={"error": "Server busy — too many concurrent requests. Please try again shortly."},  # noqa: E501
        )
    loop = asyncio.get_event_loop()
    q: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()

    is_multi = body.mode == "multi"
    sse_timeout = _MULTI_AGENT_SSE_TIMEOUT_SEC if is_multi else _AGENT_SSE_TIMEOUT_SEC

    def _worker() -> None:
        try:
            if is_multi:
                from datetime import date as _date
                from multi_agent.orchestrator import OrchestratorAgent
                orchestrator = OrchestratorAgent()
                chunks = orchestrator.stream(
                    body.question,
                    session_date=_date.today().isoformat(),
                )
            else:
                chunks = _agent.ask(body.question)
            for chunk in chunks:
                loop.call_soon_threadsafe(q.put_nowait, ("chunk", chunk))
        except Exception as exc:  # noqa: BLE001
            logger.error("Agent error (mode=%s)", body.mode, exc_info=exc)
            loop.call_soon_threadsafe(q.put_nowait, ("error", str(exc)))
        finally:
            loop.call_soon_threadsafe(q.put_nowait, ("done", None))

    threading.Thread(target=_worker, daemon=True).start()

    async def generate():
        try:
            while True:
                try:
                    kind, value = await asyncio.wait_for(q.get(), timeout=sse_timeout)
                except asyncio.TimeoutError:
                    yield _sse({"type": "error", "message": f"Request timed out after {sse_timeout} s."})  # noqa: E501
                    yield _sse({"type": "done"})
                    break

                if kind == "done":
                    yield _sse({"type": "done"})
                    break
                if kind == "error":
                    yield _sse({"type": "error", "message": value or "Unknown error"})
                    yield _sse({"type": "done"})
                    break

                chunk: str = value  # type: ignore[assignment]
                event_type, text = _classify_chunk(chunk)
                if not event_type:
                    continue
                yield _sse({"type": event_type, "text": text})
        except asyncio.CancelledError:
            pass
        finally:
            _concurrent_asks_sem.release()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("error: ANTHROPIC_API_KEY is not set.")
    port = int(os.environ.get("PORT", "7860"))
    print(f"\n  CLO Fund Performance Agent  ➜  http://localhost:{port}\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

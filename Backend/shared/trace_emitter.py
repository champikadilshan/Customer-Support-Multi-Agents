"""
shared/trace_emitter.py
-----------------------
Per-session execution trace bus for the dashboard.

Cross-process forwarding
------------------------
Each specialist agent runs in its own process. The orchestrator hosts the
dashboard SSE endpoint (GET /chat/trace/{session_id}).

Set TRACE_FORWARD_URL=http://localhost:8001/internal/trace on every agent
process. Every emit() call will also fire-and-forget an HTTP POST to that
URL, which the orchestrator stores in its own buffer for the dashboard.

Event types
-----------
  orchestrator_dispatch  — orchestrator routed a message to an agent
  agent_start            — an agent began processing
  agent_end              — an agent finished processing
  agent_handoff          — one agent is calling another internally
  tool_start             — a tool call began inside an agent
  tool_end               — a tool call completed
  hitl_requested         — HITL confirmation gate reached
  hitl_resumed           — HITL response received, graph resuming
  error                  — something went wrong
"""

import os
import threading
import asyncio
import json
import httpx
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional


MAX_EVENTS_PER_SESSION = 500
POLL_INTERVAL          = 0.05   # seconds between idle polls

# When set, every emit() also POSTs the event to this URL (orchestrator receiver).
_FORWARD_URL: Optional[str] = os.getenv("TRACE_FORWARD_URL", "").strip() or None


class TraceEmitter:
    """Thread-safe in-memory trace bus with optional cross-process forwarding."""

    def __init__(self) -> None:
        self._queues:      dict[str, deque]         = defaultdict(lambda: deque(maxlen=MAX_EVENTS_PER_SESSION))
        self._signals:     dict[str, asyncio.Event] = {}
        self._lock         = threading.Lock()
        self._http_client: Optional[httpx.Client]   = None

    # ── emit — called by agents (synchronous, any thread) ─────────────────────

    def emit(self, session_id: str, event_type: str, **kwargs) -> None:
        event = {
            "type":       event_type,
            "session_id": session_id,
            "ts":         datetime.now(timezone.utc).isoformat(),
            **kwargs,
        }
        self._store(session_id, event)
        if _FORWARD_URL:
            self._forward(event)

    # ── receive — called by orchestrator /internal/trace endpoint ─────────────

    def receive(self, event: dict) -> None:
        """Store a forwarded event from a remote agent process."""
        session_id = event.get("session_id", "")
        if session_id:
            self._store(session_id, event)

    # ── stream — async generator for FastAPI SSE endpoint ─────────────────────

    async def stream(self, session_id: str, timeout_s: float = 300.0):
        """
        Yield SSE data lines for all buffered events (replay from index 0),
        then continue live until timeout.
        """
        signal       = asyncio.Event()
        signal._loop = asyncio.get_event_loop()

        with self._lock:
            self._signals[session_id] = signal

        cursor = 0   # always replay from the start so late-connecting clients catch up

        try:
            deadline = asyncio.get_event_loop().time() + timeout_s

            while True:
                with self._lock:
                    batch   = list(self._queues[session_id])[cursor:]
                    cursor += len(batch)

                for event in batch:
                    yield f"data: {json.dumps(event)}\n\n"

                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break

                signal.clear()
                try:
                    await asyncio.wait_for(
                        asyncio.shield(signal.wait()),
                        timeout=min(POLL_INTERVAL * 20, remaining),
                    )
                except asyncio.TimeoutError:
                    pass

        finally:
            with self._lock:
                self._signals.pop(session_id, None)

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._queues.pop(session_id, None)

    def get_events(self, session_id: str) -> list[dict]:
        with self._lock:
            return list(self._queues.get(session_id, []))

    # ── internal helpers ───────────────────────────────────────────────────────

    def _store(self, session_id: str, event: dict) -> None:
        with self._lock:
            queue = self._queues[session_id]
            if queue:
                last = queue[-1]
                # Deduplicate by type + session_id + request_id (when present)
                # or type + session_id + ts (for events without request_id).
                # Prevents double-writes when the orchestrator both emits locally
                # and receives a forwarded copy of the same event.
                if (last.get("type") == event.get("type") and
                        last.get("session_id") == event.get("session_id")):
                    if event.get("request_id"):
                        if last.get("request_id") == event.get("request_id"):
                            return
                    else:
                        # No request_id — fall back to ts match (within 1 second)
                        if last.get("ts", "")[:19] == event.get("ts", "")[:19]:
                            return
            queue.append(event)
            signal = self._signals.get(session_id)
        if signal is not None:
            try:
                signal._loop.call_soon_threadsafe(signal.set)
            except Exception:
                pass

    def _forward(self, event: dict) -> None:
        try:
            if self._http_client is None:
                self._http_client = httpx.Client(timeout=2.0)
            self._http_client.post(_FORWARD_URL, json=event)
        except Exception:
            pass   # forwarding is best-effort — never crash the agent


# Module-level singleton
trace_emitter = TraceEmitter()
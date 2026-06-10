import os
import threading
import asyncio
import json
import httpx

from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional


MAX_EVENTS_PER_SESSION = 500
POLL_INTERVAL          = 0.05

_FORWARD_URL: Optional[str] = os.getenv("TRACE_FORWARD_URL", "").strip() or None


class TraceEmitter:
    def __init__(self) -> None:
        self._queues:      dict[str, deque]         = defaultdict(lambda: deque(maxlen=MAX_EVENTS_PER_SESSION))
        self._signals:     dict[str, asyncio.Event] = {}
        self._lock         = threading.Lock()
        self._http_client: Optional[httpx.Client]   = None

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

    def receive(self, event: dict) -> None:
        session_id = event.get("session_id", "")
        if session_id:
            self._store(session_id, event)

    async def stream(self, session_id: str, timeout_s: float = 300.0):
        signal       = asyncio.Event()
        signal._loop = asyncio.get_event_loop()

        with self._lock:
            self._signals[session_id] = signal

        cursor = 0

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

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._queues.pop(session_id, None)

    def get_events(self, session_id: str) -> list[dict]:
        with self._lock:
            return list(self._queues.get(session_id, []))

    def _store(self, session_id: str, event: dict) -> None:
        with self._lock:
            queue = self._queues[session_id]
            if queue:
                last = queue[-1]

                if (last.get("type") == event.get("type") and
                        last.get("session_id") == event.get("session_id")):
                    if event.get("request_id"):
                        if last.get("request_id") == event.get("request_id"):
                            return
                    else:
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
            pass


trace_emitter = TraceEmitter()
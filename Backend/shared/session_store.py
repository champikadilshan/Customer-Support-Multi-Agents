"""
shared/session_store.py
-----------------------
In-memory conversation session store.

Each session tracks:
  - Full LangChain message history (serialised as plain dicts so they are
    JSON-safe and can be sent inside A2ARequest.conversation_history).
  - The currently active specialist agent (sticky routing — Option B).
  - Loose metadata the agents or orchestrator can write to
    (e.g. resolved customer_id, account_id, customer name).
  - Timestamps for creation and last activity.

All public helpers are synchronous and thread-safe via a threading.Lock.
The store is a module-level singleton — import it anywhere with:

    from shared.session_store import session_store

Usage
-----
    sid  = session_store.create()           # new session → UUID str
    sess = session_store.get(sid)           # ConversationSession | None
    sess = session_store.get_or_create(sid) # always returns a session

    session_store.append_messages(sid, [{"type":"human","content":"hi"}])
    session_store.set_active_agent(sid, AgentType.BILLING)
    session_store.set_metadata(sid, "account_id", "ACC-001")

    session_store.reset(sid)   # clears messages + active_agent, keeps metadata option
    session_store.delete(sid)  # removes session entirely
"""

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from shared.a2a_protocol import AgentType


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class ConversationSession:
    session_id:    str
    # Serialised message history.  Each dict has at minimum:
    #   {"type": "human"|"ai"|"tool", "content": "..."}
    # Tool messages also carry {"name": "<tool_name>"}
    messages:      list[dict]            = field(default_factory=list)
    # Sticky routing: once set, the orchestrator skips intent detection
    # and dispatches directly to this agent.
    active_agent:  Optional[AgentType]   = None
    # Loose key-value store for facts extracted during the conversation
    # (customer name, account_id, phone, …).
    metadata:      dict                  = field(default_factory=dict)
    created_at:    datetime              = field(default_factory=datetime.utcnow)
    last_active:   datetime              = field(default_factory=datetime.utcnow)


# ── Store ─────────────────────────────────────────────────────────────────────

class InMemorySessionStore:
    """Thread-safe, in-memory conversation session store."""

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}
        self._lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def create(self) -> str:
        """Create a brand-new session and return its session_id."""
        sid = str(uuid.uuid4())
        with self._lock:
            self._sessions[sid] = ConversationSession(session_id=sid)
        return sid

    def get(self, session_id: str) -> Optional[ConversationSession]:
        """Return the session or None if it does not exist."""
        with self._lock:
            return self._sessions.get(session_id)

    def get_or_create(self, session_id: Optional[str]) -> ConversationSession:
        """
        Return an existing session or create a new one.
        If session_id is None or unknown a new session is created.
        The caller should use session.session_id going forward (it may differ
        from the supplied argument when a new session was created).
        """
        if session_id:
            with self._lock:
                sess = self._sessions.get(session_id)
                if sess:
                    sess.last_active = datetime.utcnow()
                    return sess

        # Create new
        sid = session_id or str(uuid.uuid4())
        sess = ConversationSession(session_id=sid)
        with self._lock:
            self._sessions[sid] = sess
        return sess

    def reset(self, session_id: str) -> bool:
        """
        Clear message history and active_agent for a session.
        Metadata is preserved so resolved facts (account_id etc.) survive.
        Returns True if the session existed, False otherwise.
        """
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                return False
            sess.messages     = []
            sess.active_agent = None
            sess.last_active  = datetime.utcnow()
            return True

    def delete(self, session_id: str) -> bool:
        """Remove the session entirely. Returns True if it existed."""
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    # ── Message helpers ───────────────────────────────────────────────────────

    def append_messages(self, session_id: str, messages: list[dict]) -> None:
        """
        Append serialised LangChain messages to the session history.
        No-op if the session does not exist.
        """
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess:
                sess.messages.extend(messages)
                sess.last_active = datetime.utcnow()

    def get_messages(self, session_id: str) -> list[dict]:
        """Return a copy of the message history (empty list if session missing)."""
        with self._lock:
            sess = self._sessions.get(session_id)
            return list(sess.messages) if sess else []

    # ── Routing helpers ───────────────────────────────────────────────────────

    def set_active_agent(self, session_id: str, agent: AgentType) -> None:
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess:
                sess.active_agent = agent
                sess.last_active  = datetime.utcnow()

    def get_active_agent(self, session_id: str) -> Optional[AgentType]:
        with self._lock:
            sess = self._sessions.get(session_id)
            return sess.active_agent if sess else None

    # ── Metadata helpers ──────────────────────────────────────────────────────

    def set_metadata(self, session_id: str, key: str, value) -> None:
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess:
                sess.metadata[key] = value

    def get_metadata(self, session_id: str, key: str, default=None):
        with self._lock:
            sess = self._sessions.get(session_id)
            return sess.metadata.get(key, default) if sess else default

    # ── Introspection ─────────────────────────────────────────────────────────

    def session_info(self, session_id: str) -> Optional[dict]:
        """Return a JSON-serialisable summary of a session (for the GET endpoint)."""
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                return None
            return {
                "session_id":    sess.session_id,
                "active_agent":  sess.active_agent.value if sess.active_agent else None,
                "message_count": len(sess.messages),
                "metadata":      dict(sess.metadata),
                "created_at":    sess.created_at.isoformat(),
                "last_active":   sess.last_active.isoformat(),
            }

    def all_session_ids(self) -> list[str]:
        with self._lock:
            return list(self._sessions.keys())


# ── Module-level singleton ────────────────────────────────────────────────────
# Import this anywhere: from shared.session_store import session_store
session_store = InMemorySessionStore()
import threading
import uuid

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from shared.a2a_protocol import AgentType
from shared.trace_emitter import trace_emitter


@dataclass
class ConversationSession:
    session_id:    str
    messages:      list[dict]            = field(default_factory=list)
    active_agent:  Optional[AgentType]   = None
    metadata:      dict                  = field(default_factory=dict)
    created_at:    datetime              = field(default_factory=datetime.utcnow)
    last_active:   datetime              = field(default_factory=datetime.utcnow)


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        sid = str(uuid.uuid4())

        with self._lock:
            self._sessions[sid] = ConversationSession(session_id=sid)
        return sid

    def get(self, session_id: str) -> Optional[ConversationSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def get_or_create(self, session_id: Optional[str]) -> ConversationSession:
        if session_id:
            with self._lock:
                sess = self._sessions.get(session_id)
                if sess:
                    sess.last_active = datetime.utcnow()
                    return sess

        sid = session_id or str(uuid.uuid4())
        sess = ConversationSession(session_id=sid)

        with self._lock:
            self._sessions[sid] = sess

        return sess

    def reset(self, session_id: str) -> bool:
        with self._lock:
            sess = self._sessions.get(session_id)

            if not sess:
                return False

            sess.messages     = []
            sess.active_agent = None
            sess.last_active  = datetime.utcnow()
            trace_emitter.clear(session_id)

            return True

    def delete(self, session_id: str) -> bool:
        with self._lock:
            existed = self._sessions.pop(session_id, None) is not None

        if existed:
            trace_emitter.clear(session_id)

        return existed


    def append_messages(self, session_id: str, messages: list[dict]) -> None:
        with self._lock:
            sess = self._sessions.get(session_id)

            if sess:
                sess.messages.extend(messages)
                sess.last_active = datetime.utcnow()

    def get_messages(self, session_id: str) -> list[dict]:
        with self._lock:
            sess = self._sessions.get(session_id)

            return list(sess.messages) if sess else []

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

    def set_metadata(self, session_id: str, key: str, value) -> None:
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess:
                sess.metadata[key] = value

    def get_metadata(self, session_id: str, key: str, default=None):
        with self._lock:
            sess = self._sessions.get(session_id)
            return sess.metadata.get(key, default) if sess else default

    def session_info(self, session_id: str) -> Optional[dict]:
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


session_store = InMemorySessionStore()
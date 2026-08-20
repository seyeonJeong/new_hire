from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from newhire.evaluate_open import ChatTurn

Speaker = Literal["trainee", "counterpart"]

MAX_TRAINEE_TURNS = 3
MIN_TRAINEE_TURNS = 1


@dataclass
class OpenSession:
    session_id: str
    scenario_id: str
    messages: list[dict[str, str]]
    evaluation_id: str | None = None


class OpenSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, OpenSession] = {}
        self._lock = threading.Lock()

    def create(self, scenario_id: str, opening: str) -> OpenSession:
        session = OpenSession(
            session_id=str(uuid.uuid4()),
            scenario_id=scenario_id,
            messages=[{"speaker": "counterpart", "text": opening}],
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> OpenSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def append_trainee(self, session_id: str, text: str) -> OpenSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.messages.append({"speaker": "trainee", "text": text})
            return session

    def append_counterpart(self, session_id: str, text: str) -> OpenSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.messages.append({"speaker": "counterpart", "text": text})
            return session

    def set_evaluation(self, session_id: str, evaluation_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session.evaluation_id = evaluation_id


def trainee_turn_count(messages: list[dict[str, Any]]) -> int:
    return sum(1 for item in messages if item.get("speaker") == "trainee")


def as_turns(messages: list[dict[str, Any]]) -> list[ChatTurn]:
    return [ChatTurn.model_validate(item) for item in messages]

"""Persists one trace per /chat call and one event per step (llm_call | tool_call | guard | final)."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import Trace, TraceEvent


class Tracer:
    def __init__(self, db: Session, conversation_id: str, user_id: int, guard_config: dict[str, Any]):
        self.db = db
        self.trace = Trace(conversation_id=conversation_id, user_id=user_id, guard_config=guard_config)
        db.add(self.trace)
        db.commit()

    @property
    def id(self) -> str:
        return self.trace.id

    def event(self, type_: str, step: int, payload: dict[str, Any], *, latency_ms: float | None = None,
              prompt_tokens: int | None = None, completion_tokens: int | None = None) -> None:
        self.db.add(TraceEvent(
            trace_id=self.trace.id, type=type_, step=step, payload=payload, latency_ms=latency_ms,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        ))
        self.db.commit()

    def finish(self, status: str, prompt_tokens: int, completion_tokens: int, latency_ms: float) -> None:
        self.trace.status = status
        self.trace.prompt_tokens = prompt_tokens
        self.trace.completion_tokens = completion_tokens
        self.trace.latency_ms = latency_ms
        self.trace.finished_at = datetime.now(timezone.utc)
        self.db.commit()

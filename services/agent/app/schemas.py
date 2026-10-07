from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatIn(BaseModel):
    conversation_id: str | None = Field(None, max_length=64)
    message: str = Field(..., min_length=1, max_length=4000)


class ChatOut(BaseModel):
    conversation_id: str
    answer: str
    status: str
    steps: list[dict[str, Any]]
    trace_id: str
    ticket_id: str | None = None
    usage: dict[str, int]
    latency_ms: float
    llm_calls: int


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str | None
    tool_calls: list[dict[str, Any]] | None
    tool_call_id: str | None
    kind: str
    trace_id: str | None
    created_at: datetime


class ConversationSummaryOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    last_message_at: datetime


class ConversationOut(BaseModel):
    id: str
    user_id: int
    created_at: datetime
    messages: list[MessageOut]


class TraceEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: str
    step: int
    payload: dict[str, Any]
    latency_ms: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    created_at: datetime


class TraceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    user_id: int
    status: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float | None
    guard_config: dict[str, Any] | None
    created_at: datetime
    finished_at: datetime | None
    events: list[TraceEventOut] = []


class TicketCallbackIn(BaseModel):
    id: str
    conversation_id: str
    user_id: int
    tool: str
    arguments: dict[str, Any]
    status: str
    review_note: str | None = None
    result: dict[str, Any] | None = None

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TicketCreate(BaseModel):
    conversation_id: str = Field("", max_length=100)
    user_id: int
    tool: str = Field(..., min_length=1, max_length=100)
    arguments: dict[str, Any]
    # subset of arguments identifying "the same request" (free text like `reason` excluded); default: arguments
    dedup_arguments: dict[str, Any] | None = None


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    user_id: int
    tool: str
    arguments: dict[str, Any]
    status: str
    reviewer_id: int | None
    review_note: str | None
    result: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class ReviewIn(BaseModel):
    note: str = Field("", max_length=1000, description="Ghi chú / lý do của staff")


class RefundRequestOut(BaseModel):
    ticket_id: str
    order_id: int | None
    user_id: int
    amount: int | None
    reason: str
    status: str
    review_note: str | None
    failure: str | None = None
    created_at: datetime
    updated_at: datetime

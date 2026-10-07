from typing import Any

from pydantic import BaseModel, Field


class InvokeIn(BaseModel):
    tool: str = Field(..., min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str = Field("", max_length=100)
    # the end user's own message for this turn (sent by the agent); used for confirm_args checks
    user_message: str = Field("", max_length=4000)

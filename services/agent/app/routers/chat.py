import hmac
import json
import logging

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opspilot_common.auth import CurrentUser, require_roles
from opspilot_common.errors import AppError

from app import prompts
from app.config import Settings, get_settings
from app.db import get_db
from app.gateway_client import GatewayClient
from app.guardrails import GuardConfig
from app.loop import AgentRunner, get_owned_conversation
from app.models import Conversation, Message, Trace, TraceEvent
from app.schemas import ChatIn, ChatOut, ConversationOut, ConversationSummaryOut, MessageOut, TicketCallbackIn, TraceEventOut, TraceOut

logger = logging.getLogger(__name__)
router = APIRouter()

INTERNAL_SECRET_HEADER = "X-Internal-Secret"
_customer_or_staff = require_roles("customer", "staff")


def _internal_ok(secret: str | None, settings: Settings) -> bool:
    return bool(secret) and hmac.compare_digest(secret, settings.INTERNAL_SECRET)


def _guard_config(settings: Settings, override: str | None, secret: str | None) -> GuardConfig:
    """X-Guard-Config lets eval compare guardrail setups; only honored with the internal secret."""
    base = GuardConfig.from_settings(settings)
    if not override:
        return base
    if not _internal_ok(secret, settings):
        raise AppError(403, "forbidden", "X-Guard-Config chỉ dùng được kèm X-Internal-Secret")
    try:
        return base.override(json.loads(override))
    except (ValueError, AttributeError):
        raise AppError(400, "bad_request", "X-Guard-Config phải là JSON object")


@router.post("/chat", response_model=ChatOut, summary="Gửi tin nhắn cho agent")
def chat(
    body: ChatIn,
    request: Request,
    user: CurrentUser = Depends(_customer_or_staff),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    x_guard_config: str | None = Header(None, alias="X-Guard-Config"),
    x_internal_secret: str | None = Header(None, alias=INTERNAL_SECRET_HEADER),
):
    guard = _guard_config(settings, x_guard_config, x_internal_secret)
    gateway = GatewayClient(request.app.state.http, settings.GATEWAY_URL, settings.AUTH_URL,
                            settings.TOOL_TIMEOUT_SECONDS)
    runner = AgentRunner(settings, request.app.state.llm, gateway, guard)
    result = runner.run(db, user, body.message, body.conversation_id)
    return ChatOut(**result.__dict__)


@router.get("/conversations", response_model=list[ConversationSummaryOut],
            summary="Các hội thoại của user hiện tại, mới hoạt động nhất trước")
def list_conversations(
    limit: int = Query(20, ge=1, le=100),
    user: CurrentUser = Depends(_customer_or_staff),
    db: Session = Depends(get_db),
):
    last_id = func.max(Message.id).label("last_id")
    stats = (
        select(Message.conversation_id, last_id, func.max(Message.created_at).label("last_at"))
        .group_by(Message.conversation_id)
        .subquery()
    )
    rows = db.execute(
        select(Conversation, stats.c.last_at)
        .join(stats, stats.c.conversation_id == Conversation.id)
        .where(Conversation.user_id == user.id)
        .order_by(stats.c.last_id.desc())
        .limit(limit)
    ).all()
    out = []
    for conv, last_at in rows:
        first = db.scalar(
            select(Message.content)
            .where(Message.conversation_id == conv.id, Message.role == "user")
            .order_by(Message.id)
            .limit(1)
        )
        out.append(ConversationSummaryOut(id=conv.id, created_at=conv.created_at, last_message_at=last_at,
                                          title=(first or "")[:60]))
    return out


@router.get("/conversations/{conversation_id}", response_model=ConversationOut, summary="Lịch sử hội thoại")
def get_conversation(
    conversation_id: str,
    user: CurrentUser = Depends(_customer_or_staff),
    db: Session = Depends(get_db),
):
    conv = get_owned_conversation(db, conversation_id, user)
    messages = db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)).all()
    return ConversationOut(id=conv.id, user_id=conv.user_id, created_at=conv.created_at,
                           messages=[MessageOut.model_validate(m) for m in messages])


@router.get("/traces/{trace_id}", response_model=TraceOut, summary="(staff) Chi tiết trace")
def get_trace(trace_id: str, _: CurrentUser = Depends(require_roles("staff")), db: Session = Depends(get_db)):
    trace = db.get(Trace, trace_id)
    if trace is None:
        raise AppError(404, "trace_not_found", "Không tìm thấy trace")
    events = db.scalars(select(TraceEvent).where(TraceEvent.trace_id == trace_id).order_by(TraceEvent.id)).all()
    out = TraceOut.model_validate(trace)
    out.events = [TraceEventOut.model_validate(e) for e in events]
    return out


@router.post("/internal/ticket-callback", summary="(Approval) ticket đã kết thúc -> thêm thông báo vào hội thoại")
def ticket_callback(
    body: TicketCallbackIn,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    x_internal_secret: str | None = Header(None, alias=INTERNAL_SECRET_HEADER),
):
    if not _internal_ok(x_internal_secret, settings):
        raise AppError(403, "forbidden", "Chỉ dành cho service nội bộ")
    conv = db.get(Conversation, body.conversation_id)
    if conv is None:
        raise AppError(404, "conversation_not_found", "Không tìm thấy hội thoại")
    text = prompts.ticket_notification(body.model_dump())
    db.add(Message(conversation_id=conv.id, role="system", content=text, kind="notification"))
    db.commit()
    logger.info("ticket %s (%s) notified in conversation %s", body.id, body.status, conv.id)
    return {"ok": True, "message": text}

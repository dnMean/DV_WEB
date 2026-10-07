import hashlib
import hmac
import json
import logging
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from opspilot_common.auth import CurrentUser, get_optional_user, require_roles
from opspilot_common.errors import AppError
from opspilot_common.logging import forward_headers
from opspilot_common.tools import agent_tool

from app.config import Settings, get_settings
from app.db import get_db
from app.models import DEDUP_STATUSES, Ticket, TicketStatus
from app.schemas import ReviewIn, TicketCreate, TicketOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tickets", tags=["tickets"])

INTERNAL_SECRET_HEADER = "X-Internal-Secret"
_staff = require_roles("staff")


def _is_internal(request: Request, settings: Settings) -> bool:
    secret = request.headers.get(INTERNAL_SECRET_HEADER)
    return bool(secret) and hmac.compare_digest(secret, settings.INTERNAL_SECRET)


def _require_internal(request: Request, settings: Settings = Depends(get_settings)) -> None:
    if not _is_internal(request, settings):
        raise AppError(403, "forbidden", "Chỉ dành cho service nội bộ")


def dedup_key(user_id: int, tool: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(f"{user_id}|{tool}|{canonical}".encode()).hexdigest()


TicketId = Annotated[str, Path(min_length=8, max_length=36, pattern=r"^[0-9a-fA-F-]+$",
                               description="Mã ticket: đủ 36 ký tự hoặc 8 ký tự đầu")]


def _get(db: Session, ticket_id: str) -> Ticket:
    """Accepts a full id or a unique prefix of at least 8 characters."""
    ticket_id = ticket_id.lower()
    if len(ticket_id) == 36:
        ticket = db.get(Ticket, ticket_id)
    else:
        matches = db.scalars(select(Ticket).where(Ticket.id.like(f"{ticket_id}%")).limit(2)).all()
        if len(matches) > 1:
            raise AppError(409, "ticket_id_ambiguous", f"Có nhiều ticket bắt đầu bằng {ticket_id}, hãy nhập đủ mã")
        ticket = matches[0] if matches else None
    if ticket is None:
        raise AppError(404, "ticket_not_found", f"Không tìm thấy ticket {ticket_id}")
    return ticket


def _http(request: Request) -> httpx.Client:
    return request.app.state.http


def _claim(db: Session, ticket_id: str, new_status: TicketStatus, reviewer: CurrentUser, note: str) -> Ticket:
    """Atomically move PENDING -> new_status so two reviewers cannot both act on one ticket."""
    ticket = _get(db, ticket_id)
    res = db.execute(
        update(Ticket)
        .where(Ticket.id == ticket.id, Ticket.status == TicketStatus.PENDING.value)
        .values(status=new_status.value, reviewer_id=reviewer.id, review_note=note or None)
    )
    db.commit()
    if res.rowcount != 1:
        db.refresh(ticket)
        raise AppError(409, "ticket_not_pending", f"Ticket đang ở trạng thái {ticket.status}, không thể duyệt/từ chối")
    db.refresh(ticket)
    return ticket


def _notify_agent(request: Request, settings: Settings, ticket: Ticket) -> None:
    if not ticket.conversation_id:
        return
    payload = TicketOut.model_validate(ticket).model_dump(mode="json")
    try:
        resp = _http(request).post(
            f"{settings.AGENT_URL}/internal/ticket-callback", json=payload,
            headers={INTERNAL_SECRET_HEADER: settings.INTERNAL_SECRET, **forward_headers()}, timeout=5.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("agent callback failed for ticket %s: %s", ticket.id, exc)


@router.post("", response_model=TicketOut, dependencies=[Depends(_require_internal)],
             summary="(Gateway) tạo ticket; trả ticket cũ nếu đã có yêu cầu giống hệt đang chờ/đã thực hiện")
def create_ticket(body: TicketCreate, response: Response, db: Session = Depends(get_db)):
    key = dedup_key(body.user_id, body.tool, body.dedup_arguments or body.arguments)
    matches = db.scalars(
        select(Ticket)
        .where(Ticket.dedup_key == key, Ticket.status.in_([s.value for s in DEDUP_STATUSES]))
        .order_by(Ticket.created_at.desc())
    ).all()
    # an already executed identical request wins over a pending one
    existing = next((t for t in matches if t.status == TicketStatus.EXECUTED), matches[0] if matches else None)
    if existing is not None:
        logger.info("duplicate request for ticket %s (%s)", existing.id, existing.status)
        return existing
    ticket = Ticket(conversation_id=body.conversation_id, user_id=body.user_id, tool=body.tool,
                    arguments=body.arguments, dedup_key=key)
    db.add(ticket)
    db.commit()
    response.status_code = 201
    logger.info("ticket %s created: user=%s tool=%s", ticket.id, body.user_id, body.tool)
    return ticket


@router.get(
    "", response_model=list[TicketOut],
    summary="(staff) Danh sách ticket (UI)",
)
def list_tickets(
    status: TicketStatus | None = Query(None, description="Lọc theo trạng thái, vd PENDING"),
    limit: int = Query(20, ge=1, le=200, description="Số ticket tối đa"),
    _: CurrentUser = Depends(_staff),
    db: Session = Depends(get_db),
):
    stmt = select(Ticket).order_by(Ticket.created_at.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(Ticket.status == status.value)
    return db.scalars(stmt).all()


@router.get(
    "/{ticket_id}", response_model=TicketOut,
    summary="Xem trạng thái một yêu cầu (ticket)",
    description=("Dùng khi user hỏi yêu cầu hoàn tiền / ticket có mã cụ thể đang ở trạng thái nào. "
                 "Khách chỉ xem được ticket của chính mình."),
    openapi_extra=agent_tool("get_approval_ticket", "low", ["customer", "staff"]),
)
def get_ticket(
    ticket_id: TicketId,
    request: Request,
    user: CurrentUser | None = Depends(get_optional_user),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    if _is_internal(request, settings):
        return _get(db, ticket_id)
    if user is None:
        raise AppError(401, "unauthorized", "Thiếu token xác thực")
    ticket = _get(db, ticket_id)
    if not user.is_staff and ticket.user_id != user.id:
        raise AppError(403, "forbidden", "Bạn không có quyền xem ticket này")
    return ticket


def do_approve(request: Request, settings: Settings, db: Session, ticket_id: str, reviewer: CurrentUser,
               note: str) -> Ticket:
    ticket = _claim(db, ticket_id, TicketStatus.APPROVED, reviewer, note)
    ticket_id = ticket.id
    logger.info("ticket %s approved by %s", ticket_id, reviewer.id)
    try:
        resp = _http(request).post(
            f"{settings.GATEWAY_URL}/internal/execute-ticket/{ticket_id}",
            headers={INTERNAL_SECRET_HEADER: settings.INTERNAL_SECRET, **forward_headers()},
            timeout=settings.EXECUTE_TIMEOUT_SECONDS,
        )
        result = resp.json()
        if not resp.is_success and "status" not in result:
            result = {"status": "error", "error": result.get("error", "gateway_error"),
                      "message": result.get("message", "")}
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("execute-ticket %s failed: %s", ticket_id, exc)
        result = {"status": "error", "error": "gateway_unavailable", "message": "Không gọi được Gateway"}

    ticket.result = result
    ticket.status = (TicketStatus.EXECUTED if result.get("status") == "ok" else TicketStatus.FAILED).value
    db.commit()
    logger.info("ticket %s -> %s", ticket_id, ticket.status)
    _notify_agent(request, settings, ticket)
    return ticket


def do_reject(request: Request, settings: Settings, db: Session, ticket_id: str, reviewer: CurrentUser,
              note: str) -> Ticket:
    ticket = _claim(db, ticket_id, TicketStatus.REJECTED, reviewer, note)
    logger.info("ticket %s rejected by %s", ticket.id, reviewer.id)
    _notify_agent(request, settings, ticket)
    return ticket


@router.post("/{ticket_id}/approve", response_model=TicketOut, summary="(staff) Duyệt và thực thi ticket (UI)")
def approve(
    ticket_id: TicketId,
    body: ReviewIn,
    request: Request,
    reviewer: CurrentUser = Depends(_staff),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    return do_approve(request, settings, db, ticket_id, reviewer, body.note)


@router.post("/{ticket_id}/reject", response_model=TicketOut, summary="(staff) Từ chối ticket (UI)")
def reject(
    ticket_id: TicketId,
    body: ReviewIn,
    request: Request,
    reviewer: CurrentUser = Depends(_staff),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    return do_reject(request, settings, db, ticket_id, reviewer, body.note)

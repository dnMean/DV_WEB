import hmac
import re
import json
import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from opspilot_common.auth import CurrentUser, create_system_token, get_current_user, require_roles
from opspilot_common.errors import AppError
from opspilot_common.logging import forward_headers, get_request_id

from app import invoker
from app.config import Settings, get_settings
from app.registry import Registry, ToolSpec
from app.schemas import InvokeIn

logger = logging.getLogger(__name__)
router = APIRouter()

INTERNAL_SECRET_HEADER = "X-Internal-Secret"


def _registry(request: Request) -> Registry:
    return request.app.state.registry


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


def check_internal_secret(secret: str | None, settings: Settings) -> None:
    if not secret or not hmac.compare_digest(secret, settings.INTERNAL_SECRET):
        raise AppError(403, "forbidden", "Sai hoặc thiếu X-Internal-Secret")


@router.get("/tools", summary="Tool definitions (OpenAI function-calling) cho role hiện tại")
def list_tools(request: Request, user: CurrentUser = Depends(get_current_user)) -> list[dict[str, Any]]:
    return [t.to_openai() for t in _registry(request).for_role(user.role)]


@router.get("/tools/meta", summary="(staff) Toàn bộ ToolSpec kèm risk, roles")
def tools_meta(request: Request, _: CurrentUser = Depends(require_roles("staff"))) -> list[dict[str, Any]]:
    return [t.meta() for t in _registry(request).all()]


@router.get("/audit", summary="(staff) Các dòng audit log gần nhất")
def audit_tail(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    _: CurrentUser = Depends(require_roles("staff")),
) -> list[dict[str, Any]]:
    return request.app.state.audit.tail(limit)


_EXISTING_STATE = {
    "PENDING": "đang chờ nhân viên duyệt",
    "APPROVED": "đã được duyệt, đang thực hiện",
    "EXECUTED": "đã được duyệt và thực hiện",
}


async def _create_ticket(request: Request, settings: Settings, user: CurrentUser,
                         spec: ToolSpec, arguments: dict, conversation_id: str) -> tuple[int, dict]:
    try:
        resp = await _client(request).post(
            f"{settings.APPROVAL_URL}/tickets",
            json={
                "conversation_id": conversation_id, "user_id": user.id, "tool": spec.name, "arguments": arguments,
                "dedup_arguments": (
                    {k: arguments.get(k) for k in spec.dedup_fields} if spec.dedup_fields else arguments
                ),
            },
            headers={INTERNAL_SECRET_HEADER: settings.INTERNAL_SECRET, **forward_headers()},
            timeout=settings.TOOL_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        ticket = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("cannot create approval ticket: %s", exc)
        return 503, invoker.error("approval_unavailable", "Không tạo được yêu cầu duyệt, vui lòng thử lại sau")

    if resp.status_code != 201:  # Approval returned an existing ticket for the same request
        state = _EXISTING_STATE.get(ticket["status"], ticket["status"])
        return 200, invoker.error(
            "duplicate_request",
            f"Đã có yêu cầu {spec.name} cho cùng đối tượng {state} (ticket {ticket['id']}, "
            f"tham số {json.dumps(ticket['arguments'], ensure_ascii=False)}). Yêu cầu mới bị từ chối, "
            "không tạo ticket mới.",
            ticket_id=ticket["id"], existing_status=ticket["status"], existing_arguments=ticket["arguments"],
        )
    return 200, {
        "status": "pending_approval",
        "ticket_id": ticket["id"],
        "message": "Thao tác rủi ro cao: đã tạo yêu cầu, đang chờ nhân viên duyệt.",
    }


async def _invoke(request: Request, body: InvokeIn, user: CurrentUser, settings: Settings) -> tuple[int, dict]:
    spec = _registry(request).get(body.tool)
    # 1. existence + role
    if spec is None or user.role not in spec.roles:
        return 403, invoker.error("tool_forbidden", f"Tool '{body.tool}' không tồn tại hoặc bạn không có quyền dùng")

    # 2. schema validation
    arguments = invoker.coerce_arguments(spec, body.arguments)
    problem = invoker.validate_arguments(spec, arguments)
    if problem:
        return 422, invoker.error("invalid_arguments", problem)

    # 2b. confirmation: some arguments must come from the user's own words, not from the LLM
    for arg in spec.confirm_args or []:
        value = str(arguments.get(arg, "")).strip()
        typed = re.search(rf"(?<![0-9A-Za-z]){re.escape(value)}(?![0-9A-Za-z])", body.user_message, re.IGNORECASE)
        if not value or not typed:
            return 403, invoker.error(
                "confirmation_required",
                f"Để dùng '{spec.name}', người dùng phải tự gõ {arg} '{arguments.get(arg, '')}' trong tin nhắn "
                "của mình. Hãy hỏi người dùng xác nhận bằng cách nhập mã đó.",
            )

    # 3. rate limit per (user, tool)
    if not spec.is_write:
        per_minute = settings.RATE_LIMIT_READ_PER_MIN
    elif user.is_staff:
        per_minute = settings.RATE_LIMIT_STAFF_WRITE_PER_MIN
    else:
        per_minute = settings.RATE_LIMIT_WRITE_PER_MIN
    allowed, retry_after = request.app.state.limiter.allow((user.id, spec.name), per_minute)
    if not allowed:
        return 429, invoker.error(
            "rate_limited", f"Gọi '{spec.name}' quá {per_minute} lần/phút, thử lại sau {retry_after:.0f}s",
            retry_after=round(retry_after, 1),
        )

    # 4. high risk -> precheck on the service, then an approval ticket; the action itself is NOT executed
    if spec.risk == "high":
        if spec.precheck:
            rejected = await invoker.precheck(
                _client(request), spec, arguments, {"Authorization": f"Bearer {user.token}", **forward_headers()},
                timeout=settings.TOOL_TIMEOUT_SECONDS,
            )
            if rejected:
                return 200, rejected
        return await _create_ticket(request, settings, user, spec, arguments, body.conversation_id)

    # 5-7. forward to the service
    headers = {"Authorization": f"Bearer {user.token}", **forward_headers()}
    if spec.is_write:
        headers["Idempotency-Key"] = invoker.idempotency_key(user.id, spec.name, arguments, body.conversation_id)
    result = await invoker.call_service(
        _client(request), spec, arguments, headers,
        timeout=settings.TOOL_TIMEOUT_SECONDS, max_chars=settings.TOOL_MAX_RESULT_CHARS,
    )
    return 200, result


@router.post("/invoke", summary="Thực thi một tool (pipeline: authz, validate, rate limit, approval, forward)")
async def invoke(
    body: InvokeIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    start = time.perf_counter()
    status_code, result = await _invoke(request, body, user, settings)
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    request.app.state.audit.write(
        request_id=get_request_id(), user_id=user.id, tool=body.tool, arguments=body.arguments,
        status=result.get("status"), error=result.get("error"), latency_ms=latency_ms,
        conversation_id=body.conversation_id, ticket_id=result.get("ticket_id"),
    )
    return JSONResponse(status_code=status_code, content=result)


@router.post("/internal/execute-ticket/{ticket_id}", summary="(Approval) thực thi ticket đã duyệt")
async def execute_ticket(
    ticket_id: str,
    request: Request,
    x_internal_secret: str | None = Header(None, alias=INTERNAL_SECRET_HEADER),
    settings: Settings = Depends(get_settings),
):
    check_internal_secret(x_internal_secret, settings)
    start = time.perf_counter()
    internal = {INTERNAL_SECRET_HEADER: settings.INTERNAL_SECRET, **forward_headers()}
    try:
        resp = await _client(request).get(f"{settings.APPROVAL_URL}/tickets/{ticket_id}", headers=internal, timeout=5.0)
    except httpx.HTTPError:
        raise AppError(503, "approval_unavailable", "Không đọc được ticket từ Approval")
    if resp.status_code == 404:
        raise AppError(404, "ticket_not_found", f"Không tìm thấy ticket {ticket_id}")
    resp.raise_for_status()
    ticket = resp.json()
    if ticket["status"] != "APPROVED" or ticket.get("result") is not None:
        raise AppError(409, "ticket_not_executable", f"Ticket đang ở trạng thái {ticket['status']}")

    spec = _registry(request).get(ticket["tool"])
    if spec is None:
        result = invoker.error("tool_not_found", f"Tool '{ticket['tool']}' không còn trong registry")
    else:
        arguments = invoker.coerce_arguments(spec, ticket["arguments"])
        problem = invoker.validate_arguments(spec, arguments)
        if problem:
            result = invoker.error("invalid_arguments", problem)
        else:
            headers = {
                "Authorization": f"Bearer {create_system_token()}",
                "X-On-Behalf-Of": str(ticket["user_id"]),
                "Idempotency-Key": ticket_id,
                **forward_headers(),
            }
            result = await invoker.call_service(
                _client(request), spec, arguments, headers,
                timeout=settings.TOOL_TIMEOUT_SECONDS, max_chars=settings.TOOL_MAX_RESULT_CHARS,
            )
    request.app.state.audit.write(
        request_id=get_request_id(), user_id=ticket["user_id"], tool=ticket["tool"], arguments=ticket["arguments"],
        status=result.get("status"), error=result.get("error"),
        latency_ms=round((time.perf_counter() - start) * 1000, 1), ticket_id=ticket_id, via="system",
    )
    return result

import logging

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from opspilot_common.auth import CurrentUser, require_roles
from opspilot_common.errors import AppError
from opspilot_common.tools import agent_tool

from app.db import get_db
from app.models import Payment, PaymentStatus, Refund
from app.outbox import outbox
from app.policy import Dependencies, evaluate
from app.schemas import EligibilityOut, PaymentOut, RefundCheckOut, RefundIn, RefundOut, RefundResultOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["payments"])


def _payment_for_order(db: Session, order_id: int, *, lock: bool = False) -> Payment:
    stmt = select(Payment).where(Payment.order_id == order_id)
    if lock:
        stmt = stmt.with_for_update()
    payment = db.scalar(stmt)
    if payment is None:
        raise AppError(404, "payment_not_found", f"Đơn {order_id} chưa có thanh toán nào")
    return payment


def _result(refund: Refund, payment: Payment, replayed: bool) -> RefundResultOut:
    return RefundResultOut(
        refund=RefundOut.model_validate(refund), replayed=replayed,
        refundable_amount=payment.refundable_amount,
    )


@router.get(
    "/payments",
    response_model=PaymentOut,
    summary="Xem thanh toán của một đơn hàng",
    description=(
        "Dùng khi user hỏi đơn đã thanh toán chưa, thanh toán bao nhiêu, bằng phương thức nào, "
        "đã hoàn tiền bao nhiêu và còn hoàn được bao nhiêu. Cần order_id."
    ),
    openapi_extra=agent_tool("get_payment", "low", ["customer", "staff"]),
)
def get_payment(
    order_id: int = Query(..., ge=1, description="Mã đơn hàng"),
    user: CurrentUser = Depends(require_roles("customer", "staff")),
    db: Session = Depends(get_db),
):
    payment = _payment_for_order(db, order_id)
    if not user.is_staff and payment.user_id != user.id:
        raise AppError(403, "forbidden", "Bạn không có quyền xem thanh toán của đơn hàng này")
    return payment


def _deps(request: Request) -> Dependencies:
    return Dependencies(request.app.state.http)


@router.get(
    "/refunds/eligibility",
    response_model=EligibilityOut,
    summary="Kiểm tra đơn hàng có được hoàn tiền không",
    description=(
        "Dùng khi user hỏi đơn có hoàn tiền được không, được hoàn tối đa bao nhiêu, hoặc muốn hoàn tiền nhưng "
        "chưa nêu số tiền. Trả eligible, lý do (order_in_transit, order_not_paid, order_not_refundable), "
        "số tiền tối đa và có bắt buộc hoàn toàn bộ không. Chỉ đọc, không tạo yêu cầu. Cần order_id."
    ),
    openapi_extra=agent_tool("check_refund_eligibility", "low", ["customer", "staff"]),
)
def refund_eligibility(
    request: Request,
    order_id: int = Query(..., ge=1, description="Mã đơn hàng"),
    user: CurrentUser = Depends(require_roles("customer", "staff")),
    db: Session = Depends(get_db),
):
    try:
        check = evaluate(db, _deps(request), user, order_id, None)
    except AppError as exc:
        if exc.status_code != 409:  # 403/404/503 stay errors
            raise
        return EligibilityOut(order_id=order_id, eligible=False, reason=exc.error, message=exc.message,
                              max_refundable=0, full_refund_required=False)
    if check.before_shipping:
        message = (f"Đơn đã thanh toán nhưng chưa giao: chỉ có thể hoàn toàn bộ {check.refundable:,}đ, "
                   "đơn sẽ bị huỷ khi yêu cầu được duyệt.")
    else:
        message = f"Đơn đã giao: có thể hoàn một phần hoặc toàn bộ, tối đa {check.refundable:,}đ."
    return EligibilityOut(order_id=order_id, eligible=True, reason="ok", message=message + " Cần nhân viên duyệt.",
                          max_refundable=check.refundable, full_refund_required=check.before_shipping)


@router.post(
    "/refunds/validate",
    response_model=RefundCheckOut,
    summary="Kiểm tra yêu cầu hoàn tiền có hợp lệ không (không thay đổi dữ liệu)",
    description="Gateway gọi trước khi tạo ticket duyệt (precheck của refund_payment).",
)
def validate_refund(
    body: RefundIn,
    request: Request,
    user: CurrentUser = Depends(require_roles("customer", "staff", "system")),
    db: Session = Depends(get_db),
):
    check = evaluate(db, _deps(request), user, body.order_id, body.amount)
    return RefundCheckOut(eligible=True, order_status=check.order["status"],
                          refundable_amount=check.refundable, full_refund_required=check.before_shipping)


@router.post(
    "/refunds",
    response_model=RefundResultOut,
    summary="Tạo yêu cầu hoàn tiền cho đơn hàng",
    description=(
        "Chỉ dùng khi chính khách yêu cầu hoàn tiền rõ ràng và đã có mã đơn, số tiền, lý do. "
        "Yêu cầu được nhân viên duyệt trước khi thực hiện. Chính sách: đơn đã thanh toán nhưng chưa giao "
        "chỉ được hoàn TOÀN BỘ số tiền (đơn sẽ bị huỷ); đơn đang giao (SHIPPING) không hoàn được, khách "
        "nhận hàng rồi yêu cầu; đơn đã giao được hoàn một phần hoặc toàn bộ; đơn chưa thanh toán thì dùng "
        "cancel_order. Mỗi đơn chỉ có một yêu cầu hoàn tiền."
    ),
    openapi_extra=agent_tool("refund_payment", "high", ["customer"],
                             dedup_fields=["order_id"], precheck="/refunds/validate"),
)
def create_refund(
    body: RefundIn,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=128),
    user: CurrentUser = Depends(require_roles("system", "staff")),
    db: Session = Depends(get_db),
):
    if not idempotency_key:
        raise AppError(400, "idempotency_key_required", "Thiếu header Idempotency-Key")

    existing = db.scalar(select(Refund).where(Refund.idempotency_key == idempotency_key))
    if existing is not None:
        if existing.order_id != body.order_id or existing.amount != body.amount:
            raise AppError(409, "idempotency_key_conflict", "Idempotency-Key đã dùng cho một yêu cầu khác")
        return _result(existing, existing.payment, replayed=True)

    # rules are re-checked at execution time: the order may have changed since the ticket was created
    deps = _deps(request)
    check = evaluate(db, deps, user, body.order_id, body.amount, lock=True)
    payment = check.payment
    if check.before_shipping:
        # stop the parcel first; if it already left, no money moves
        deps.cancel_shipment(body.order_id, key=idempotency_key)

    refund = Refund(
        payment_id=payment.id, order_id=payment.order_id, user_id=payment.user_id,
        amount=body.amount, reason=body.reason, idempotency_key=idempotency_key,
        requested_by=user.on_behalf_of if user.is_system else user.id, requested_role=user.role,
    )
    payment.refunds.append(refund)
    payment.status = (
        PaymentStatus.REFUNDED if payment.refundable_amount == 0 else PaymentStatus.PARTIALLY_REFUNDED
    ).value
    outbox.add(db, "order", f"/internal/orders/{payment.order_id}/refund-applied",
               {"total_refunded": payment.refunded_amount, "full": payment.refundable_amount == 0},
               key=f"order-{payment.order_id}-refunded-{payment.refunded_amount}")
    try:
        db.commit()
    except IntegrityError:  # same key committed concurrently
        db.rollback()
        existing = db.scalar(select(Refund).where(Refund.idempotency_key == idempotency_key))
        return _result(existing, existing.payment, replayed=True)
    outbox.flush()
    logger.info("refund %s created: order=%s amount=%s by %s", refund.id, refund.order_id, refund.amount, user.role)
    return _result(refund, payment, replayed=False)

"""Service-to-service endpoints (see docs/USECASES.md section 4). All are idempotent."""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from opspilot_common.auth import require_internal
from opspilot_common.errors import AppError

from app.db import get_db
from app.models import Payment, PaymentStatus
from app.schemas import ChargeIn, PaymentOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/payments", tags=["internal"], dependencies=[Depends(require_internal)])


@router.post("", response_model=PaymentOut, summary="(Order) Ghi nhận thanh toán giả lập của một đơn")
def charge(body: ChargeIn, db: Session = Depends(get_db)):
    """Simulated payment: always succeeds. One payment per order, so a retried call returns the same row."""
    existing = db.scalar(select(Payment).where(Payment.order_id == body.order_id))
    if existing is None:
        db.add(Payment(order_id=body.order_id, user_id=body.user_id, amount=body.amount, method=body.method,
                       status=PaymentStatus.SUCCESS.value))
        try:
            db.commit()
            logger.info("payment for order %s: %s via %s", body.order_id, body.amount, body.method)
        except IntegrityError:  # same order charged concurrently
            db.rollback()
        existing = db.scalar(select(Payment).where(Payment.order_id == body.order_id))
    if (existing.user_id, existing.amount) != (body.user_id, body.amount):
        raise AppError(409, "payment_conflict", f"Đơn {body.order_id} đã có thanh toán với dữ liệu khác")
    return existing

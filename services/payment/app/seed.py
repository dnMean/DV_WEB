import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from opspilot_common import demo_data

from app.db import sync_sequence
from app.models import Payment, PaymentStatus, Refund

logger = logging.getLogger(__name__)

# One SUCCESS payment per order with status >= PAID (see services/order/app/seed.py).
# (id, order_id, user_id, amount, method)
PAYMENTS = [
    (1, 1001, 1, 350_000, "COD"),
    (2, 1002, 1, 1_200_000, "CARD"),
    (3, 1003, 1, 2_500_000, "BANK_TRANSFER"),
    (4, 1005, 2, 800_000, "E_WALLET"),
]


def seed(db: Session, extra: int | None = None) -> None:
    """Hand-written payments + payments/refunds of generated demo orders (default DEMO_EXTRA_ORDERS)."""
    if db.scalar(select(Payment.id).limit(1)) is not None:
        return
    for pid, order_id, user_id, amount, method in PAYMENTS:
        db.add(Payment(id=pid, order_id=order_id, user_id=user_id, amount=amount, method=method))
    now = datetime.now(timezone.utc)
    next_id = len(PAYMENTS) + 1
    count = len(PAYMENTS)
    for o in demo_data.generate(extra):
        if o.payment_method is None:
            continue
        paid_at = now - timedelta(days=o.days_ago, hours=o.id % 24)
        if o.refunded_amount == 0:
            status = PaymentStatus.SUCCESS
        elif o.refunded_amount == o.total:
            status = PaymentStatus.REFUNDED
        else:
            status = PaymentStatus.PARTIALLY_REFUNDED
        payment = Payment(id=next_id, order_id=o.id, user_id=o.user_id, amount=o.total, method=o.payment_method,
                          status=status.value, created_at=paid_at)
        if o.refunded_amount:
            payment.refunds.append(Refund(
                order_id=o.id, user_id=o.user_id, amount=o.refunded_amount, reason=o.refund_reason or "",
                idempotency_key=f"seed-{o.id}", requested_by=o.user_id, requested_role="system",
                created_at=paid_at + timedelta(days=min(2, o.days_ago)),
            ))
        db.add(payment)
        next_id += 1
        count += 1
    db.flush()
    sync_sequence(db, "payments")
    db.commit()
    logger.info("seeded %s payments", count)

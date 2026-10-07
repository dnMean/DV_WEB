import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from opspilot_common import demo_data

from app.models import Ticket
from app.routers.tickets import dedup_key

logger = logging.getLogger(__name__)

STAFF_ID = 3


def seed(db: Session, extra: int | None = None) -> None:
    """Refund tickets of generated demo orders (the hand-written orders 1001-1005 start without tickets)."""
    if db.scalar(select(Ticket.id).limit(1)) is not None:
        return
    now = datetime.now(timezone.utc)
    count = 0
    for o in demo_data.generate(extra):
        for t in o.tickets:
            created = now - timedelta(days=max(o.days_ago - 1, 0), hours=o.id % 24)
            db.add(Ticket(
                conversation_id="", user_id=o.user_id, tool="refund_payment",
                arguments={"order_id": o.id, "amount": t.amount, "reason": t.reason}, status=t.status,
                reviewer_id=None if t.status == "PENDING" else STAFF_ID, review_note=t.review_note,
                result={"status": "ok", "data": {"seeded": True}} if t.status == "EXECUTED" else None,
                dedup_key=dedup_key(o.user_id, "refund_payment", {"order_id": o.id}),
                created_at=created, updated_at=created,
            ))
            count += 1
    db.commit()
    if count:
        logger.info("seeded %s tickets", count)

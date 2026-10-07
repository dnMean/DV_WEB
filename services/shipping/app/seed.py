import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from opspilot_common import demo_data

from app.db import sync_sequence
from app.models import Shipment, ShipmentEvent, ShipmentStatus

logger = logging.getLogger(__name__)

_RECIPIENTS = {
    1: ("Nguyễn Thị Alice", "0901234567", "25 Trần Hưng Đạo, Hoàn Kiếm, Hà Nội"),
    2: ("Trần Văn Bob", "0912345678", "8 Nguyễn Văn Linh, Hải Châu, Đà Nẵng"),
}

# (id, order_id, user_id, status, tracking_code, [(status, location, description, days_ago)])
SHIPMENTS = [
    (1, 1001, 1, ShipmentStatus.DELIVERED, "GHN1001VN", [
        ("WAITING_PICKUP", "Kho TP.HCM", "Đã tạo vận đơn, chờ lấy hàng", 10),
        ("IN_TRANSIT", "Kho TP.HCM", "Đã lấy hàng", 9),
        ("IN_TRANSIT", "Kho Hà Nội", "Đã đến kho giao hàng", 7),
        ("DELIVERED", "Hoàn Kiếm, Hà Nội", "Giao hàng thành công", 6),
    ]),
    (2, 1002, 1, ShipmentStatus.IN_TRANSIT, "GHN1002VN", [
        ("IN_TRANSIT", "Kho TP.HCM", "Đã lấy hàng", 3),
        ("IN_TRANSIT", "Kho trung chuyển Đà Nẵng", "Đã đến kho trung chuyển", 2),
        ("IN_TRANSIT", "Đà Nẵng", "Đang vận chuyển đến kho Hà Nội", 1),
    ]),
    (3, 1003, 1, ShipmentStatus.WAITING_PICKUP, "GHN1003VN", [
        ("WAITING_PICKUP", "Kho TP.HCM", "Đã tạo vận đơn, chờ lấy hàng", 0),
    ]),
    (4, 1005, 2, ShipmentStatus.WAITING_PICKUP, "GHN1005VN", [
        ("WAITING_PICKUP", "Kho TP.HCM", "Đã tạo vận đơn, chờ lấy hàng", 0),
    ]),
]


def seed(db: Session, extra: int | None = None) -> None:
    """Hand-written shipments + shipments of generated demo orders (default DEMO_EXTRA_ORDERS)."""
    if db.scalar(select(Shipment.id).limit(1)) is not None:
        return
    now = datetime.now(timezone.utc)
    shipments = list(SHIPMENTS)
    for o in demo_data.generate(extra):
        if o.shipment_status:
            shipments.append((len(shipments) + 1, o.id, o.user_id, ShipmentStatus(o.shipment_status),
                              o.tracking_code, o.shipment_events))
    for sid, order_id, user_id, status, tracking, events in shipments:
        name, phone, address = _RECIPIENTS[user_id]
        db.add(Shipment(
            id=sid, order_id=order_id, user_id=user_id, status=status.value, carrier="GHN",
            tracking_code=tracking, recipient_name=name, recipient_phone=phone, address=address,
            events=[
                ShipmentEvent(status=s, location=loc, description=desc, occurred_at=now - timedelta(days=d))
                for s, loc, desc, d in events
            ],
        ))
    db.flush()
    sync_sequence(db, "shipments")
    db.commit()
    logger.info("seeded %s shipments", len(shipments))

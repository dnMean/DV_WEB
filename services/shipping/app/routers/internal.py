"""Service-to-service endpoints (see docs/USECASES.md section 4). All are idempotent."""
import logging

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from opspilot_common.auth import require_internal
from opspilot_common.errors import AppError

from app.db import get_db
from app.models import Shipment, ShipmentEvent, ShipmentStatus
from app.schemas import ShipmentCreateIn, ShipmentOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/shipments", tags=["internal"], dependencies=[Depends(require_internal)])


def _get(db: Session, order_id: int, *, lock: bool = False) -> Shipment:
    stmt = select(Shipment).where(Shipment.order_id == order_id)
    if lock:
        stmt = stmt.with_for_update()
    shipment = db.scalar(stmt)
    if shipment is None:
        raise AppError(404, "shipment_not_found", f"Đơn {order_id} chưa có vận đơn")
    return shipment


@router.post("", response_model=ShipmentOut, summary="(Order) Tạo vận đơn chờ lấy hàng cho đơn vừa thanh toán")
def create_shipment(body: ShipmentCreateIn, db: Session = Depends(get_db)):
    """One shipment per order: a retried call returns the existing one."""
    shipment = db.scalar(select(Shipment).where(Shipment.order_id == body.order_id))
    if shipment is not None:
        return shipment
    shipment = Shipment(
        order_id=body.order_id, user_id=body.user_id, status=ShipmentStatus.WAITING_PICKUP.value, carrier="GHN",
        tracking_code=f"GHN{body.order_id}VN", recipient_name=body.recipient_name,
        recipient_phone=body.recipient_phone, address=body.address,
        events=[ShipmentEvent(status=ShipmentStatus.WAITING_PICKUP.value, location="Kho TP.HCM",
                              description="Đã tạo vận đơn, chờ lấy hàng")],
    )
    db.add(shipment)
    try:
        db.commit()
    except IntegrityError:  # same order created concurrently
        db.rollback()
        return db.scalar(select(Shipment).where(Shipment.order_id == body.order_id))
    logger.info("shipment created for order %s", body.order_id)
    return shipment


@router.get("/{order_id}", response_model=ShipmentOut)
def get_shipment(order_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    return _get(db, order_id)


@router.post("/{order_id}/cancel", response_model=ShipmentOut, summary="Huỷ vận đơn chưa lấy hàng (do hoàn tiền)")
def cancel_shipment(order_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    shipment = _get(db, order_id, lock=True)
    if shipment.status == ShipmentStatus.CANCELLED:
        return shipment
    if shipment.status != ShipmentStatus.WAITING_PICKUP:
        raise AppError(409, "shipment_already_dispatched",
                       f"Vận đơn đơn {order_id} đang ở trạng thái {shipment.status}, không thể huỷ")
    shipment.status = ShipmentStatus.CANCELLED.value
    shipment.events.append(ShipmentEvent(status=shipment.status, location="Hệ thống",
                                         description="Huỷ vận đơn do đơn hàng được hoàn tiền"))
    db.commit()
    logger.info("shipment for order %s cancelled", order_id)
    return shipment

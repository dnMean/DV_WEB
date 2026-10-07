import logging

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from opspilot_common.auth import CurrentUser, require_roles
from opspilot_common.errors import AppError
from opspilot_common.tools import agent_tool

from app.db import get_db
from app.models import Shipment, ShipmentEvent, ShipmentStatus
from app.outbox import outbox
from app.schemas import AddressUpdateIn, AdvanceIn, ShipmentOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["shipments"])

_customer_or_staff = require_roles("customer", "staff")


def _get_owned_shipment(db: Session, order_id: int, user: CurrentUser) -> Shipment:
    shipment = db.scalar(select(Shipment).where(Shipment.order_id == order_id))
    if shipment is None:
        raise AppError(404, "shipment_not_found", f"Đơn {order_id} chưa có vận đơn")
    if not user.is_staff and shipment.user_id != user.id:
        raise AppError(403, "forbidden", "Bạn không có quyền xem vận đơn của đơn hàng này")
    return shipment


@router.get("/shipments", response_model=list[ShipmentOut], summary="(staff) Danh sách vận đơn (UI kho)")
def list_shipments(
    status: ShipmentStatus | None = None,
    limit: int = 500,
    _: CurrentUser = Depends(require_roles("staff")),
    db: Session = Depends(get_db),
):
    stmt = select(Shipment).order_by(Shipment.order_id.desc()).limit(min(max(limit, 1), 1000))
    if status is not None:
        stmt = stmt.where(Shipment.status == status.value)
    return db.scalars(stmt).all()


@router.get(
    "/shipments/{order_id}",
    response_model=ShipmentOut,
    summary="Tra cứu vận chuyển của đơn hàng",
    description=(
        "Dùng khi user hỏi đơn đang giao tới đâu, đã lấy hàng chưa, mã vận đơn, địa chỉ nhận hàng "
        "hoặc lịch sử vận chuyển. Cần order_id."
    ),
    openapi_extra=agent_tool("get_shipment", "low", ["customer", "staff"]),
)
def get_shipment(
    order_id: int = Path(..., ge=1, description="Mã đơn hàng"),
    user: CurrentUser = Depends(_customer_or_staff),
    db: Session = Depends(get_db),
):
    return _get_owned_shipment(db, order_id, user)


@router.put(
    "/shipments/{order_id}/address",
    response_model=ShipmentOut,
    summary="Đổi địa chỉ giao hàng",
    description=(
        "Dùng khi user yêu cầu rõ ràng đổi địa chỉ nhận hàng và đã cung cấp địa chỉ mới đầy đủ. "
        "Hệ thống tự kiểm tra (chỉ đổi được khi chưa lấy hàng) và trả lỗi nếu không đổi được."
    ),
    openapi_extra=agent_tool("update_shipping_address", "medium", ["customer", "staff"]),
)
def update_address(
    body: AddressUpdateIn,
    order_id: int = Path(..., ge=1, description="Mã đơn hàng"),
    user: CurrentUser = Depends(_customer_or_staff),
    db: Session = Depends(get_db),
):
    shipment = _get_owned_shipment(db, order_id, user)
    if shipment.status != ShipmentStatus.WAITING_PICKUP:
        raise AppError(
            409, "shipment_not_editable",
            f"Vận đơn của đơn {order_id} đang ở trạng thái {shipment.status}, không thể đổi địa chỉ.",
        )
    new_name = body.recipient_name or shipment.recipient_name
    new_phone = body.recipient_phone or shipment.recipient_phone
    if (body.address, new_name, new_phone) == (shipment.address, shipment.recipient_name, shipment.recipient_phone):
        return shipment  # idempotent: nothing changed
    shipment.address, shipment.recipient_name, shipment.recipient_phone = body.address, new_name, new_phone
    shipment.events.append(ShipmentEvent(
        status=shipment.status, location="Hệ thống", description="Cập nhật địa chỉ giao hàng",
    ))
    db.commit()
    logger.info("shipment for order %s address updated by user %s", order_id, user.id)
    return shipment


_ADVANCE = {  # current status -> allowed next statuses
    ShipmentStatus.WAITING_PICKUP: {"IN_TRANSIT"},
    ShipmentStatus.IN_TRANSIT: {"IN_TRANSIT", "DELIVERED"},
}


@router.post(
    "/shipments/{order_id}/advance",
    response_model=ShipmentOut,
    summary="Cập nhật trạng thái vận chuyển của đơn (staff)",
    description=(
        "Chỉ dành cho staff: khi staff báo một đơn cụ thể đã được lấy hàng / đang giao / đang ở vị trí nào "
        "(status=IN_TRANSIT) hoặc đã giao thành công (status=DELIVERED). Gọi ngay khi tin nhắn có mã đơn, không tự "
        "đoán trạng thái: hệ thống tự kiểm tra và trả lỗi nếu không chuyển được. Trạng thái đơn hàng tự đồng bộ "
        "theo vận đơn. Mỗi lần một đơn."
    ),
    openapi_extra=agent_tool("update_shipment_status", "medium", ["staff"], confirm_args=["order_id"]),
)
def advance_shipment(
    body: AdvanceIn,
    order_id: int = Path(..., ge=1),
    user: CurrentUser = Depends(require_roles("staff")),
    db: Session = Depends(get_db),
):
    shipment = db.scalar(select(Shipment).where(Shipment.order_id == order_id).with_for_update())
    if shipment is None:
        raise AppError(404, "shipment_not_found", f"Đơn {order_id} chưa có vận đơn")
    if body.status not in _ADVANCE.get(ShipmentStatus(shipment.status), set()):
        raise AppError(409, "invalid_transition", f"Không thể chuyển vận đơn từ {shipment.status} sang {body.status}")
    changed = shipment.status != body.status
    location = body.location or ("Kho TP.HCM" if shipment.status == ShipmentStatus.WAITING_PICKUP else
                                 "Địa chỉ người nhận" if body.status == "DELIVERED" else "Đang vận chuyển")
    description = body.description or {"IN_TRANSIT": "Đã lấy hàng, đang vận chuyển" if changed else
                                       f"Đang vận chuyển qua {location}",
                                       "DELIVERED": "Giao hàng thành công"}[body.status]
    shipment.status = body.status
    shipment.events.append(ShipmentEvent(status=body.status, location=location, description=description))
    if changed:
        outbox.add(db, "order", f"/internal/orders/{order_id}/shipping-status", {"status": body.status},
                   key=f"shipment-{order_id}-{body.status}")
    db.commit()
    outbox.flush()
    logger.info("shipment %s -> %s by staff %s", order_id, body.status, user.id)
    return shipment

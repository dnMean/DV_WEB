"""Service-to-service endpoints (see docs/USECASES.md section 4). All are idempotent."""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from opspilot_common.auth import require_internal
from opspilot_common.errors import AppError

from app.db import get_db
from app.models import Order, OrderStatus
from app.outbox import outbox, queue_restock
from app.schemas import OrderOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/orders", tags=["internal"], dependencies=[Depends(require_internal)])


class RefundAppliedIn(BaseModel):
    total_refunded: int = Field(..., ge=0, description="Tổng tiền đã hoàn của đơn (giá trị tuyệt đối)")
    full: bool = Field(..., description="Đã hoàn toàn bộ số tiền thanh toán")


class ShippingStatusIn(BaseModel):
    status: Literal["IN_TRANSIT", "DELIVERED"]


def _get(db: Session, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise AppError(404, "order_not_found", f"Không tìm thấy đơn hàng {order_id}")
    return order


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    return _get(db, order_id)


@router.post("/{order_id}/refund-applied", response_model=OrderOut, summary="Payment báo đã hoàn tiền")
def refund_applied(body: RefundAppliedIn, order_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    order = _get(db, order_id)
    before = order.status
    if body.full:
        if order.status == OrderStatus.PAID:  # refunded before shipping: goods never left the warehouse
            order.status = OrderStatus.REFUNDED.value
            queue_restock(db, order, "refund")
        elif order.status == OrderStatus.DELIVERED:
            order.status = OrderStatus.REFUNDED.value
        elif order.status != OrderStatus.REFUNDED:
            raise AppError(409, "invalid_transition", f"Không thể hoàn toàn bộ đơn ở trạng thái {order.status}")
    elif order.status not in (OrderStatus.DELIVERED, OrderStatus.REFUNDED):
        raise AppError(409, "invalid_transition", f"Không thể hoàn một phần đơn ở trạng thái {order.status}")
    order.refunded_amount = max(order.refunded_amount, body.total_refunded)
    db.commit()
    outbox.flush()
    logger.info("order %s refund applied: %s -> %s, refunded=%s", order_id, before, order.status, order.refunded_amount)
    return order


_SHIPPING_TRANSITIONS = {
    # shipment status -> {current order status: new order status}
    "IN_TRANSIT": {OrderStatus.PAID: OrderStatus.SHIPPING, OrderStatus.SHIPPING: OrderStatus.SHIPPING},
    "DELIVERED": {OrderStatus.PAID: OrderStatus.DELIVERED, OrderStatus.SHIPPING: OrderStatus.DELIVERED,
                  OrderStatus.DELIVERED: OrderStatus.DELIVERED},
}


@router.post("/{order_id}/shipping-status", response_model=OrderOut, summary="Shipping báo vận đơn đổi trạng thái")
def shipping_status(body: ShippingStatusIn, order_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    order = _get(db, order_id)
    new = _SHIPPING_TRANSITIONS[body.status].get(OrderStatus(order.status))
    if new is None:
        raise AppError(409, "invalid_transition", f"Đơn {order.status} không thể chuyển theo vận đơn {body.status}")
    if new != order.status:
        logger.info("order %s %s -> %s (shipment %s)", order_id, order.status, new, body.status)
        order.status = new.value
        db.commit()
    return order

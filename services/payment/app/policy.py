"""Refund rules (docs/USECASES.md section 2), evaluated against live Order and Shipping state."""
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from opspilot_common.auth import INTERNAL_SECRET_HEADER, CurrentUser, get_auth_settings
from opspilot_common.errors import AppError
from opspilot_common.logging import forward_headers

from app.config import get_settings
from app.models import Payment

logger = logging.getLogger(__name__)


@dataclass
class RefundCheck:
    payment: Payment
    order: dict[str, Any]
    before_shipping: bool  # PAID and still in the warehouse: refund = cancel the order
    full: bool

    @property
    def refundable(self) -> int:
        return self.payment.refundable_amount


class Dependencies:
    """Internal calls to Order and Shipping."""

    def __init__(self, http: httpx.Client):
        s = get_settings()
        self.http = http
        self.order_url = s.ORDER_URL.rstrip("/")
        self.shipping_url = s.SHIPPING_URL.rstrip("/")
        self.timeout = s.DEPENDENCY_TIMEOUT_SECONDS

    def _call(self, method: str, url: str, **kw) -> httpx.Response:
        headers = {INTERNAL_SECRET_HEADER: get_auth_settings().INTERNAL_SECRET, **forward_headers(), **kw.pop("headers", {})}
        try:
            return self.http.request(method, url, headers=headers, timeout=self.timeout, **kw)
        except httpx.HTTPError as exc:
            logger.error("%s %s failed: %s", method, url, exc)
            raise AppError(503, "dependency_unavailable", "Hệ thống đơn hàng/vận chuyển tạm thời không phản hồi")

    def order(self, order_id: int) -> dict[str, Any]:
        resp = self._call("GET", f"{self.order_url}/internal/orders/{order_id}")
        if resp.status_code == 404:
            raise AppError(404, "order_not_found", f"Không tìm thấy đơn hàng {order_id}")
        if not resp.is_success:
            raise AppError(503, "dependency_unavailable", "Không đọc được đơn hàng")
        return resp.json()

    def shipment(self, order_id: int) -> dict[str, Any] | None:
        resp = self._call("GET", f"{self.shipping_url}/internal/shipments/{order_id}")
        if resp.status_code == 404:
            return None
        if not resp.is_success:
            raise AppError(503, "dependency_unavailable", "Không đọc được vận đơn")
        return resp.json()

    def cancel_shipment(self, order_id: int, key: str) -> None:
        resp = self._call("POST", f"{self.shipping_url}/internal/shipments/{order_id}/cancel",
                          headers={"Idempotency-Key": key})
        if resp.status_code == 404 or resp.is_success:
            return
        if resp.status_code == 409:
            raise AppError(409, "order_in_transit",
                           "Hàng đã được giao cho đơn vị vận chuyển nên không thể hoàn tiền lúc này. "
                           "Khách vui lòng nhận hàng rồi yêu cầu hoàn/đổi trả.")
        raise AppError(503, "dependency_unavailable", "Không huỷ được vận đơn")


def evaluate(db: Session, deps: Dependencies, user: CurrentUser, order_id: int, amount: int | None,
             *, lock: bool = False) -> RefundCheck:
    order = deps.order(order_id)

    # ownership first, so a stranger learns nothing about the order's state
    if user.is_system:
        if user.on_behalf_of is None:
            raise AppError(400, "bad_request", "System token cần header X-On-Behalf-Of")
        if order["user_id"] != user.on_behalf_of:
            raise AppError(403, "forbidden", "Đơn hàng không thuộc về người yêu cầu hoàn tiền")
    elif not user.is_staff and order["user_id"] != user.id:
        raise AppError(403, "forbidden", "Bạn không có quyền yêu cầu hoàn tiền cho đơn hàng này")

    status = order["status"]
    stmt = select(Payment).where(Payment.order_id == order_id)
    payment = db.scalar(stmt.with_for_update() if lock else stmt)
    if status == "PENDING" or payment is None:
        raise AppError(409, "order_not_paid", f"Đơn {order_id} chưa thanh toán nên không có gì để hoàn")
    if status == "SHIPPING":
        raise AppError(409, "order_in_transit",
                       f"Đơn {order_id} đang được giao. Khách vui lòng nhận hàng rồi yêu cầu hoàn/đổi trả.")
    if status in ("CANCELLED", "REFUNDED") or payment.refundable_amount <= 0:
        raise AppError(409, "order_not_refundable", f"Đơn {order_id} đã được hoàn tiền hoặc đã huỷ")
    if amount is not None and amount > payment.refundable_amount:
        raise AppError(422, "amount_exceeds_refundable",
                       f"Số tiền hoàn {amount:,}đ vượt quá số còn có thể hoàn ({payment.refundable_amount:,}đ)",
                       extra={"refundable_amount": payment.refundable_amount})

    before_shipping = status == "PAID"
    if before_shipping:
        shipment = deps.shipment(order_id)
        if shipment is not None and shipment["status"] not in ("WAITING_PICKUP", "CANCELLED"):
            raise AppError(409, "order_in_transit",
                           f"Đơn {order_id} đã được giao cho đơn vị vận chuyển. Khách vui lòng nhận hàng rồi yêu cầu hoàn.")
        if amount is not None and amount != payment.refundable_amount:
            raise AppError(422, "full_refund_required",
                           f"Đơn {order_id} chưa giao: chỉ có thể hoàn toàn bộ {payment.refundable_amount:,}đ "
                           "(tương đương huỷ đơn)",
                           extra={"refundable_amount": payment.refundable_amount})
    return RefundCheck(payment, order, before_shipping,
                       full=amount is None or amount == payment.refundable_amount)

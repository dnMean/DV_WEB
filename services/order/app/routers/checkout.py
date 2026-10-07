"""Ordering by chat: quote -> place (customer types the quote code) -> pay (docs/USECASES.md section 3b)."""
import logging
import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from opspilot_common.auth import CurrentUser, require_roles
from opspilot_common.errors import AppError
from opspilot_common.tools import agent_tool

from app.config import get_settings
from app.db import get_db
from app.deps import Dependencies
from app.models import Order, OrderDelivery, OrderItem, OrderStatus, Quote, utcnow_naive
from app.outbox import outbox
from app.schemas import (
    DeliveryOut, OrderOut, PaidOut, PayIn, PlacedOut, PlaceIn, QuoteIn, QuoteLineOut, QuoteOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["checkout"])

_customer = require_roles("customer")
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L


def _deps(request: Request) -> Dependencies:
    return Dependencies(request.app.state.http)


def _new_code(db: Session) -> str:
    while True:
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if db.get(Quote, code) is None:
            return code


def _money(value: int) -> str:
    return f"{value:,}".replace(",", ".") + "đ"


def _quote_out(q: Quote) -> QuoteOut:
    minutes = max(0, int((q.expires_at - utcnow_naive()).total_seconds() // 60))
    return QuoteOut(
        quote_id=q.id, total=q.total, recipient_name=q.recipient_name, recipient_phone=q.recipient_phone,
        address=q.address, expires_in_minutes=minutes, order_id=q.order_id,
        items=[QuoteLineOut(**i, subtotal=i["qty"] * i["price"]) for i in q.items],
        next_step=(f"Chưa đặt hàng. Trình bày báo giá cho khách; để đặt, khách phải tự gõ 'xác nhận {q.id}' "
                   f"trong {minutes} phút."),
    )


@router.post(
    "/orders/quotes",
    response_model=QuoteOut,
    status_code=201,
    summary="Báo giá trước khi đặt hàng",
    description=(
        "Dùng khi khách muốn mua/đặt sản phẩm và đã nêu sản phẩm (product_id từ search_products), số lượng, "
        "tên người nhận, số điện thoại và địa chỉ giao hàng. Trả mã báo giá (quote_id), giá từng món, tổng tiền. "
        "CHƯA tạo đơn: trình bày báo giá và hướng dẫn khách gõ 'xác nhận <quote_id>' để đặt hàng."
    ),
    openapi_extra=agent_tool("quote_order", "low", ["customer"]),
)
def create_quote(
    body: QuoteIn,
    request: Request,
    user: CurrentUser = Depends(_customer),
    db: Session = Depends(get_db),
):
    wanted: dict[int, int] = {}
    for item in body.items:
        wanted[item.product_id] = wanted.get(item.product_id, 0) + item.qty
    catalog = _deps(request).catalog(list(wanted))
    missing = [pid for pid in wanted if pid not in catalog]
    if missing:
        raise AppError(404, "product_not_found", f"Không có sản phẩm {missing}. Hãy tìm lại bằng search_products.")
    short = [{"product_id": pid, "name": catalog[pid]["name"], "requested": qty, "available": catalog[pid]["stock"]}
             for pid, qty in wanted.items() if catalog[pid]["stock"] < qty]
    if short:
        names = ", ".join(f"{s['name']} (còn {s['available']})" for s in short)
        raise AppError(409, "out_of_stock", f"Không đủ hàng: {names}", extra={"items": short})

    items = [{"product_id": pid, "name": catalog[pid]["name"], "qty": qty, "price": catalog[pid]["price"]}
             for pid, qty in wanted.items()]
    quote = Quote(
        id=_new_code(db), user_id=user.id, items=items, total=sum(i["qty"] * i["price"] for i in items),
        recipient_name=body.recipient_name, recipient_phone=body.recipient_phone, address=body.address,
        expires_at=utcnow_naive() + timedelta(minutes=get_settings().QUOTE_TTL_MINUTES),
    )
    db.add(quote)
    db.commit()
    logger.info("quote %s for user %s: %s", quote.id, user.id, quote.total)
    return _quote_out(quote)


def _placed(db: Session, order: Order) -> PlacedOut:
    delivery = db.get(OrderDelivery, order.id)
    return PlacedOut(
        order=OrderOut.model_validate(order), delivery=DeliveryOut.model_validate(delivery),
        next_step=(f"Đơn {order.id} đang chờ thanh toán ({_money(order.total)}). Để thanh toán, khách tự gõ mã đơn "
                   f"và phương thức, vd 'thanh toán đơn {order.id} bằng thẻ' (thẻ, chuyển khoản, ví điện tử; "
                   "không hỗ trợ COD)."),
    )


@router.post(
    "/orders",
    response_model=PlacedOut,
    status_code=201,
    summary="Đặt hàng theo báo giá",
    description=(
        "Dùng khi khách xác nhận đặt hàng và tự gõ mã báo giá (quote_id) trong tin nhắn hiện tại. Tạo đơn chờ "
        "thanh toán và giữ hàng trong kho. Nếu khách chưa gõ mã báo giá thì không gọi, hãy nhắc khách gõ."
    ),
    openapi_extra=agent_tool("place_order", "medium", ["customer"], confirm_args=["quote_id"]),
)
def place_order(
    body: PlaceIn,
    request: Request,
    user: CurrentUser = Depends(_customer),
    db: Session = Depends(get_db),
):
    code = body.quote_id.upper()
    quote = db.scalar(select(Quote).where(Quote.id == code).with_for_update())
    if quote is None or quote.user_id != user.id:
        raise AppError(404, "quote_not_found", f"Không tìm thấy báo giá {code}")
    if quote.order_id is not None:  # idempotent: confirming twice places one order
        return _placed(db, db.get(Order, quote.order_id))
    if quote.expires_at < utcnow_naive():
        raise AppError(409, "quote_expired", f"Báo giá {code} đã hết hạn. Hãy tạo báo giá mới bằng quote_order.")

    order = Order(
        user_id=user.id, status=OrderStatus.PENDING.value, total=quote.total,
        items=[OrderItem(product_id=i["product_id"], name=i["name"], qty=i["qty"], price=i["price"])
               for i in quote.items],
    )
    db.add(order)
    db.flush()  # order id
    db.add(OrderDelivery(order_id=order.id, recipient_name=quote.recipient_name,
                         recipient_phone=quote.recipient_phone, address=quote.address))
    quote.order_id = order.id

    # a fresh key per attempt: a failed attempt releases exactly what it reserved
    stock = [{"product_id": i["product_id"], "qty": i["qty"]} for i in quote.items]
    key = f"quote-{code}-{uuid.uuid4().hex[:8]}"
    deps = _deps(request)
    try:
        deps.reserve(stock, key, f"order {order.id}")
    except AppError:
        db.rollback()
        raise
    try:
        db.commit()
    except Exception:
        db.rollback()
        deps.release(stock, f"{key}-release", f"order {order.id} not saved")
        raise
    logger.info("order %s placed from quote %s by user %s", order.id, code, user.id)
    return _placed(db, order)


@router.post(
    "/orders/{order_id}/pay",
    response_model=PaidOut,
    summary="Thanh toán đơn hàng (giả lập)",
    description=(
        "Dùng khi khách yêu cầu thanh toán một đơn cụ thể, tự gõ mã đơn và chọn phương thức. Gọi ngay, không tự "
        "đoán trạng thái đơn: hệ thống tự kiểm tra và trả lỗi nếu không thanh toán được. Sau khi thanh toán, đơn "
        "chuyển sang đã thanh toán và vận đơn được tạo."
    ),
    openapi_extra=agent_tool("pay_order", "medium", ["customer"], confirm_args=["order_id"]),
)
def pay_order(
    body: PayIn,
    request: Request,
    order_id: int = Path(..., ge=1, description="Mã đơn hàng cần thanh toán"),
    user: CurrentUser = Depends(_customer),
    db: Session = Depends(get_db),
):
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise AppError(404, "order_not_found", f"Không tìm thấy đơn hàng {order_id}")
    if order.user_id != user.id:
        raise AppError(403, "forbidden", "Bạn không có quyền truy cập đơn hàng này")
    if order.status != OrderStatus.PENDING:
        if order.status == OrderStatus.CANCELLED:
            raise AppError(409, "order_not_payable", f"Đơn {order_id} đã bị huỷ, không thể thanh toán.")
        raise AppError(409, "order_already_paid", f"Đơn {order_id} đã được thanh toán (trạng thái {order.status}).")

    delivery = db.get(OrderDelivery, order_id)
    if delivery is None:
        given = (body.recipient_name, body.recipient_phone, body.address)
        if not all(given):
            raise AppError(422, "delivery_info_required",
                           f"Đơn {order_id} chưa có thông tin giao hàng: cần tên người nhận, số điện thoại và địa chỉ.")
        delivery = OrderDelivery(order_id=order_id, recipient_name=given[0], recipient_phone=given[1],
                                 address=given[2])
        db.add(delivery)

    # money first (idempotent per order); the order only becomes PAID once Payment has recorded it
    payment = _deps(request).charge(order.id, order.user_id, order.total, body.method)
    order.status = OrderStatus.PAID.value
    outbox.add(db, "shipping", "/internal/shipments",
               {"order_id": order.id, "user_id": order.user_id, "recipient_name": delivery.recipient_name,
                "recipient_phone": delivery.recipient_phone, "address": delivery.address},
               key=f"order-{order.id}-shipment")
    db.commit()
    outbox.flush()
    logger.info("order %s paid by user %s via %s", order.id, user.id, body.method)
    return PaidOut(
        order=OrderOut.model_validate(order),
        payment={k: payment.get(k) for k in ("amount", "method", "status")},
        delivery=DeliveryOut.model_validate(delivery),
        next_step="Đã thanh toán; vận đơn được tạo và chờ kho lấy hàng. Khách tra cứu bằng get_shipment.",
    )

import logging

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opspilot_common.auth import CurrentUser, require_roles
from opspilot_common.errors import AppError
from opspilot_common.tools import agent_tool

from app.db import get_db
from app.models import Order, OrderStatus
from app.outbox import outbox, queue_restock
from app.schemas import OrderOut, OrderPage, OrderSummaryOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["orders"])

_customer_or_staff = require_roles("customer", "staff")


def _get_owned_order(db: Session, order_id: int, user: CurrentUser) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise AppError(404, "order_not_found", f"Không tìm thấy đơn hàng {order_id}")
    if not user.is_staff and order.user_id != user.id:
        raise AppError(403, "forbidden", "Bạn không có quyền truy cập đơn hàng này")
    return order


def _page(db: Session, filters: list, limit: int, offset: int) -> OrderPage:
    total = db.scalar(select(func.count()).select_from(Order).where(*filters))
    rows = db.scalars(select(Order).where(*filters).order_by(Order.id.desc()).limit(limit).offset(offset))
    orders = [OrderSummaryOut.of(o) for o in rows]
    return OrderPage(total=total, offset=offset, limit=limit, has_more=offset + len(orders) < total, orders=orders)


_PAGE_HINT = (
    "Trả {total: tổng số đơn khớp bộ lọc, has_more, orders: một trang đơn tóm tắt, mới nhất trước}. "
    "Khi được hỏi 'bao nhiêu đơn' thì trả lời theo total, không đếm số dòng trong trang. "
    "Dùng offset để xem trang tiếp; cần chi tiết/ghi chú thì dùng get_order."
)


@router.get(
    "/orders",
    response_model=OrderPage,
    summary="Liệt kê đơn hàng của tôi",
    description=(
        "Dùng khi user muốn xem hoặc đếm đơn hàng của mình, hoặc chưa nêu mã đơn cụ thể. "
        "Customer chỉ thấy đơn của chính mình; dùng status để lọc. " + _PAGE_HINT
    ),
    openapi_extra=agent_tool("list_my_orders", "low", ["customer"]),
)
def list_orders(
    status: OrderStatus | None = Query(None, description="Lọc theo trạng thái đơn"),
    user_id: int | None = Query(None, ge=1, description="Chỉ staff: lọc theo user_id của khách"),
    limit: int = Query(20, ge=1, le=50, description="Số đơn tối đa trả về trong một trang"),
    offset: int = Query(0, ge=0, description="Bỏ qua bao nhiêu đơn (phân trang)"),
    user: CurrentUser = Depends(_customer_or_staff),
    db: Session = Depends(get_db),
):
    filters = []
    if user.is_staff:
        if user_id is not None:
            filters.append(Order.user_id == user_id)
    else:
        if user_id is not None and user_id != user.id:
            raise AppError(403, "forbidden", "Bạn chỉ được xem đơn hàng của chính mình")
        filters.append(Order.user_id == user.id)
    if status is not None:
        filters.append(Order.status == status.value)
    return _page(db, filters, limit, offset)


@router.get(
    "/orders/search",
    response_model=OrderPage,
    summary="Tìm đơn hàng (staff)",
    description=(
        "Chỉ dành cho staff. Tìm trong toàn bộ đơn hàng, lọc theo khách (user_id), mã đơn (order_id), trạng thái "
        "(PENDING chờ thanh toán, PAID đã thanh toán chưa giao, SHIPPING đang giao, DELIVERED đã giao, CANCELLED đã huỷ, "
        "REFUNDED đã hoàn toàn bộ) hoặc refunded=true để lấy các đơn đã có hoàn tiền (kể cả hoàn một phần). "
        + _PAGE_HINT
    ),
    openapi_extra=agent_tool("search_orders", "low", ["staff"]),
)
def search_orders(
    user_id: int | None = Query(None, ge=1, description="Lọc theo user_id của khách"),
    order_id: int | None = Query(None, ge=1, description="Lọc theo mã đơn"),
    status: OrderStatus | None = Query(None, description="Lọc theo trạng thái đơn"),
    refunded: bool | None = Query(None, description="true: chỉ đơn đã có hoàn tiền; false: chỉ đơn chưa hoàn"),
    limit: int = Query(20, ge=1, le=200, description="Số đơn tối đa trong một trang"),
    offset: int = Query(0, ge=0, description="Bỏ qua bao nhiêu đơn (phân trang)"),
    _: CurrentUser = Depends(require_roles("staff")),
    db: Session = Depends(get_db),
):
    filters = []
    if user_id is not None:
        filters.append(Order.user_id == user_id)
    if order_id is not None:
        filters.append(Order.id == order_id)
    if status is not None:
        filters.append(Order.status == status.value)
    if refunded is not None:
        filters.append(Order.refunded_amount > 0 if refunded else Order.refunded_amount == 0)
    return _page(db, filters, limit, offset)


@router.get(
    "/orders/{order_id}",
    response_model=OrderOut,
    summary="Lấy thông tin một đơn hàng",
    description=(
        "Dùng khi user hỏi trạng thái, sản phẩm, tổng tiền của một đơn cụ thể. "
        "Cần mã đơn (order_id). Customer chỉ xem được đơn của mình."
    ),
    openapi_extra=agent_tool("get_order", "low", ["customer", "staff"]),
)
def get_order(
    order_id: int = Path(..., ge=1, description="Mã đơn hàng, ví dụ 1002"),
    user: CurrentUser = Depends(_customer_or_staff),
    db: Session = Depends(get_db),
):
    return _get_owned_order(db, order_id, user)


@router.post(
    "/orders/{order_id}/cancel",
    response_model=OrderOut,
    summary="Huỷ đơn hàng chưa thanh toán",
    description=(
        "Dùng khi user yêu cầu rõ ràng huỷ một đơn cụ thể: gọi ngay, không tự đoán trạng thái đơn. Hệ thống tự "
        "kiểm tra điều kiện (chỉ đơn chưa thanh toán mới huỷ được) và trả lỗi kèm gợi ý nếu không huỷ được "
        "(vd đơn đã thanh toán thì khách cần yêu cầu hoàn toàn bộ tiền)."
    ),
    openapi_extra=agent_tool("cancel_order", "medium", ["customer", "staff"]),
)
def cancel_order(
    order_id: int = Path(..., ge=1, description="Mã đơn hàng cần huỷ"),
    user: CurrentUser = Depends(_customer_or_staff),
    db: Session = Depends(get_db),
):
    order = _get_owned_order(db, order_id, user)
    if order.status == OrderStatus.CANCELLED:
        return order  # idempotent: cancelling twice is not an error
    if order.status == OrderStatus.PAID:
        raise AppError(
            409, "order_already_paid",
            f"Đơn {order_id} đã thanh toán nên không thể huỷ trực tiếp. "
            "Hãy tạo yêu cầu hoàn tiền bằng refund_payment (cần nhân viên duyệt).",
            extra={"suggested_tool": "refund_payment"},
        )
    if order.status != OrderStatus.PENDING:
        raise AppError(
            409, "order_not_cancellable",
            f"Đơn {order_id} đang ở trạng thái {order.status}, không thể huỷ.",
        )
    order.status = OrderStatus.CANCELLED.value
    queue_restock(db, order, "cancel")
    db.commit()
    outbox.flush()
    logger.info("order %s cancelled by user %s", order_id, user.id)
    return order

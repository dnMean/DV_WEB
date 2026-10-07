from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import OrderStatus


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    name: str
    qty: int
    price: int


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    status: OrderStatus
    total: int
    refunded_amount: int
    items: list[OrderItemOut]
    note: str | None
    created_at: datetime


class OrderSummaryOut(BaseModel):
    """Compact row for list endpoints (keeps tool results small); use get_order for details and note."""

    id: int
    user_id: int
    status: OrderStatus
    total: int
    refunded_amount: int
    items: str
    created_at: datetime

    @classmethod
    def of(cls, o) -> "OrderSummaryOut":
        return cls(id=o.id, user_id=o.user_id, status=o.status, total=o.total, refunded_amount=o.refunded_amount,
                   items=", ".join(f"{i.name} x{i.qty}" for i in o.items), created_at=o.created_at)


class OrderPage(BaseModel):
    total: int
    offset: int
    limit: int
    has_more: bool
    orders: list[OrderSummaryOut]


# --- ordering by chat (docs/USECASES.md section 3b) ------------------------------------------

_PHONE = r"^(\+84|0)\d{9}$"


class QuoteItemIn(BaseModel):
    product_id: int = Field(..., ge=1, description="Mã sản phẩm (lấy từ search_products)")
    qty: int = Field(1, ge=1, le=10, description="Số lượng")


class QuoteIn(BaseModel):
    items: list[QuoteItemIn] = Field(..., min_length=1, max_length=10, description="Sản phẩm khách muốn mua")
    recipient_name: str = Field(..., min_length=1, max_length=100, description="Tên người nhận do khách cung cấp")
    recipient_phone: str = Field(..., pattern=_PHONE, description="Số điện thoại người nhận do khách cung cấp")
    address: str = Field(..., min_length=10, max_length=300, description="Địa chỉ giao hàng đầy đủ do khách cung cấp")


class QuoteLineOut(BaseModel):
    product_id: int
    name: str
    qty: int
    price: int
    subtotal: int


class QuoteOut(BaseModel):
    quote_id: str = Field(description="Mã báo giá; khách phải tự gõ mã này để xác nhận đặt hàng")
    items: list[QuoteLineOut]
    total: int
    recipient_name: str
    recipient_phone: str
    address: str
    expires_in_minutes: int
    order_id: int | None = Field(None, description="Đơn đã đặt từ báo giá này (nếu có)")
    next_step: str


class PlaceIn(BaseModel):
    quote_id: str = Field(..., pattern=r"^[A-Za-z0-9]{6}$", description="Mã báo giá khách đã gõ để xác nhận")


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipient_name: str
    recipient_phone: str
    address: str


class PlacedOut(BaseModel):
    order: OrderOut
    delivery: DeliveryOut
    next_step: str


class PayIn(BaseModel):
    # prepaid only: COD collects money on delivery, so the order could not be PAID now
    method: Literal["CARD", "BANK_TRANSFER", "E_WALLET"] = Field(
        ..., description="Phương thức khách chọn: CARD (thẻ), BANK_TRANSFER (chuyển khoản), E_WALLET (ví điện tử). "
                         "Không hỗ trợ COD (trả khi nhận hàng)")
    recipient_name: str | None = Field(None, min_length=1, max_length=100,
                                       description="Chỉ khi đơn chưa có thông tin giao hàng: tên người nhận")
    recipient_phone: str | None = Field(None, pattern=_PHONE,
                                        description="Chỉ khi đơn chưa có thông tin giao hàng: số điện thoại")
    address: str | None = Field(None, min_length=10, max_length=300,
                                description="Chỉ khi đơn chưa có thông tin giao hàng: địa chỉ")


class PaidOut(BaseModel):
    order: OrderOut
    payment: dict
    delivery: DeliveryOut
    next_step: str

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ShipmentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    location: str
    description: str
    occurred_at: datetime


class ShipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: int
    user_id: int
    status: str
    carrier: str
    tracking_code: str
    recipient_name: str
    recipient_phone: str
    address: str
    updated_at: datetime
    events: list[ShipmentEventOut]


class AddressUpdateIn(BaseModel):
    address: str = Field(..., min_length=5, max_length=300, description="Địa chỉ giao hàng mới, đầy đủ")
    recipient_name: str | None = Field(None, min_length=1, max_length=100, description="Tên người nhận mới (tuỳ chọn)")
    recipient_phone: str | None = Field(
        None, pattern=r"^(\+84|0)\d{9}$", description="Số điện thoại người nhận mới (tuỳ chọn)"
    )


class AdvanceIn(BaseModel):
    status: Literal["IN_TRANSIT", "DELIVERED"] = Field(
        ..., description="IN_TRANSIT: đã lấy hàng / đang giao / cập nhật vị trí; DELIVERED: đã giao thành công")
    location: str = Field("", max_length=100, description="Vị trí hiện tại (tuỳ chọn), vd Kho Hà Nội")
    description: str = Field("", max_length=300, description="Ghi chú (tuỳ chọn)")


class ShipmentCreateIn(BaseModel):
    order_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)
    recipient_name: str = Field(..., min_length=1, max_length=100)
    recipient_phone: str = Field(..., max_length=20)
    address: str = Field(..., min_length=1, max_length=300)

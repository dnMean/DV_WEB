from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RefundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    amount: int
    reason: str
    status: str
    created_at: datetime


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    user_id: int
    amount: int
    method: str
    status: str
    refunded_amount: int
    refundable_amount: int
    refunds: list[RefundOut]
    created_at: datetime


class RefundIn(BaseModel):
    order_id: int = Field(..., ge=1, description="Mã đơn hàng cần hoàn tiền")
    amount: int = Field(..., gt=0, description="Số tiền hoàn (VND), không vượt quá số tiền còn có thể hoàn")
    reason: str = Field(..., min_length=1, max_length=500, description="Lý do hoàn tiền do khách nêu")


class RefundResultOut(BaseModel):
    refund: RefundOut
    replayed: bool = Field(description="true nếu Idempotency-Key đã được dùng và đây là kết quả cũ")
    refundable_amount: int


class RefundCheckOut(BaseModel):
    eligible: bool
    order_status: str
    refundable_amount: int
    full_refund_required: bool


class EligibilityOut(BaseModel):
    order_id: int
    eligible: bool
    reason: str = Field(description="ok | order_not_paid | order_in_transit | order_not_refundable")
    message: str
    max_refundable: int
    full_refund_required: bool


class ChargeIn(BaseModel):
    order_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)
    amount: int = Field(..., gt=0)
    method: str = Field(..., min_length=1, max_length=30)

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opspilot_common.outbox import make_outbox_model

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PaymentStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)  # denormalized for ownership checks
    amount: Mapped[int] = mapped_column(BigInteger)  # VND
    method: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default=PaymentStatus.SUCCESS.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    refunds: Mapped[list["Refund"]] = relationship(
        back_populates="payment", lazy="selectin", order_by="Refund.id"
    )

    @property
    def refunded_amount(self) -> int:
        return sum(r.amount for r in self.refunds)

    @property
    def refundable_amount(self) -> int:
        return self.amount - self.refunded_amount


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), index=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="SUCCESS")
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    requested_by: Mapped[int] = mapped_column(Integer)  # end user (system: X-On-Behalf-Of) or staff id
    requested_role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    payment: Mapped[Payment] = relationship(back_populates="refunds")


OutboxMessage = make_outbox_model(Base)

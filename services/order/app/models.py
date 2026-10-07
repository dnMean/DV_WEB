from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opspilot_common.outbox import make_outbox_model

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_naive() -> datetime:
    """Naive UTC: compares the same on SQLite and Postgres (used for quote expiry)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    SHIPPING = "SHIPPING"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(20))
    total: Mapped[int] = mapped_column(BigInteger)  # VND
    refunded_amount: Mapped[int] = mapped_column(BigInteger, default=0)  # mirrored from Payment
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin", order_by="OrderItem.id"
    )


class OrderItem(Base):
    """Product name/price are copied at order time (no cross-DB join with product_db)."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[int] = mapped_column(BigInteger)

    order: Mapped[Order] = relationship(back_populates="items")


class Quote(Base):
    """Price quote shown to the customer before an order is placed (docs/USECASES.md section 3b).

    `id` is the short code the customer types to confirm; the Gateway checks it is in their own message.
    """

    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    items: Mapped[list] = mapped_column(JSON)  # [{product_id, name, qty, price}]
    total: Mapped[int] = mapped_column(BigInteger)
    recipient_name: Mapped[str] = mapped_column(String(100))
    recipient_phone: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime)  # naive UTC
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # set once the order is placed


class OrderDelivery(Base):
    """Where to ship an order; sent to Shipping when the order is paid. Seed orders have none."""

    __tablename__ = "order_delivery"

    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True)
    recipient_name: Mapped[str] = mapped_column(String(100))
    recipient_phone: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(Text)


OutboxMessage = make_outbox_model(Base)

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opspilot_common.outbox import make_outbox_model

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ShipmentStatus(StrEnum):
    WAITING_PICKUP = "WAITING_PICKUP"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)  # denormalized for ownership checks
    status: Mapped[str] = mapped_column(String(20))
    carrier: Mapped[str] = mapped_column(String(50))
    tracking_code: Mapped[str] = mapped_column(String(50))
    recipient_name: Mapped[str] = mapped_column(String(100))
    recipient_phone: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    events: Mapped[list["ShipmentEvent"]] = relationship(
        back_populates="shipment", lazy="selectin", order_by="ShipmentEvent.occurred_at",
        cascade="all, delete-orphan",
    )


class ShipmentEvent(Base):
    __tablename__ = "shipment_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    location: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    shipment: Mapped[Shipment] = relationship(back_populates="events")


OutboxMessage = make_outbox_model(Base)

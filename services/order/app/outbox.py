from opspilot_common.auth import get_auth_settings
from opspilot_common.outbox import Outbox

from app.config import get_settings
from app.db import SessionLocal
from app.models import Order, OutboxMessage

outbox = Outbox(OutboxMessage, SessionLocal,
                {"product": get_settings().PRODUCT_URL, "shipping": get_settings().SHIPPING_URL},
                get_auth_settings().INTERNAL_SECRET)


def queue_restock(db, order: Order, reason: str) -> None:
    """Put the order's items back in stock (once per order, whatever the retries)."""
    outbox.add(db, "product", "/internal/inventory/restock",
               {"items": [{"product_id": i.product_id, "qty": i.qty} for i in order.items],
                "reason": f"{reason} order {order.id}"},
               key=f"order-{order.id}-restock")

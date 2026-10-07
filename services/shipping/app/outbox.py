from opspilot_common.auth import get_auth_settings
from opspilot_common.outbox import Outbox

from app.config import get_settings
from app.db import SessionLocal
from app.models import OutboxMessage

outbox = Outbox(OutboxMessage, SessionLocal, {"order": get_settings().ORDER_URL},
                get_auth_settings().INTERNAL_SECRET)

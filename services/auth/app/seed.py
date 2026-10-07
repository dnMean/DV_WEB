import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import sync_sequence
from app.models import User
from app.security import hash_password

logger = logging.getLogger(__name__)

DEFAULT_PASSWORD = "password123"

# (id, username, role, email, phone)
USERS = [
    (1, "alice", "customer", "alice@example.com", "0901234567"),
    (2, "bob", "customer", "bob@example.com", "0912345678"),
    (3, "staff1", "staff", "staff1@opspilot.local", "0987654321"),
]


def seed(db: Session) -> None:
    if db.scalar(select(User.id).limit(1)) is not None:
        return
    for user_id, username, role, email, phone in USERS:
        db.add(User(
            id=user_id, username=username, role=role, email=email, phone=phone,
            password_hash=hash_password(DEFAULT_PASSWORD),
        ))
    db.flush()
    sync_sequence(db, "users")
    db.commit()
    logger.info("seeded %s users", len(USERS))

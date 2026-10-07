import logging
import time
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings

logger = logging.getLogger(__name__)

_url = get_settings().database_url
if _url.startswith("sqlite"):
    engine = create_engine(_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
else:
    engine = create_engine(_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


def init_db(retries: int = 10, delay: float = 2.0) -> None:
    from app import models  # noqa: F401  (register tables)

    for attempt in range(1, retries + 1):
        try:
            Base.metadata.create_all(engine)
            return
        except Exception as exc:  # DB may still be starting
            if attempt == retries:
                raise
            logger.warning("create_all failed (attempt %s/%s): %s", attempt, retries, exc)
            time.sleep(delay)


def sync_sequence(db: Session, table: str) -> None:
    """After inserting explicit ids on Postgres, move the serial sequence past max(id)."""
    if db.bind.dialect.name != "postgresql":
        return
    db.execute(text(
        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT COALESCE(MAX(id), 1) FROM {table}))"
    ))

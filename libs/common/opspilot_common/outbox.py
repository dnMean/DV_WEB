"""Transactional outbox for service-to-service updates (docs/USECASES.md section 4).

A service writes an outbox row in the same DB transaction as its own change, then delivers it:
right away after commit (`flush()`), and again from a background thread while the target is down.
Targets must be idempotent (every row carries a stable Idempotency-Key).

Requires SQLAlchemy (only services with a database import this module).
"""
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import JSON, DateTime, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from .auth import INTERNAL_SECRET_HEADER
from .logging import forward_headers

logger = logging.getLogger("opspilot.outbox")

PENDING, DONE, FAILED = "PENDING", "DONE", "FAILED"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC: compares the same on SQLite and Postgres


def make_outbox_model(base: type) -> type:
    class OutboxMessage(base):
        __tablename__ = "outbox"

        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        target: Mapped[str] = mapped_column(String(30))
        method: Mapped[str] = mapped_column(String(10), default="POST")
        path: Mapped[str] = mapped_column(String(200))
        payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
        idempotency_key: Mapped[str] = mapped_column(String(128))
        status: Mapped[str] = mapped_column(String(10), default=PENDING, index=True)
        attempts: Mapped[int] = mapped_column(Integer, default=0)
        last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
        created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
        next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    return OutboxMessage


class Outbox:
    def __init__(self, model: type, session_factory: sessionmaker, targets: dict[str, str], internal_secret: str,
                 *, max_attempts: int = 8, timeout: float = 5.0):
        self.model = model
        self.session_factory = session_factory
        self.targets = {k: v.rstrip("/") for k, v in targets.items()}
        self.secret = internal_secret
        self.max_attempts = max_attempts
        self.timeout = timeout
        self.http: httpx.Client | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def add(self, db: Session, target: str, path: str, payload: dict[str, Any] | None, key: str,
            method: str = "POST") -> None:
        """Queue a call; it is committed together with the caller's transaction."""
        if target not in self.targets:
            raise ValueError(f"unknown outbox target {target}")
        db.add(self.model(target=target, method=method, path=path, payload=payload, idempotency_key=key))

    def flush(self) -> int:
        """Deliver every due message. Safe to call from request handlers and the background thread."""
        if self.http is None:
            return 0
        with self._lock, self.session_factory() as db:
            rows = db.scalars(
                select(self.model)
                .where(self.model.status == PENDING, self.model.next_attempt_at <= _utcnow())
                .order_by(self.model.id)
                .limit(50)
            ).all()
            for row in rows:
                self._deliver(row)
                db.commit()
            return len(rows)

    def _deliver(self, row) -> None:
        row.attempts += 1
        headers = {INTERNAL_SECRET_HEADER: self.secret, "Idempotency-Key": row.idempotency_key, **forward_headers()}
        try:
            resp = self.http.request(row.method, self.targets[row.target] + row.path, json=row.payload,
                                     headers=headers, timeout=self.timeout)
        except httpx.HTTPError as exc:
            self._retry(row, f"{type(exc).__name__}: {exc}")
            return
        if resp.is_success:
            row.status, row.last_error = DONE, None
        elif resp.status_code in (408, 429) or resp.status_code >= 500:
            self._retry(row, f"HTTP {resp.status_code}")
        else:  # 4xx: the target rejected it; retrying will not help
            row.status, row.last_error = FAILED, f"HTTP {resp.status_code}: {resp.text[:300]}"
            logger.error("outbox #%s %s %s rejected: %s", row.id, row.target, row.path, row.last_error)

    def _retry(self, row, error: str) -> None:
        row.last_error = error
        if row.attempts >= self.max_attempts:
            row.status = FAILED
            logger.error("outbox #%s %s %s gave up: %s", row.id, row.target, row.path, error)
            return
        row.next_attempt_at = _utcnow() + timedelta(seconds=min(2 ** row.attempts, 60))
        logger.warning("outbox #%s %s %s failed (%s), retry #%s", row.id, row.target, row.path, error, row.attempts)

    def stats(self, db: Session) -> dict[str, int]:
        rows = db.execute(select(self.model.status, func.count()).group_by(self.model.status)).all()
        return {status: count for status, count in rows}

    def start(self, http: httpx.Client, interval: float) -> None:
        self.http = http
        if interval <= 0:
            return
        self._stop.clear()

        def loop() -> None:
            while not self._stop.wait(interval):
                try:
                    self.flush()
                except Exception:
                    logger.exception("outbox flush failed")

        self._thread = threading.Thread(target=loop, name="outbox", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

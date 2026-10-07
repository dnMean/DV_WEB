from sqlalchemy import BigInteger, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[int] = mapped_column(BigInteger)  # VND
    stock: Mapped[int] = mapped_column(Integer, default=0)
    # Lowercased, accent-stripped name + category + description, for accent-insensitive search.
    search_text: Mapped[str] = mapped_column(Text, default="")


class RestockLog(Base):
    """Processed restock/reserve requests, so a retried call never changes stock twice."""

    __tablename__ = "restock_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    reason: Mapped[str] = mapped_column(String(200), default="")

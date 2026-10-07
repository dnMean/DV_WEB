import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import sync_sequence
from app.models import Product
from app.text import normalize

logger = logging.getLogger(__name__)

# (id, sku, name, category, description, price, stock) — ids/prices referenced by order seed.
PRODUCTS = [
    (1, "PHN-SS-A15", "Điện thoại Samsung Galaxy A15", "Điện thoại",
     "Màn hình 6.5 inch, RAM 8GB, bộ nhớ 128GB, pin 5000mAh.", 2_500_000, 12),
    (2, "HP-SONY-CH520", "Tai nghe Bluetooth Sony WH-CH520", "Tai nghe",
     "Tai nghe chụp tai không dây, pin 50 giờ, sạc nhanh.", 1_200_000, 20),
    (3, "CHG-ANKER-20W", "Sạc nhanh Anker 20W USB-C", "Sạc",
     "Củ sạc nhanh PD 20W cho iPhone và Android.", 350_000, 45),
    (4, "CBL-BASEUS-C1M", "Cáp sạc USB-C Baseus 1m", "Phụ kiện",
     "Cáp USB-C sang USB-C, hỗ trợ sạc nhanh 60W.", 150_000, 80),
    (5, "CASE-IP15-SIL", "Ốp lưng silicon iPhone 15", "Phụ kiện",
     "Ốp lưng silicon mềm, chống sốc, nhiều màu.", 200_000, 35),
    (6, "GLS-IP15", "Kính cường lực iPhone 15", "Phụ kiện",
     "Kính cường lực 9H, chống vân tay.", 100_000, 60),
    (7, "WR-XM-BAND8", "Vòng đeo tay Xiaomi Smart Band 8", "Đồng hồ thông minh",
     "Theo dõi sức khoẻ, đo nhịp tim, pin 16 ngày.", 800_000, 18),
    (8, "PB-XM-10K", "Sạc dự phòng Xiaomi 10000mAh", "Sạc",
     "Pin sạc dự phòng 10000mAh, sạc nhanh 22.5W.", 400_000, 0),
]


def seed(db: Session) -> None:
    if db.scalar(select(Product.id).limit(1)) is not None:
        return
    for pid, sku, name, category, description, price, stock in PRODUCTS:
        db.add(Product(
            id=pid, sku=sku, name=name, category=category, description=description,
            price=price, stock=stock, search_text=normalize(f"{name} {category} {description}"),
        ))
    db.flush()
    sync_sequence(db, "products")
    db.commit()
    logger.info("seeded %s products", len(PRODUCTS))

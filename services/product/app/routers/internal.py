import logging

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from opspilot_common.auth import require_internal
from opspilot_common.errors import AppError

from app.db import get_db
from app.models import Product, RestockLog
from app.schemas import CatalogItemOut, ReserveOut, RestockIn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal)])


def _catalog(p: Product) -> CatalogItemOut:
    return CatalogItemOut(id=p.id, name=p.name, price=p.price, stock=p.stock)


def _locked_products(db: Session, body: RestockIn) -> dict[int, Product]:
    products = {p.id: p for p in db.scalars(select(Product).where(
        Product.id.in_([i.product_id for i in body.items])).with_for_update())}
    missing = [i.product_id for i in body.items if i.product_id not in products]
    if missing:
        raise AppError(422, "product_not_found", f"Không có sản phẩm {missing}")
    return products


@router.get("/products", response_model=list[CatalogItemOut], summary="(nội bộ) Giá và tồn kho của nhiều sản phẩm")
def catalog(ids: str = Query(..., max_length=200, description="Danh sách product_id, cách nhau bởi dấu phẩy"),
            db: Session = Depends(get_db)):
    try:
        wanted = {int(x) for x in ids.split(",") if x.strip()}
    except ValueError:
        raise AppError(422, "validation_error", "ids phải là các số nguyên cách nhau bởi dấu phẩy")
    return [_catalog(p) for p in db.scalars(select(Product).where(Product.id.in_(wanted)).order_by(Product.id))]


@router.post("/inventory/restock", summary="(nội bộ) Cộng lại tồn kho khi đơn bị huỷ/hoàn trước khi giao")
def restock(
    body: RestockIn,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=128),
    db: Session = Depends(get_db),
):
    if not idempotency_key:
        raise AppError(400, "idempotency_key_required", "Thiếu header Idempotency-Key")
    if db.scalar(select(RestockLog).where(RestockLog.idempotency_key == idempotency_key)):
        return {"replayed": True}
    products = _locked_products(db, body)
    for item in body.items:
        products[item.product_id].stock += item.qty
    db.add(RestockLog(idempotency_key=idempotency_key, reason=body.reason))
    try:
        db.commit()
    except IntegrityError:  # same key processed concurrently
        db.rollback()
        return {"replayed": True}
    logger.info("restocked %s (%s)", [(i.product_id, i.qty) for i in body.items], body.reason)
    return {"replayed": False}


@router.post("/inventory/reserve", response_model=ReserveOut,
             summary="(nội bộ) Trừ tồn kho khi đặt hàng: đủ hàng cho mọi sản phẩm hoặc không trừ gì")
def reserve(
    body: RestockIn,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=128),
    db: Session = Depends(get_db),
):
    if not idempotency_key:
        raise AppError(400, "idempotency_key_required", "Thiếu header Idempotency-Key")
    if db.scalar(select(RestockLog).where(RestockLog.idempotency_key == idempotency_key)):
        products = db.scalars(select(Product).where(Product.id.in_([i.product_id for i in body.items])))
        return ReserveOut(replayed=True, items=[_catalog(p) for p in products])
    products = _locked_products(db, body)
    wanted: dict[int, int] = {}
    for item in body.items:
        wanted[item.product_id] = wanted.get(item.product_id, 0) + item.qty
    short = [
        {"product_id": pid, "name": products[pid].name, "requested": qty, "available": products[pid].stock}
        for pid, qty in wanted.items() if products[pid].stock < qty
    ]
    if short:
        names = ", ".join(f"{s['name']} (còn {s['available']})" for s in short)
        raise AppError(409, "out_of_stock", f"Không đủ hàng: {names}", extra={"items": short})
    for pid, qty in wanted.items():
        products[pid].stock -= qty
    db.add(RestockLog(idempotency_key=idempotency_key, reason=body.reason))
    try:
        db.commit()
    except IntegrityError:  # same key processed concurrently
        db.rollback()
        return ReserveOut(replayed=True, items=[_catalog(products[pid]) for pid in wanted])
    logger.info("reserved %s (%s)", list(wanted.items()), body.reason)
    return ReserveOut(replayed=False, items=[_catalog(products[pid]) for pid in wanted])

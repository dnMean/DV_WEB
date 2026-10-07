from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from opspilot_common.auth import CurrentUser, get_optional_user
from opspilot_common.errors import AppError
from opspilot_common.tools import agent_tool

from app.db import get_db
from app.models import Product
from app.schemas import ProductOut, StockOut
from app.text import normalize

router = APIRouter(tags=["products"])

_ROLES = ["customer", "staff"]


def _to_out(p: Product) -> ProductOut:
    return ProductOut(
        id=p.id, sku=p.sku, name=p.name, category=p.category,
        description=p.description, price=p.price, in_stock=p.stock > 0,
    )


def _get_product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise AppError(404, "product_not_found", f"Không tìm thấy sản phẩm {product_id}")
    return product


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get(
    "/products/search",
    response_model=list[ProductOut],
    summary="Tìm kiếm sản phẩm",
    description=(
        "Dùng khi user hỏi về sản phẩm theo tên hoặc loại (ví dụ 'tai nghe', 'sạc'). "
        "Tìm không phân biệt hoa thường và dấu. Trả tối đa `limit` kết quả."
    ),
    openapi_extra=agent_tool("search_products", "low", _ROLES),
)
def search_products(
    q: str = Query(..., min_length=1, max_length=100, description="Từ khoá tìm kiếm"),
    limit: int = Query(5, ge=1, le=20, description="Số kết quả tối đa"),
    _user: CurrentUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    stmt = select(Product).order_by(Product.id).limit(limit)
    for word in normalize(q).split():
        stmt = stmt.where(Product.search_text.like(f"%{_escape_like(word)}%", escape="\\"))
    return [_to_out(p) for p in db.scalars(stmt)]


@router.get(
    "/products/{product_id}",
    response_model=ProductOut,
    summary="Lấy chi tiết sản phẩm",
    description="Dùng khi đã biết mã sản phẩm (product_id) và cần giá, mô tả, danh mục.",
    openapi_extra=agent_tool("get_product", "low", _ROLES),
)
def get_product(
    product_id: int = Path(..., ge=1, description="Mã sản phẩm"),
    _user: CurrentUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    return _to_out(_get_product(db, product_id))


@router.get(
    "/inventory/{product_id}",
    response_model=StockOut,
    summary="Kiểm tra tồn kho sản phẩm",
    description="Dùng khi user hỏi sản phẩm còn hàng không hoặc còn bao nhiêu. Cần product_id.",
    openapi_extra=agent_tool("check_stock", "low", _ROLES),
)
def check_stock(
    product_id: int = Path(..., ge=1, description="Mã sản phẩm"),
    _user: CurrentUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    p = _get_product(db, product_id)
    return StockOut(product_id=p.id, name=p.name, stock=p.stock, in_stock=p.stock > 0)

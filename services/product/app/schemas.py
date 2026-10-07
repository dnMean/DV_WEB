from pydantic import BaseModel, ConfigDict, Field


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    category: str
    description: str
    price: int
    in_stock: bool


class StockOut(BaseModel):
    product_id: int
    name: str
    stock: int
    in_stock: bool


class RestockItem(BaseModel):
    product_id: int
    qty: int = Field(..., gt=0)


class RestockIn(BaseModel):
    items: list[RestockItem] = Field(..., min_length=1)
    reason: str = Field("", max_length=200)


class CatalogItemOut(BaseModel):
    """Internal view for Order: current name, price and stock."""

    id: int
    name: str
    price: int
    stock: int


class ReserveOut(BaseModel):
    replayed: bool
    items: list[CatalogItemOut]

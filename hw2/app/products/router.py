from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.orm import ProductStatus, UserRole, User
from app.products import service
# Импортируем сгенерированные модели — DTO формируются кодогенерацией из OpenAPI
from generated.models import (
    ProductCreate, ProductUpdate, ProductResponse, ProductListResponse,
)

router = APIRouter(prefix="/products", tags=["products"])


def _to_response(p) -> ProductResponse:
    return ProductResponse(
        id=p.id,
        name=p.name,
        description=p.description,
        price=float(p.price),
        stock=p.stock,
        category=p.category,
        status=p.status.value,   # ORM-enum → строка для Pydantic
        seller_id=p.seller_id,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.get("", response_model=ProductListResponse)
async def list_products(
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1, le=100),
    status: Optional[ProductStatus] = Query(None),
    category: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    products, total = await service.list_products(db, page, size, status, category)
    return ProductListResponse(
        items=[_to_response(p) for p in products],
        totalElements=total,
        page=page,
        size=size,
    )


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    body: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = await service.create_product(db, body.model_dump(), current_user)
    return _to_response(product)


@router.get("/{id}", response_model=ProductResponse)
async def get_product(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = await service.get_product(db, id)
    return _to_response(product)


@router.put("/{id}", response_model=ProductResponse)
async def update_product(
    id: int,
    body: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = await service.update_product(db, id, body.model_dump(exclude_none=True), current_user)
    return _to_response(product)


@router.delete("/{id}", response_model=ProductResponse)
async def delete_product(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = await service.archive_product(db, id, current_user)
    return _to_response(product)

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ProductNotFoundError, AccessDeniedError
from app.models.orm import Product, ProductStatus, UserRole, User
from app.products import repository


def _check_product_ownership(product: Product, user: User) -> None:
    """SELLER может управлять только своими товарами."""
    if user.role == UserRole.SELLER and product.seller_id != user.id:
        raise AccessDeniedError("Вы можете управлять только своими товарами")


async def get_product(db: AsyncSession, product_id: int) -> Product:
    product = await repository.get_by_id(db, product_id)
    if product is None:
        raise ProductNotFoundError(product_id)
    return product


async def list_products(
    db: AsyncSession,
    page: int,
    size: int,
    status: Optional[ProductStatus] = None,
    category: Optional[str] = None,
):
    return await repository.list_products(db, page, size, status, category)


async def create_product(db: AsyncSession, data: dict, user: User) -> Product:
    if user.role == UserRole.USER:
        raise AccessDeniedError("Пользователи с ролью USER не могут создавать товары")

    seller_id = user.id if user.role == UserRole.SELLER else data.get("seller_id")
    # Конвертируем Pydantic-enum в ORM-enum (data["status"] может быть Pydantic-enum из generated models)
    raw_status = data["status"]
    orm_status = ProductStatus(raw_status.value if hasattr(raw_status, "value") else raw_status)
    return await repository.create_product(
        db,
        name=data["name"],
        description=data.get("description"),
        price=data["price"],
        stock=data["stock"],
        category=data["category"],
        status=orm_status,
        seller_id=seller_id,
    )


async def update_product(db: AsyncSession, product_id: int, data: dict, user: User) -> Product:
    if user.role == UserRole.USER:
        raise AccessDeniedError("Пользователи с ролью USER не могут изменять товары")

    product = await get_product(db, product_id)
    _check_product_ownership(product, user)

    # Конвертируем status если передан
    if "status" in data and data["status"] is not None:
        raw = data["status"]
        data["status"] = ProductStatus(raw.value if hasattr(raw, "value") else raw)

    return await repository.update_product(db, product, **{k: v for k, v in data.items() if v is not None})


async def archive_product(db: AsyncSession, product_id: int, user: User) -> Product:
    if user.role == UserRole.USER:
        raise AccessDeniedError("Пользователи с ролью USER не могут удалять товары")

    product = await get_product(db, product_id)
    _check_product_ownership(product, user)

    return await repository.update_product(db, product, status=ProductStatus.ARCHIVED)

from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Product, ProductStatus


async def get_by_id(db: AsyncSession, product_id: int) -> Optional[Product]:
    result = await db.execute(select(Product).where(Product.id == product_id))
    return result.scalar_one_or_none()


async def list_products(
    db: AsyncSession,
    page: int,
    size: int,
    status: Optional[ProductStatus] = None,
    category: Optional[str] = None,
) -> tuple[list[Product], int]:
    query = select(Product)
    count_query = select(func.count()).select_from(Product)

    if status is not None:
        query = query.where(Product.status == status)
        count_query = count_query.where(Product.status == status)
    if category is not None:
        query = query.where(Product.category == category)
        count_query = count_query.where(Product.category == category)

    total = (await db.execute(count_query)).scalar_one()
    products = (await db.execute(query.offset(page * size).limit(size))).scalars().all()
    return list(products), total


async def create_product(
    db: AsyncSession,
    name: str,
    description: Optional[str],
    price: Decimal,
    stock: int,
    category: str,
    status: ProductStatus,
    seller_id: Optional[int],
) -> Product:
    product = Product(
        name=name,
        description=description,
        price=price,
        stock=stock,
        category=category,
        status=status,
        seller_id=seller_id,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


async def update_product(db: AsyncSession, product: Product, **fields) -> Product:
    for key, value in fields.items():
        if value is not None:
            setattr(product, key, value)
    await db.commit()
    await db.refresh(product)
    return product

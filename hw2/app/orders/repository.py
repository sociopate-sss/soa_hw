from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Order, OrderItem, OrderStatus


async def get_by_id(db: AsyncSession, order_id: int) -> Optional[Order]:
    result = await db.execute(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
    )
    return result.scalar_one_or_none()


async def get_active_order_for_user(db: AsyncSession, user_id: int) -> Optional[Order]:
    """Возвращает активный заказ пользователя (CREATED или PAYMENT_PENDING)."""
    result = await db.execute(
        select(Order).where(
            Order.user_id == user_id,
            Order.status.in_([OrderStatus.CREATED, OrderStatus.PAYMENT_PENDING]),
        )
    )
    return result.scalar_one_or_none()

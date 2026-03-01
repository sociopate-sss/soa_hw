from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AccessDeniedError, PromoCodeConflictError
from app.models.orm import PromoCode, UserRole, User


async def create_promo_code(db: AsyncSession, data: dict, user: User) -> PromoCode:
    if user.role == UserRole.USER:
        raise AccessDeniedError("Пользователи с ролью USER не могут создавать промокоды")

    # Проверяем уникальность кода
    existing = await db.execute(select(PromoCode).where(PromoCode.code == data["code"]))
    if existing.scalar_one_or_none():
        raise PromoCodeConflictError()

    from app.models.orm import DiscountType
    raw_dt = data["discount_type"]
    orm_discount_type = DiscountType(raw_dt.value if hasattr(raw_dt, "value") else raw_dt)

    promo = PromoCode(
        code=data["code"],
        discount_type=orm_discount_type,
        discount_value=data["discount_value"],
        min_order_amount=data["min_order_amount"],
        max_uses=data["max_uses"],
        valid_from=data["valid_from"],
        valid_until=data["valid_until"],
        active=True,
        current_uses=0,
    )
    db.add(promo)
    await db.commit()
    await db.refresh(promo)
    return promo

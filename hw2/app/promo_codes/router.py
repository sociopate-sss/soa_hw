from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.orm import User
from app.promo_codes import service
from generated.models import PromoCodeCreate, PromoCodeResponse

router = APIRouter(prefix="/promo-codes", tags=["promo-codes"])


@router.post("", response_model=PromoCodeResponse, status_code=status.HTTP_201_CREATED)
async def create_promo_code(
    body: PromoCodeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    promo = await service.create_promo_code(db, body.model_dump(), current_user)
    return PromoCodeResponse(
        id=promo.id,
        code=promo.code,
        discount_type=promo.discount_type.value,   # ORM-enum → строка
        discount_value=float(promo.discount_value),
        min_order_amount=float(promo.min_order_amount),
        max_uses=promo.max_uses,
        current_uses=promo.current_uses,
        valid_from=promo.valid_from,
        valid_until=promo.valid_until,
        active=promo.active,
    )

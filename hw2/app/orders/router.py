from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.orm import User
from app.orders import service
from generated.models import OrderCreate, OrderUpdate, OrderResponse, OrderItemResponse

router = APIRouter(prefix="/orders", tags=["orders"])


def _to_response(order) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        user_id=order.user_id,
        status=order.status.value,   # ORM-enum → строка для Pydantic
        items=[
            OrderItemResponse(
                id=item.id,
                product_id=item.product_id,
                quantity=item.quantity,
                price_at_order=float(item.price_at_order),
            )
            for item in order.items
        ],
        promo_code_id=order.promo_code_id,
        total_amount=float(order.total_amount),
        discount_amount=float(order.discount_amount),
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = [item.model_dump() for item in body.items]
    order = await service.create_order(db, current_user, items, body.promo_code)
    return _to_response(order)


@router.get("/{id}", response_model=OrderResponse)
async def get_order(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = await service.get_order(db, id, current_user)
    return _to_response(order)


@router.put("/{id}", response_model=OrderResponse)
async def update_order(
    id: int,
    body: OrderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = [item.model_dump() for item in body.items]
    order = await service.update_order(db, id, current_user, items)
    return _to_response(order)


@router.post("/{id}/cancel", response_model=OrderResponse)
async def cancel_order(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = await service.cancel_order(db, id, current_user)
    return _to_response(order)

"""
Бизнес-логика заказов.
Реализует все проверки и инварианты, описанные в задании:
  - rate limiting через user_operations
  - проверка активных заказов
  - проверка статуса и остатков товаров
  - резервирование stock в транзакции
  - снапшот цен (price_at_order)
  - промокоды (PERCENTAGE / FIXED_AMOUNT, max 70% скидка)
  - конечный автомат состояний заказа
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import (
    OrderNotFoundError, OrderLimitExceededError, OrderHasActiveError,
    ProductNotFoundError, ProductInactiveError, InsufficientStockError,
    PromoCodeInvalidError, PromoCodeMinAmountError,
    InvalidStateTransitionError, OrderOwnershipViolationError, AccessDeniedError,
)
from app.models.orm import (
    Order, OrderItem, OrderStatus, Product, ProductStatus,
    PromoCode, DiscountType, UserOperation, OperationType,
    UserRole, User, ORDER_STATE_TRANSITIONS,
)
from app.orders import repository


def _check_order_access(order: Order, user: User) -> None:
    """Проверяет, что пользователь может работать с заказом."""
    if user.role == UserRole.SELLER:
        raise AccessDeniedError("SELLER не может работать с заказами")
    if user.role == UserRole.USER and order.user_id != user.id:
        raise OrderOwnershipViolationError()


async def _check_rate_limit(db: AsyncSession, user_id: int, op_type: OperationType) -> None:
    """Проверяет, что с момента последней операции прошло >= N минут."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.ORDER_RATE_LIMIT_MINUTES)
    result = await db.execute(
        select(UserOperation)
        .where(
            UserOperation.user_id == user_id,
            UserOperation.operation_type == op_type,
            UserOperation.created_at > cutoff,
        )
        .order_by(UserOperation.created_at.desc())
        .limit(1)
    )
    if result.scalar_one_or_none():
        raise OrderLimitExceededError(settings.ORDER_RATE_LIMIT_MINUTES)


async def _validate_and_reserve_items(
    db: AsyncSession,
    items: list[dict],
) -> tuple[list[tuple[Product, int]], Decimal]:
    """
    Для каждой позиции:
    1. Проверяет, что товар существует и ACTIVE
    2. Проверяет достаточность остатков
    3. Резервирует stock (уменьшает)
    Возвращает список (product, quantity) и total_amount (без скидки).
    """
    product_ids = [item["product_id"] for item in items]
    result = await db.execute(
        select(Product).where(Product.id.in_(product_ids))
    )
    products_by_id: dict[int, Product] = {p.id: p for p in result.scalars().all()}

    # Агрегируем количество по product_id (на случай дублей в items)
    qty_by_product: dict[int, int] = {}
    for item in items:
        pid = item["product_id"]
        qty_by_product[pid] = qty_by_product.get(pid, 0) + item["quantity"]

    # Проверяем существование и статус
    for pid in qty_by_product:
        if pid not in products_by_id:
            raise ProductNotFoundError(pid)
        if products_by_id[pid].status != ProductStatus.ACTIVE:
            raise ProductInactiveError(pid)

    # Проверяем остатки (собираем все недостающие сразу)
    insufficient = []
    for pid, qty in qty_by_product.items():
        p = products_by_id[pid]
        if p.stock < qty:
            insufficient.append({
                "product_id": pid,
                "requested": qty,
                "available": p.stock,
            })
    if insufficient:
        raise InsufficientStockError(insufficient)

    # Резервируем остатки
    result_pairs = []
    total = Decimal("0")
    for item in items:
        pid = item["product_id"]
        qty = item["quantity"]
        p = products_by_id[pid]
        p.stock -= qty
        total += Decimal(str(p.price)) * qty
        result_pairs.append((p, qty))

    return result_pairs, total


async def _apply_promo_code(
    db: AsyncSession, code: str, total: Decimal
) -> tuple[Optional[PromoCode], Decimal]:
    """
    Проверяет и применяет промокод. Возвращает (promo, discount_amount).
    Для PERCENTAGE: скидка не более 70% от суммы.
    Инкрементирует current_uses.
    """
    result = await db.execute(select(PromoCode).where(PromoCode.code == code))
    promo = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if promo is None or not promo.active:
        raise PromoCodeInvalidError("Промокод не найден или неактивен")
    if promo.current_uses >= promo.max_uses:
        raise PromoCodeInvalidError("Промокод исчерпан")
    if now < promo.valid_from or now > promo.valid_until:
        raise PromoCodeInvalidError("Промокод вышел за пределы срока действия")

    min_amount = Decimal(str(promo.min_order_amount))
    if total < min_amount:
        raise PromoCodeMinAmountError(float(min_amount), float(total))

    discount_value = Decimal(str(promo.discount_value))
    if promo.discount_type == DiscountType.PERCENTAGE:
        discount = total * discount_value / 100
        max_discount = total * Decimal("0.70")
        discount = min(discount, max_discount)
    else:  # FIXED_AMOUNT
        discount = min(discount_value, total)

    discount = discount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    promo.current_uses += 1
    return promo, discount


async def create_order(db: AsyncSession, user: User, items: list[dict], promo_code: Optional[str]) -> Order:
    if user.role == UserRole.SELLER:
        raise AccessDeniedError("SELLER не может создавать заказы")

    # 1. Rate limit
    await _check_rate_limit(db, user.id, OperationType.CREATE_ORDER)

    # 2. Активный заказ
    active = await repository.get_active_order_for_user(db, user.id)
    if active:
        raise OrderHasActiveError()

    # 3+4+5. Проверка товаров и резервирование остатков
    product_pairs, total = await _validate_and_reserve_items(db, items)

    # 6+7. Промокод
    promo = None
    discount = Decimal("0")
    if promo_code:
        promo, discount = await _apply_promo_code(db, promo_code, total)

    final_total = total - discount

    # 8. Создаём заказ
    order = Order(
        user_id=user.id,
        status=OrderStatus.CREATED,
        promo_code_id=promo.id if promo else None,
        total_amount=final_total,
        discount_amount=discount,
    )
    db.add(order)
    await db.flush()  # получаем order.id

    # Создаём позиции с снапшотом цен
    for product, qty in product_pairs:
        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=qty,
            price_at_order=product.price,
        )
        db.add(item)

    # 9. Фиксируем операцию
    op = UserOperation(user_id=user.id, operation_type=OperationType.CREATE_ORDER)
    db.add(op)

    await db.commit()
    await db.refresh(order)

    # Загружаем items для ответа
    result = await db.execute(
        select(Order).where(Order.id == order.id).options(selectinload(Order.items))
    )
    return result.scalar_one()


async def get_order(db: AsyncSession, order_id: int, user: User) -> Order:
    order = await repository.get_by_id(db, order_id)
    if order is None:
        raise OrderNotFoundError()
    _check_order_access(order, user)
    return order


async def update_order(db: AsyncSession, order_id: int, user: User, new_items: list[dict]) -> Order:
    if user.role == UserRole.SELLER:
        raise AccessDeniedError("SELLER не может изменять заказы")

    order = await repository.get_by_id(db, order_id)
    if order is None:
        raise OrderNotFoundError()

    _check_order_access(order, user)

    # Обновление разрешено только из CREATED
    if order.status != OrderStatus.CREATED:
        raise InvalidStateTransitionError(order.status.value, "update")

    # Rate limit на обновление
    await _check_rate_limit(db, user.id, OperationType.UPDATE_ORDER)

    # Возвращаем предыдущие остатки
    for old_item in order.items:
        result = await db.execute(select(Product).where(Product.id == old_item.product_id))
        product = result.scalar_one()
        product.stock += old_item.quantity

    # Удаляем старые позиции
    for old_item in list(order.items):
        await db.delete(old_item)
    await db.flush()

    # Резервируем новые остатки
    product_pairs, total = await _validate_and_reserve_items(db, new_items)

    # Пересчитываем промокод
    promo = None
    discount = Decimal("0")
    if order.promo_code_id:
        result = await db.execute(select(PromoCode).where(PromoCode.id == order.promo_code_id))
        existing_promo = result.scalar_one_or_none()
        if existing_promo:
            try:
                existing_promo.current_uses -= 1  # временно сбрасываем
                promo, discount = await _apply_promo_code(db, existing_promo.code, total)
            except Exception:
                # Промокод больше не применим — снимаем скидку
                existing_promo.current_uses += 1  # откатываем декремент
                order.promo_code_id = None

    final_total = total - discount

    # Обновляем заказ
    order.total_amount = final_total
    order.discount_amount = discount
    order.promo_code_id = promo.id if promo else None

    # Создаём новые позиции
    for product, qty in product_pairs:
        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=qty,
            price_at_order=product.price,
        )
        db.add(item)

    # Фиксируем операцию
    op = UserOperation(user_id=user.id, operation_type=OperationType.UPDATE_ORDER)
    db.add(op)

    await db.commit()

    result = await db.execute(
        select(Order).where(Order.id == order.id).options(selectinload(Order.items))
    )
    return result.scalar_one()


async def cancel_order(db: AsyncSession, order_id: int, user: User) -> Order:
    if user.role == UserRole.SELLER:
        raise AccessDeniedError("SELLER не может отменять заказы")

    order = await repository.get_by_id(db, order_id)
    if order is None:
        raise OrderNotFoundError()

    _check_order_access(order, user)

    # Отмена разрешена только из CREATED / PAYMENT_PENDING
    cancellable = {OrderStatus.CREATED, OrderStatus.PAYMENT_PENDING}
    if order.status not in cancellable:
        raise InvalidStateTransitionError(order.status.value, "CANCELED")

    # Возвращаем остатки на склад
    for item in order.items:
        result = await db.execute(select(Product).where(Product.id == item.product_id))
        product = result.scalar_one()
        product.stock += item.quantity

    # Возвращаем использование промокода
    if order.promo_code_id:
        result = await db.execute(select(PromoCode).where(PromoCode.id == order.promo_code_id))
        promo = result.scalar_one_or_none()
        if promo and promo.current_uses > 0:
            promo.current_uses -= 1

    order.status = OrderStatus.CANCELED
    await db.commit()

    result = await db.execute(
        select(Order).where(Order.id == order.id).options(selectinload(Order.items))
    )
    return result.scalar_one()

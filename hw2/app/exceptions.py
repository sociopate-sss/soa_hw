"""
Кастомные исключения с кодами ошибок из контракта OpenAPI.
Каждое исключение соответствует error_code в спецификации.
"""
from typing import Any


class AppError(Exception):
    """Базовый класс для бизнес-ошибок."""
    def __init__(self, error_code: str, message: str, http_status: int, details: Any = None):
        self.error_code = error_code
        self.message = message
        self.http_status = http_status
        self.details = details
        super().__init__(message)


class ProductNotFoundError(AppError):
    def __init__(self, product_id: int = None):
        msg = f"Товар не найден" if product_id is None else f"Товар {product_id} не найден"
        super().__init__("PRODUCT_NOT_FOUND", msg, 404)


class ProductInactiveError(AppError):
    def __init__(self, product_id: int = None):
        msg = f"Товар не активен" if product_id is None else f"Товар {product_id} не активен"
        super().__init__("PRODUCT_INACTIVE", msg, 409)


class OrderNotFoundError(AppError):
    def __init__(self):
        super().__init__("ORDER_NOT_FOUND", "Заказ не найден", 404)


class OrderLimitExceededError(AppError):
    def __init__(self, minutes: int):
        super().__init__(
            "ORDER_LIMIT_EXCEEDED",
            f"Превышен лимит частоты операций. Повторите через {minutes} мин.",
            429,
        )


class OrderHasActiveError(AppError):
    def __init__(self):
        super().__init__(
            "ORDER_HAS_ACTIVE",
            "У пользователя уже есть активный заказ в состоянии CREATED или PAYMENT_PENDING",
            409,
        )


class InvalidStateTransitionError(AppError):
    def __init__(self, current: str, target: str = None):
        msg = (
            f"Недопустимый переход из состояния {current}"
            if target is None
            else f"Недопустимый переход из {current} в {target}"
        )
        super().__init__("INVALID_STATE_TRANSITION", msg, 409)


class InsufficientStockError(AppError):
    def __init__(self, items: list[dict]):
        super().__init__(
            "INSUFFICIENT_STOCK",
            "Недостаточно товара на складе",
            409,
            details={"insufficient_items": items},
        )


class PromoCodeInvalidError(AppError):
    def __init__(self, reason: str = "Промокод недействителен"):
        super().__init__("PROMO_CODE_INVALID", reason, 422)


class PromoCodeMinAmountError(AppError):
    def __init__(self, min_amount: float, current_amount: float):
        super().__init__(
            "PROMO_CODE_MIN_AMOUNT",
            f"Сумма заказа {current_amount} ниже минимальной {min_amount} для промокода",
            422,
            details={"min_order_amount": min_amount, "current_amount": current_amount},
        )


class OrderOwnershipViolationError(AppError):
    def __init__(self):
        super().__init__("ORDER_OWNERSHIP_VIOLATION", "Заказ принадлежит другому пользователю", 403)


class ValidationError(AppError):
    def __init__(self, details: Any):
        super().__init__("VALIDATION_ERROR", "Ошибка валидации входных данных", 400, details)


class TokenExpiredError(AppError):
    def __init__(self):
        super().__init__("TOKEN_EXPIRED", "Токен истёк", 401)


class TokenInvalidError(AppError):
    def __init__(self):
        super().__init__("TOKEN_INVALID", "Невалидный токен", 401)


class RefreshTokenInvalidError(AppError):
    def __init__(self):
        super().__init__("REFRESH_TOKEN_INVALID", "Невалидный refresh token", 401)


class AccessDeniedError(AppError):
    def __init__(self, message: str = "Недостаточно прав"):
        super().__init__("ACCESS_DENIED", message, 403)


class UsernameConflictError(AppError):
    def __init__(self):
        super().__init__("USERNAME_CONFLICT", "Имя пользователя уже занято", 409)


class PromoCodeConflictError(AppError):
    def __init__(self):
        super().__init__("PROMO_CODE_CONFLICT", "Промокод с таким кодом уже существует", 409)

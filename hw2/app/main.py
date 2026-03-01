"""
Точка входа FastAPI-приложения.
Регистрирует роутеры, middleware, обработчики ошибок.
"""
import json
import logging
import sys

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pythonjsonlogger import jsonlogger

from app.exceptions import AppError
from app.middleware.logging import RequestLoggingMiddleware
from app.auth.router import router as auth_router
from app.products.router import router as products_router
from app.orders.router import router as orders_router
from app.promo_codes.router import router as promo_codes_router

# ── Настройка JSON-логирования ────────────────────────────────────────────────

class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Объединяет стандартные поля logRecord с нашими json_fields из middleware."""
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        if hasattr(record, "json_fields"):
            log_record.update(record.json_fields)


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(CustomJsonFormatter())
logging.getLogger("api").addHandler(handler)
logging.getLogger("api").setLevel(logging.INFO)
logging.getLogger("api").propagate = False

# ── Приложение ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Marketplace API",
    description="API сервиса маркетплейса",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(RequestLoggingMiddleware)

# ── Обработчики ошибок ────────────────────────────────────────────────────────

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    """Единый формат ответа для всех бизнес-ошибок."""
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """
    Перехватывает ошибки валидации Pydantic и возвращает
    контрактный формат VALIDATION_ERROR с деталями по каждому полю.
    """
    details = []
    for error in exc.errors():
        details.append({
            "field": " -> ".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })
    return JSONResponse(
        status_code=400,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "Ошибка валидации входных данных",
            "details": {"errors": details},
        },
    )


# ── Роутеры ───────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(products_router)
app.include_router(orders_router)
app.include_router(promo_codes_router)


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}

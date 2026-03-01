"""
Middleware для JSON-логирования каждого API-запроса.

Логирует: request_id, method, endpoint, status_code, duration_ms,
user_id (из JWT если есть), timestamp, и тело запроса для мутирующих методов.
"""
import json
import time
import uuid
import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

import jwt as pyjwt
from app.config import settings

logger = logging.getLogger("api")

MUTABLE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}
SENSITIVE_FIELDS = {"password", "password_hash", "refresh_token"}


def _mask_sensitive(data: dict) -> dict:
    """Маскирует чувствительные поля в логе запроса."""
    if not isinstance(data, dict):
        return data
    return {
        k: "***" if k in SENSITIVE_FIELDS else v
        for k, v in data.items()
    }


def _extract_user_id(request: Request) -> str | None:
    """Извлекает user_id из JWT-токена без валидации (только для логирования)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    try:
        payload = pyjwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload.get("sub")
    except Exception:
        return None


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        start_time = time.time()
        user_id = _extract_user_id(request)

        # Читаем тело запроса для мутирующих методов
        request_body = None
        if request.method in MUTABLE_METHODS:
            try:
                body_bytes = await request.body()
                if body_bytes:
                    body = json.loads(body_bytes)
                    request_body = _mask_sensitive(body) if isinstance(body, dict) else body
            except Exception:
                request_body = "<non-json body>"

        # Прокидываем request_id в state для доступа из обработчиков
        request.state.request_id = request_id

        response = await call_next(request)

        duration_ms = round((time.time() - start_time) * 1000, 2)

        log_record = {
            "request_id": request_id,
            "method": request.method,
            "endpoint": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "user_id": user_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if request_body is not None:
            log_record["request_body"] = request_body

        logger.info("", extra={"json_fields": log_record})

        # Пробрасываем request_id в заголовок ответа
        response.headers["X-Request-Id"] = request_id
        return response

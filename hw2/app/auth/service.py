"""
Сервис аутентификации: регистрация, вход, обновление токенов.
JWT: access token (15 мин) + refresh token (30 дней).
"""
from datetime import datetime, timezone, timedelta

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import (
    RefreshTokenInvalidError, TokenInvalidError, UsernameConflictError,
)
from app.models.orm import User, RefreshToken, UserRole


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _create_token(user_id: int, role: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def register_user(username: str, password: str, role: UserRole, db: AsyncSession) -> User:
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        raise UsernameConflictError()

    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def login_user(username: str, password: str, db: AsyncSession) -> tuple[str, str]:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        raise TokenInvalidError()

    access_token = _create_token(
        user.id, user.role.value, "access",
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token_str = _create_token(
        user.id, user.role.value, "refresh",
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    # Сохраняем refresh token в БД для возможности инвалидации
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    rt = RefreshToken(user_id=user.id, token=refresh_token_str, expires_at=expires_at)
    db.add(rt)
    await db.commit()

    return access_token, refresh_token_str


async def refresh_access_token(refresh_token_str: str, db: AsyncSession) -> tuple[str, str]:
    # Проверяем подпись и срок
    try:
        payload = jwt.decode(
            refresh_token_str, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
    except jwt.ExpiredSignatureError:
        raise RefreshTokenInvalidError()
    except jwt.PyJWTError:
        raise RefreshTokenInvalidError()

    if payload.get("type") != "refresh":
        raise RefreshTokenInvalidError()

    # Проверяем наличие в БД (не был ли отозван)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token == refresh_token_str)
    )
    rt = result.scalar_one_or_none()
    if rt is None:
        raise RefreshTokenInvalidError()

    user_id = int(payload["sub"])
    role = payload["role"]

    # Ротируем refresh token: удаляем старый, создаём новый
    await db.delete(rt)

    new_access = _create_token(
        user_id, role, "access",
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    new_refresh = _create_token(
        user_id, role, "refresh",
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    new_rt = RefreshToken(user_id=user_id, token=new_refresh, expires_at=expires_at)
    db.add(new_rt)
    await db.commit()

    return new_access, new_refresh

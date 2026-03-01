"""
FastAPI-зависимости: получение текущего пользователя из JWT, проверка ролей.
"""
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.exceptions import TokenExpiredError, TokenInvalidError, AccessDeniedError
from app.models.orm import User, UserRole
import jwt
from app.config import settings

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise TokenInvalidError()

    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError()
    except jwt.PyJWTError:
        raise TokenInvalidError()

    token_type = payload.get("type")
    if token_type != "access":
        raise TokenInvalidError()

    user_id = payload.get("sub")
    if user_id is None:
        raise TokenInvalidError()

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise TokenInvalidError()

    return user


def require_roles(*roles: UserRole):
    """Фабрика зависимости, проверяющей роль пользователя."""
    async def check_role(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise AccessDeniedError(
                f"Роль {current_user.role.value} не имеет доступа к этой операции"
            )
        return current_user
    return check_role

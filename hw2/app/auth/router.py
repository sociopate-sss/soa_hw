from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import service
from app.models.orm import UserRole as OrmUserRole
# Импортируем из сгенерированных моделей
from generated.models import RegisterRequest, LoginRequest, RefreshRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Конвертируем Pydantic-enum (generated) в ORM-enum
    role = OrmUserRole(body.role.value)
    user = await service.register_user(
        username=body.username,
        password=body.password,
        role=role,
        db=db,
    )
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role.value,   # ORM-enum → строка → Pydantic coerce
        created_at=user.created_at,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    access_token, refresh_token = await service.login_user(
        username=body.username,
        password=body.password,
        db=db,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    access_token, new_refresh = await service.refresh_access_token(
        refresh_token_str=body.refresh_token,
        db=db,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        token_type="bearer",
    )

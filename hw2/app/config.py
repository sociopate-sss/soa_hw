from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://marketplace:marketplace_pass@localhost:5432/marketplace"
    SECRET_KEY: str = "super-secret-jwt-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    # Минимальный интервал между операциями (в минутах)
    ORDER_RATE_LIMIT_MINUTES: int = 1

    class Config:
        env_file = ".env"


settings = Settings()

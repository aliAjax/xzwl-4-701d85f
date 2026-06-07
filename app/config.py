from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True
    )

    DATABASE_URL: str = "sqlite:///./medical_rental.db"

    JWT_SECRET_KEY: str = "your-super-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    APP_NAME: str = "Medical Equipment Rental System"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True

    OVERDUE_DAILY_RATE: float = 50.0
    OVERDUE_GRACE_PERIOD_DAYS: int = 1

    DEVICE_LOCK_TIMEOUT_MINUTES: int = 30


settings = Settings()

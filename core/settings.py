from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/fb_fanpage"

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 1440

    # Facebook OAuth
    FACEBOOK_APP_ID: str = ""
    FACEBOOK_APP_SECRET: str = ""
    FACEBOOK_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/facebook/callback"
    FACEBOOK_GRAPH_API_URL: str = "https://graph.facebook.com/v21.0"

    # X (Twitter) API
    X_COOKIES: str = ""

    # Douyin
    DOUYIN_COOKIES: str = ""

    # Grok (xAI) LLM
    XAI_API_KEY: str = ""
    XAI_MODEL: str = "grok-3-mini"

    # Server
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()

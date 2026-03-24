from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/profile_db"

    JWT_SECRET_KEY: str = "change-me-to-a-real-secret-key-min-32"
    JWT_ALGORITHM: str = "HS256"

    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_NAME: str = "avatars"
    MINIO_USE_SSL: bool = False

    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5673/"

    INTERNAL_SECRET: str = "secret"

    APP_ENV: str = "development"
    DEBUG: bool = True


settings = Settings()

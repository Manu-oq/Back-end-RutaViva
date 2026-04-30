from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Ruta Viva"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"

    postgres_user: str = "admin"
    postgres_password: str = "admin"
    postgres_db: str = "rutaviva_db"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    secret_key: str = "a9c2d3f4e5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def async_database_uri(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()

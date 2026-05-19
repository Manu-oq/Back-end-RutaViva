from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Ruta Viva"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"

    postgres_user: str = Field(
        default="admin",
        validation_alias=AliasChoices("POSTGRES_USER", "postgres_user"),
    )
    postgres_password: str = Field(
        default="admin",
        validation_alias=AliasChoices("POSTGRES_PASSWORD", "postgres_password"),
    )
    postgres_db: str = Field(
        default="rutaviva_db",
        validation_alias=AliasChoices("POSTGRES_DB", "postgres_db"),
    )
    postgres_host: str = Field(
        default="localhost",
        validation_alias=AliasChoices("POSTGRES_HOST", "postgres_host"),
    )
    postgres_port: int = Field(
        default=5432,
        validation_alias=AliasChoices("POSTGRES_PORT", "postgres_port"),
    )

    openai_api_key: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_timeout_seconds: float = 90.0
    ara_chat_timeout_seconds: float = 8.0
    openweather_api_key: str | None = None

    secret_key: str
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

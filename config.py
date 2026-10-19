from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    db_path: str = "./financas.db"
    checkpoints_path: str = "./checkpoints.db"
    max_context_messages: int = 40

    # Telegram Bot (MVP 3)
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = "change-me-in-production"
    telegram_webhook_url: str = ""


settings = Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    db_path: str = "./financas.db"
    checkpoints_path: str = "./checkpoints.db"
    max_expense_amount: float = 100_000.0
    max_context_messages: int = 40

    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "financas-ia-mvp1"


settings = Settings()

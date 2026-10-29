"""Shared model configuration for the Telegram agent and classification."""

from langchain_openai import ChatOpenAI

from config import settings


def create_chat_model(
    *, timeout: float | None = None, max_retries: int | None = None
) -> ChatOpenAI:
    options = {}
    if timeout is not None:
        options["timeout"] = timeout
    if max_retries is not None:
        options["max_retries"] = max_retries
    return ChatOpenAI(
        model=settings.openai_model,
        temperature=0,
        api_key=settings.openai_api_key,
        **options,
    )

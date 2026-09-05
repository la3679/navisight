"""Choosing a provider from configuration.

One function, so "which model is answering, and is it configured?" has exactly
one answer in the codebase. Everything above this reads
:func:`build_provider` and never touches an environment variable.
"""

from __future__ import annotations

from app.agent.provider import LLMProvider, ProviderError
from app.agent.providers.mock import MockProvider
from app.config import Settings


def effective_model(settings: Settings) -> str:
    """The model that will actually answer, including a provider's default.

    ``LLM_MODEL`` is optional and each provider falls back to its own default,
    so the setting alone does not say what will answer. Resolving it in one
    place is what keeps ``/agent/status`` and the answer footer from disagreeing
    — the status route said the model was empty while every answer named
    ``gpt-4o-mini``, and the user was left to notice.
    """
    if settings.llm_model:
        return settings.llm_model
    if settings.llm_provider == "openai":
        from app.agent.providers.openai_provider import DEFAULT_MODEL

        return DEFAULT_MODEL
    if settings.llm_provider == "mock":
        return MockProvider.DEFAULT_MODEL
    return ""


def build_provider(settings: Settings) -> LLMProvider:
    """Construct the configured provider.

    Raises :class:`ProviderError` when the configuration is incomplete, so the
    caller can turn it into the not-configured response rather than a 500.
    """
    if settings.llm_provider == "mock":
        return MockProvider(model=effective_model(settings))

    if settings.llm_provider == "openai":
        from app.agent.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=effective_model(settings),
            timeout_seconds=settings.agent_timeout_seconds,
        )

    raise ProviderError(
        "No AI provider is configured. Set LLM_PROVIDER to 'openai' (with "
        "OPENAI_API_KEY in the backend environment) or to 'mock' for the "
        "deterministic offline provider."
    )


def describe(settings: Settings) -> dict[str, str | bool]:
    """What the client needs to render the copilot's state.

    Deliberately contains the provider *name* and model, never a credential —
    this is serialized into an API response.
    """
    return {
        "configured": settings.ai_enabled,
        "provider": settings.llm_provider,
        "model": effective_model(settings),
        "deterministic": settings.llm_provider == "mock",
    }

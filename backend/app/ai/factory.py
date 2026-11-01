"""Choose the AI provider from settings.

Providers are built on demand (not at import or startup), so a missing API key only affects AI
features; the rest of the app keeps working.
"""

from app.ai.fake import FakeAIProvider
from app.ai.provider import AIProvider, AIUnavailableError
from app.core.config import Settings, get_settings


def build_ai_provider(settings: Settings) -> AIProvider:
    match settings.ai_provider:
        case "fake":
            return FakeAIProvider()
        case "anthropic":
            # The key is a SecretStr and is not read here: only the Anthropic provider (Issue #2)
            # may call get_secret_value(). Never include the key in messages or logs.
            if settings.anthropic_api_key is None:
                raise AIUnavailableError(
                    "AI_PROVIDER=anthropic requires ANTHROPIC_API_KEY. Set it, or use "
                    "AI_PROVIDER=fake for local development."
                )
            raise AIUnavailableError(
                "The Anthropic provider is not available yet. Use AI_PROVIDER=fake."
            )
        case other:  # unreachable while Settings validates the value; kept as a safety net
            raise AIUnavailableError(f"Unknown AI provider '{other}'. Use 'fake' or 'anthropic'.")


def get_ai_provider() -> AIProvider:
    """FastAPI dependency for AI routes (tests can override it with any AIProvider)."""
    return build_ai_provider(get_settings())

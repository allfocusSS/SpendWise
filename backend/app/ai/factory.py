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
            # Never include the key itself in messages or logs.
            if not settings.anthropic_api_key:
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

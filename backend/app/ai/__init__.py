"""AI providers. They interpret text and backend-calculated figures; they never do money math."""

from app.ai.factory import build_ai_provider, get_ai_provider
from app.ai.fake import FakeAIProvider
from app.ai.provider import AIProvider, AIUnavailableError

__all__ = [
    "AIProvider",
    "AIUnavailableError",
    "FakeAIProvider",
    "build_ai_provider",
    "get_ai_provider",
]

import os
import re
from typing import Any

import httpx

from app.rag.providers import PROVIDER_TIMEOUT_MS
from app.services.conversation_memory import sanitize_sensitive_text

OPENAI_MODERATION_URL = "https://api.openai.com/v1/moderations"
DEFAULT_MODERATION_MODEL = "omni-moderation-latest"

_SENSITIVE_DISCLOSURE_REQUEST = re.compile(
    r"\b(?:show|reveal|expose|print|display|give|provide|tell me|dump|leak|"
    r"what(?:'s| is)|find|return|repeat|share)\b.{0,100}\b"
    r"(?:api[_ -]?keys?|secret(?:s| keys?)?|passwords?|"
    r"access[_ -]?tokens?|credentials?|system prompts?|hidden instructions?|"
    r"environment variables?|(?:[a-z0-9]+_)?api[_ -]?key|"
    r"(?:[a-z0-9]+_)*secret(?:_access)?_key|\.env|"
    r"private customer (?:data|details|orders?)|"
    r"(?:another|other) customer'?s private (?:data|details|orders?)|"
    r"(?:customer|user|account) (?:data|details|information|orders?|"
    r"email addresses?|phone numbers?))\b"
    r"|\b(?:api[_ -]?keys?|secret keys?|passwords?|access[_ -]?tokens?|"
    r"credentials?|system prompts?|hidden instructions?|environment variables?)"
    r"\s*(?:is|are|=|:)\s*\S+",
    re.IGNORECASE,
)
_SENSITIVE_OUTPUT = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|sk-proj-[A-Za-z0-9_-]{16,}|"
    r"gsk_[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._~+/-]{16,}|"
    r"(?:OPENAI|GROQ|MISTRAL|OPENAI_MODERATION)_API_KEY\s*[:=]\s*\S+|"
    r"(?:AWS|AZURE|GCP)_SECRET_ACCESS_KEY\s*[:=]\s*\S+)\b",
    re.IGNORECASE,
)
_ORDER_REFERENCE = re.compile(r"\b(?:ORD|CUS-DEMO)-[A-Z0-9_-]+\b", re.IGNORECASE)


class ModerationUnavailable(RuntimeError):
    """Raised when the configured OpenAI moderation service cannot be used."""


class OpenAIModerationService:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODERATION_MODEL,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI moderation API key is required.")
        if not model.strip():
            raise ValueError("OpenAI moderation model is required.")
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._transport = transport

    def is_flagged(self, text: str) -> bool:
        safe_text = redact_for_moderation(text)
        try:
            with httpx.Client(
                timeout=PROVIDER_TIMEOUT_MS / 1000,
                transport=self._transport,
            ) as client:
                response = client.post(
                    OPENAI_MODERATION_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "input": safe_text},
                )
                response.raise_for_status()
                payload: Any = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ModerationUnavailable(
                "OpenAI moderation request failed."
            ) from exc

        results = payload.get("results") if isinstance(payload, dict) else None
        if (
            not isinstance(results, list)
            or not results
            or not isinstance(results[0], dict)
            or not isinstance(results[0].get("flagged"), bool)
        ):
            raise ModerationUnavailable(
                "OpenAI moderation returned an invalid response."
            )
        return results[0]["flagged"]


def moderation_service_from_environment() -> OpenAIModerationService | None:
    api_key = (
        os.environ.get("OPENAI_MODERATION_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )
    if not api_key:
        return None
    model = (
        os.environ.get("OPENAI_MODERATION_MODEL", "").strip()
        or DEFAULT_MODERATION_MODEL
    )
    return OpenAIModerationService(api_key, model)


def requests_sensitive_disclosure(text: str) -> bool:
    return _SENSITIVE_DISCLOSURE_REQUEST.search(text) is not None


def contains_sensitive_output(text: str) -> bool:
    return _SENSITIVE_OUTPUT.search(text) is not None


def redact_for_moderation(text: str) -> str:
    redacted = sanitize_sensitive_text(text)
    return _ORDER_REFERENCE.sub("[redacted reference]", redacted)

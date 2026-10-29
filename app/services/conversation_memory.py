import re
from datetime import datetime, timezone

from app.storage.models import ConversationMemory, ConversationTurn
from app.storage.repository import SupportRepository

_SENSITIVE_ASSIGNMENT = re.compile(
    r"\b(?:[A-Z0-9_]*(?:API[_ -]?KEY|SECRET(?:[_ -]?ACCESS)?[_ -]?KEY|"
    r"CLIENT[_ -]?SECRET)|secret[_ -]?key|client[_ -]?secret|"
    r"password|passcode|access[_ -]?token|authorization)\b"
    r"\s*(?:is|[:=])\s*\S+",
    re.IGNORECASE,
)
_OPAQUE_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{40,}(?![A-Za-z0-9_-])")
_BEARER_TOKEN = re.compile(r"\bBearer\s+\S+", re.IGNORECASE)
_PAYMENT_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_EMAIL_ADDRESS = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_ORDER_REFERENCE = re.compile(r"\bORD-[A-Z0-9_-]+\b", re.IGNORECASE)
_CONVERSATION_RECALL_CUES = (
    "do you remember",
    "can you remember",
    "remember what we",
    "remember what i",
    "what did we talk",
    "what were we talking",
    "what did we discuss",
    "what were we discussing",
    "what did i ask",
    "what did i say",
    "what did we say",
)


class ConversationMemoryService:
    def __init__(self, repository: SupportRepository) -> None:
        self._repository = repository

    def get(
        self,
        conversation_id: str,
        owner_id: str,
    ) -> ConversationMemory | None:
        return self._repository.get_conversation_memory(conversation_id, owner_id)

    def record_turns(
        self,
        conversation_id: str,
        owner_id: str,
        user_text: str,
        assistant_text: str,
        last_order_id: str | None,
        existing: ConversationMemory | None,
    ) -> ConversationMemory:
        now = datetime.now(timezone.utc)
        turns = list(existing.turns) if existing is not None else []
        turns.extend(
            [
                ConversationTurn(
                    role="user",
                    text=sanitize_sensitive_text(user_text),
                    created_at=now,
                ),
                ConversationTurn(
                    role="assistant",
                    text=sanitize_sensitive_text(assistant_text),
                    created_at=now,
                ),
            ]
        )
        memory = ConversationMemory(
            conversation_id=conversation_id,
            owner_id=owner_id,
            turns=turns[-12:],
            last_order_id=last_order_id,
            created_at=existing.created_at if existing else now,
            updated_at=now,
            expires_at=now,
        )
        return self._repository.save_conversation_memory(memory)


def sanitize_sensitive_text(text: str) -> str:
    sanitized = _SENSITIVE_ASSIGNMENT.sub("[redacted]", text)
    sanitized = _OPAQUE_TOKEN.sub("[redacted]", sanitized)
    sanitized = _BEARER_TOKEN.sub("[redacted]", sanitized)
    sanitized = _PAYMENT_CARD.sub("[redacted]", sanitized)
    sanitized = _EMAIL_ADDRESS.sub("[redacted]", sanitized)
    return sanitized[:2000]


def is_conversation_recall_request(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9\s]", "", text.casefold())
    return any(cue in normalized for cue in _CONVERSATION_RECALL_CUES)


def format_conversation_recall(turns: list[ConversationTurn]) -> str:
    recent_turns = turns[-4:]
    if not recent_turns:
        return (
            "I don’t have earlier messages available in this chat yet. "
            "Tell me what you’d like to continue discussing, and I’ll keep "
            "the conversation in context."
        )
    labels = {"user": "You", "assistant": "I"}
    recap = "\n".join(
        f"{labels[turn.role]}: {turn.text}"
        for turn in recent_turns
    )
    return f"Yes—here’s what we discussed most recently:\n{recap}"


def unambiguous_order_context(
    turns: list[ConversationTurn],
    last_order_id: str | None,
) -> str | None:
    if len(turns) >= 2:
        recent_order_ids = {
            order_id.upper()
            for turn in turns[-2:]
            for order_id in _ORDER_REFERENCE.findall(turn.text)
        }
        if len(recent_order_ids) == 1:
            return recent_order_ids.pop()
        if len(recent_order_ids) > 1:
            return None

    conversation_order_ids = {
        order_id.upper()
        for turn in turns
        for order_id in _ORDER_REFERENCE.findall(turn.text)
    }
    if len(conversation_order_ids) == 1:
        return conversation_order_ids.pop()
    if not conversation_order_ids:
        return last_order_id
    return None

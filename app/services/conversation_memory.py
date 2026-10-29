import re
from datetime import datetime, timezone

from app.storage.models import (
    MAX_CONVERSATION_TURNS,
    ConversationMemory,
    ConversationTurn,
)
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
_WORD = re.compile(r"\b[a-z0-9]{3,}\b")
_FIRST_MESSAGE_REQUEST = re.compile(
    r"\b(?:first|initial|earliest|original)\b.{0,50}"
    r"\b(?:message|text|thing|question)\b"
    r"|\b(?:message|text|thing|question)\b.{0,50}"
    r"\b(?:first|initial|earliest|original)\b"
    r"|\bwhat\s+did\s+i\s+(?:first\s+)?(?:say|send|ask|write)\b",
    re.IGNORECASE,
)
_STOP_WORDS = frozenset(
    {
        "about",
        "and",
        "did",
        "for",
        "from",
        "have",
        "hello",
        "help",
        "here",
        "how",
        "into",
        "just",
        "message",
        "please",
        "remember",
        "said",
        "say",
        "sent",
        "that",
        "the",
        "this",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "you",
    }
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
        first_user_message = (
            existing.first_user_message if existing is not None else None
        )
        if first_user_message is None:
            first_user_message = next(
                (turn for turn in turns if turn.role == "user"),
                None,
            )
        memory = ConversationMemory(
            conversation_id=conversation_id,
            owner_id=owner_id,
            turns=turns[-MAX_CONVERSATION_TURNS:],
            first_user_message=first_user_message,
            last_order_id=last_order_id,
            created_at=existing.created_at if existing else now,
            updated_at=now,
            expires_at=now,
        )
        return self._repository.save_conversation_memory(memory)

    def classifier_context(
        self,
        memory: ConversationMemory | None,
        message: str,
    ) -> list[dict[str, str]] | None:
        if memory is None:
            return None

        recent_turns = memory.turns[-4:]
        older_turns = memory.turns[:-4]
        first_user_message = memory.first_user_message or next(
            (turn for turn in memory.turns if turn.role == "user"),
            None,
        )
        if (
            first_user_message is not None
            and all(
                turn.created_at != first_user_message.created_at
                or turn.text != first_user_message.text
                for turn in memory.turns
            )
        ):
            older_turns = [first_user_message, *older_turns]

        if _FIRST_MESSAGE_REQUEST.search(message):
            relevant_turns = (
                [first_user_message] if first_user_message is not None else []
            )
        else:
            relevant_turns = self._relevant_turns(message, older_turns, limit=2)

        selected = {
            (turn.role, turn.created_at, turn.text): turn
            for turn in [*relevant_turns, *recent_turns]
        }
        ordered_turns = sorted(
            selected.values(),
            key=lambda turn: turn.created_at,
        )[-6:]
        return [
            {"role": turn.role, "text": turn.text}
            for turn in ordered_turns
        ]

    def answer_recall(
        self,
        message: str,
        memory: ConversationMemory | None,
    ) -> str:
        if memory is None:
            return (
                "I can’t access an earlier message from this conversation. "
                "If you remind me briefly, I’ll pick it up from there."
            )

        turns = list(memory.turns)
        first_user_message = memory.first_user_message or next(
            (turn for turn in turns if turn.role == "user"),
            None,
        )
        if (
            first_user_message is not None
            and all(
                turn.created_at != first_user_message.created_at
                or turn.text != first_user_message.text
                for turn in turns
            )
        ):
            turns.insert(0, first_user_message)

        if _FIRST_MESSAGE_REQUEST.search(message):
            if first_user_message is None:
                return (
                    "I don’t have an earlier message saved in this conversation yet. "
                    "Tell me what you’d like to continue with, and I’ll keep track "
                    "as we go."
                )
            return f"Your first message was: “{first_user_message.text}”"

        relevant = self._relevant_turns(message, turns, limit=1)
        if not relevant:
            return (
                "I can see this conversation, but I’m not sure which earlier detail "
                "you mean. Could you give me a keyword or remind me briefly?"
            )
        turn = relevant[0]
        if turn.role == "user":
            return f"Earlier, you said: “{turn.text}”"
        return f"Earlier, I replied: “{turn.text}”"

    @staticmethod
    def _relevant_turns(
        message: str,
        turns: list[ConversationTurn],
        limit: int,
    ) -> list[ConversationTurn]:
        terms = {
            word
            for word in _WORD.findall(message.casefold())
            if word not in _STOP_WORDS
        }
        if not terms:
            return []

        scored_turns = []
        for index, turn in enumerate(turns):
            turn_terms = set(_WORD.findall(turn.text.casefold()))
            overlap = len(terms & turn_terms)
            if overlap:
                scored_turns.append((overlap, index, turn))
        scored_turns.sort(key=lambda result: (result[0], result[1]), reverse=True)
        return [turn for _, _, turn in scored_turns[:limit]]


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

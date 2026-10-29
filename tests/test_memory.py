from datetime import timedelta
from pathlib import Path

import pytest

from app.services.conversation_memory import (
    ConversationMemoryService,
    is_conversation_recall_request,
    unambiguous_order_context,
)
from app.storage.json_store import ConversationOwnershipError, JsonRepository


def test_conversation_recall_detection_does_not_confuse_missing_order_reference() -> None:
    assert is_conversation_recall_request(
        "Do you remember what we talked about earlier?"
    )
    assert not is_conversation_recall_request(
        "I don't remember my order number."
    )


def test_order_context_is_rejected_when_recent_exchange_mentions_multiple_orders(
    tmp_path: Path,
) -> None:
    repository = JsonRepository(tmp_path)
    service = ConversationMemoryService(repository)
    memory = service.record_turns(
        "demo-ambiguous-orders",
        "CUS-DEMO-001",
        "Compare ORD-1001 and ORD-1002.",
        "I found ORD-1001 and ORD-1002.",
        "ORD-1002",
        None,
    )

    assert unambiguous_order_context(memory.turns, memory.last_order_id) is None


def test_conversation_memory_is_bounded_and_redacts_sensitive_values(
    tmp_path: Path,
) -> None:
    repository = JsonRepository(tmp_path, max_conversation_turns=2)
    service = ConversationMemoryService(repository)
    conversation_id = "demo-conversation-001"

    first = service.record_turns(
        conversation_id,
        "CUS-DEMO-001",
        "password: secret-value and card 4111 1111 1111 1111",
        "Contact customer@example.com with access_token=secret-token",
        "ORD-1001",
        None,
    )
    assert "secret-value" not in first.turns[0].text
    assert "4111 1111 1111 1111" not in first.turns[0].text
    assert "customer@example.com" not in first.turns[1].text
    assert "secret-token" not in first.turns[1].text
    assert first.first_user_message is not None
    assert first.first_user_message.text.startswith("[redacted]")
    saved = service.record_turns(
        conversation_id,
        "CUS-DEMO-001",
        f"Retry using {'a' * 43}",
        "The current order status is processing.",
        "ORD-1001",
        repository.get_conversation_memory(
            conversation_id,
            "CUS-DEMO-001",
        ),
    )

    assert len(saved.turns) == 2
    assert saved.turns[0].role == "user"
    assert saved.turns[0].text == "Retry using [redacted]"
    assert "processing" in saved.turns[1].text
    assert saved.last_order_id == "ORD-1001"
    assert service.answer_recall("What was my first message?", saved) == (
        "Your first message was: “[redacted] and card [redacted]”"
    )
    context = service.classifier_context(
        saved,
        "Do you remember the first text I sent?",
    )
    assert context is not None
    assert any(
        turn["text"].startswith("[redacted]")
        for turn in context
    )


def test_memory_retrieves_relevant_older_turns_for_context(tmp_path: Path) -> None:
    repository = JsonRepository(tmp_path, max_conversation_turns=20)
    service = ConversationMemoryService(repository)
    conversation_id = "older-context"
    memory = None
    for index in range(5):
        memory = service.record_turns(
            conversation_id,
            "CUS-DEMO-001",
            (
                "The delivery was delayed because the address was missing."
                if index == 0
                else f"Follow-up conversation topic number {index}."
            ),
            f"Assistant response number {index}.",
            None,
            memory,
        )

    assert memory is not None
    context = service.classifier_context(memory, "What happened with the address?")
    assert context is not None
    assert any("address was missing" in turn["text"] for turn in context)


def test_conversation_memory_is_owner_scoped(tmp_path: Path) -> None:
    repository = JsonRepository(tmp_path)
    service = ConversationMemoryService(repository)
    conversation_id = "demo-conversation-002"
    service.record_turns(
        conversation_id,
        "CUS-DEMO-001",
        "Where is ORD-1001?",
        "Order status is available.",
        "ORD-1001",
        None,
    )

    assert repository.get_conversation_memory(
        conversation_id,
        "CUS-DEMO-002",
    ) is None
    with pytest.raises(ConversationOwnershipError):
        service.record_turns(
            conversation_id,
            "CUS-DEMO-002",
            "What about delivery?",
            "Please provide an order reference.",
            None,
            None,
        )


def test_expired_conversation_memory_is_removed(tmp_path: Path) -> None:
    repository = JsonRepository(
        tmp_path,
        conversation_ttl=timedelta(seconds=5),
    )
    service = ConversationMemoryService(repository)
    saved = service.record_turns(
        "demo-conversation-003",
        "CUS-DEMO-001",
        "Where is ORD-1001?",
        "Order status is available.",
        "ORD-1001",
        None,
    )

    assert repository.expire_old_conversations(
        saved.expires_at + timedelta(seconds=1)
    ) == 1
    assert repository.get_conversation_memory(
        "demo-conversation-003",
        "CUS-DEMO-001",
    ) is None

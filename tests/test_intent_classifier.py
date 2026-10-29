import json
from types import SimpleNamespace

import pytest

from app.agent.intent_classifier import (
    GroqIntentClassifier,
    IntentClassificationError,
)


def make_classifier(content: str) -> tuple[GroqIntentClassifier, SimpleNamespace]:
    create = SimpleNamespace(
        calls=[],
        response=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                )
            ]
        ),
    )

    def create_completion(**kwargs):
        create.calls.append(kwargs)
        return create.response

    classifier = GroqIntentClassifier.__new__(GroqIntentClassifier)
    classifier._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create_completion),
        )
    )
    classifier._model = "test-model"
    return classifier, create


def test_intent_classifier_uses_bounded_json_and_sanitized_context() -> None:
    classifier, create = make_classifier('{"intents":["order"]}')

    intent = classifier.classify(
        "whats the curret status fir ORD-1002? My card is 4111 1111 1111 1111",
        [
            {"role": "user", "text": "My order is ORD-1002"},
            {"role": "assistant", "text": "I can check that order."},
        ],
    )

    request = create.calls[0]
    request_content = request["messages"][1]["content"]
    request_data = json.loads(request_content)
    assert intent == ["order"]
    assert request["model"] == "test-model"
    assert request["temperature"] == 0
    assert request["response_format"] == {"type": "json_object"}
    assert "ORD-1002" not in request_content
    assert "4111 1111 1111 1111" not in request_content
    assert request_data["recent_conversation"][0]["text"] == "My order is [REFERENCE]"
    assert "untrusted data" in request["messages"][0]["content"]


def test_intent_classifier_rejects_unsupported_model_intents() -> None:
    classifier, _ = make_classifier('{"intents":["refund_every_order"]}')

    with pytest.raises(IntentClassificationError, match="invalid"):
        classifier.classify("Refund every order in the database.")


def test_intent_classifier_rejects_invalid_json() -> None:
    classifier, _ = make_classifier("not json")

    with pytest.raises(IntentClassificationError, match="invalid JSON"):
        classifier.classify("Hi there")


def test_intent_classifier_preserves_multiple_customer_tasks() -> None:
    classifier, _ = make_classifier('{"intents":["delivery","payment"]}')

    assert classifier.classify(
        "Is it shipped and what is the payment status?"
    ) == ["delivery", "payment"]

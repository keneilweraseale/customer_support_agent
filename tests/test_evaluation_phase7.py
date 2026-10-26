from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.evaluation.config import EvaluationSettings
from app.evaluation.runner import _build_judge_model, run_evaluation_case
from app.evaluation.schemas import EvaluationCase
from app.main import app

client = TestClient(app)


def test_evaluation_api_local_mode_remains_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPEVAL_ENVIRONMENT", "local")
    monkeypatch.delenv("DEEPEVAL_API_TOKEN", raising=False)

    response = client.get("/eval/health")

    assert response.status_code == 200


@pytest.mark.parametrize("authorization", [None, "Bearer wrong-token", "Basic configured-token"])
def test_nonlocal_evaluation_api_rejects_missing_or_invalid_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
    authorization: str | None,
) -> None:
    monkeypatch.setenv("DEEPEVAL_ENVIRONMENT", "production")
    monkeypatch.setenv("DEEPEVAL_API_TOKEN", "configured-evaluation-token")
    headers = {"Authorization": authorization} if authorization is not None else {}

    response = client.get("/eval/health", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert "configured-evaluation-token" not in response.text


def test_nonlocal_evaluation_api_fails_closed_without_configured_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPEVAL_ENVIRONMENT", "production")
    monkeypatch.delenv("DEEPEVAL_API_TOKEN", raising=False)

    response = client.get("/eval/health")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_nonlocal_evaluation_api_accepts_configured_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPEVAL_ENVIRONMENT", "production")
    monkeypatch.setenv("DEEPEVAL_API_TOKEN", "configured-evaluation-token")

    response = client.get(
        "/eval/metrics",
        headers={"Authorization": "Bearer configured-evaluation-token"},
    )

    assert response.status_code == 200


def test_evaluation_request_body_size_is_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPEVAL_ENVIRONMENT", "local")
    monkeypatch.setenv("DEEPEVAL_MAX_REQUEST_BODY_BYTES", "1024")
    oversized_body = b"{" + b" " * 1100 + b"}"

    response = client.post(
        "/eval/run",
        content=oversized_body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    assert "traceback" not in response.text.casefold()


def test_evaluation_concurrency_limit_returns_busy_without_running_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = EvaluationCase.model_validate(
        {
            "case_id": "PHASE7-CAPACITY",
            "category": "tool_lookup",
            "input": "Is PROD-001 available?",
            "expected_route": "tools",
        }
    )
    monkeypatch.setattr("app.evaluation.runner._active_evaluations", 1)
    settings = EvaluationSettings(max_concurrent_evaluations=1)

    result = run_evaluation_case(case, settings=settings)

    assert result.status == "busy"
    assert result.actual_output is None
    assert "capacity" in (result.error or "").casefold()


def test_judge_model_uses_configured_http_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from deepeval import models as deepeval_models
    import openai

    class FakeGPTModel:
        def __init__(self, **kwargs: Any) -> None:
            self._openai_api_key = kwargs["_openai_api_key"]
            self.model_name = kwargs["model"]

    created_clients: list[dict[str, Any]] = []

    class FakeOpenAIClient:
        def __init__(self, **kwargs: Any) -> None:
            created_clients.append(kwargs)

    monkeypatch.setattr(deepeval_models, "GPTModel", FakeGPTModel)
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAIClient)

    model = _build_judge_model(
        EvaluationSettings(
            judge_api_key="test-key",
            model="gpt-4o-mini",
            judge_timeout_seconds=17.0,
        )
    )
    model.load_model()

    assert created_clients == [{"api_key": "test-key", "timeout": 17.0}]


def test_existing_health_and_chat_routes_remain_available_in_local_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPEVAL_ENVIRONMENT", "local")

    health = client.get("/health")
    chat = client.post("/api/chat", json={"message": "Hello"})

    assert health.status_code == 200
    assert chat.status_code == 200

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.evaluation.config import get_evaluation_settings
from app.evaluation.schemas import EvaluationHealthResponse, MetricDefinition
from app.main import app


client = TestClient(app)


def test_eval_health_route_reports_readiness() -> None:
    response = client.get("/eval/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ready", "disabled"}
    assert "judge_configured" in payload
    assert "model" in payload
    assert "provider" in payload
    assert "message" in payload
    assert "judge_api_key" not in payload


def test_eval_metrics_route_lists_phase1_metrics() -> None:
    response = client.get("/eval/metrics")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["metrics"], list)
    metric_names = {entry["name"] for entry in payload["metrics"]}
    assert {"answer_relevancy", "faithfulness", "customer_support_correctness"}.issubset(metric_names)
    assert all("description" in entry and "threshold" in entry for entry in payload["metrics"])


def test_evaluation_settings_read_environment_and_hide_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPEVAL_ENABLED", "false")
    monkeypatch.setenv("DEEPEVAL_PROVIDER", "mistral")
    monkeypatch.setenv("DEEPEVAL_MODEL", "judge-model")
    monkeypatch.setenv("DEEPEVAL_JUDGE_API_KEY", "test-secret-key")
    monkeypatch.setenv("DEEPEVAL_THRESHOLD", "0.65")

    settings = get_evaluation_settings()

    assert settings.enabled is False
    assert settings.provider == "mistral"
    assert settings.model == "judge-model"
    assert settings.judge_configured is True
    assert settings.threshold == 0.65
    assert "test-secret-key" not in client.get("/eval/health").text


def test_evaluation_settings_use_provider_key_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPEVAL_JUDGE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")

    assert get_evaluation_settings().judge_configured is True


@pytest.mark.parametrize("value", ["not-a-number", "1.2", "-0.1", "nan", "inf"])
def test_invalid_threshold_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("DEEPEVAL_THRESHOLD", value)

    assert get_evaluation_settings().threshold == 0.8


def test_metrics_use_configured_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPEVAL_THRESHOLD", "0.7")

    response = client.get("/eval/metrics")

    assert response.status_code == 200
    assert {entry["threshold"] for entry in response.json()["metrics"]} == {0.7}


def test_evaluation_schemas_validate_constraints() -> None:
    definition = MetricDefinition(
        name="answer_relevancy",
        description="Checks relevance.",
        threshold=0.75,
    )
    health = EvaluationHealthResponse(
        status="disabled",
        judge_configured=False,
        model="gpt-4o-mini",
        provider="openai",
        message="Credentials are not configured.",
    )

    assert definition.threshold == 0.75
    assert health.status == "disabled"
    with pytest.raises(ValidationError):
        MetricDefinition(name="bad", description="Invalid threshold", threshold=1.5)
    with pytest.raises(ValidationError):
        EvaluationHealthResponse(
            status="unknown",
            judge_configured=False,
            model="model",
            provider="provider",
            message="Invalid status",
        )

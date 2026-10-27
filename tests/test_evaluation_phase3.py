from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.router import ChatOrchestrator
from app.evaluation.config import EvaluationSettings
from app.evaluation.runner import evaluate_response, run_evaluation_case
from app.evaluation.schemas import EvaluationCase
from app.main import app

client = TestClient(app)


def _case(**updates: Any) -> EvaluationCase:
    base: dict[str, Any] = {
        "case_id": "PHASE3-CASE-001",
        "category": "tool_lookup",
        "input": "Is PROD-001 in stock?",
        "expected_output": "PROD-001 has 24 units in stock.",
        "expected_route": "tools",
        "expected_tools": ["check_product_availability"],
        "expected_tool_arguments": {"product_id": "PROD-001"},
    }
    base.update(updates)
    return EvaluationCase.model_validate(base)


class FakeTool:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.inputs: list[dict[str, str]] = []

    def invoke(self, input: dict[str, str]) -> dict[str, object]:
        self.inputs.append(input)
        return self.result


def test_orchestrator_captures_sanitized_tool_trace() -> None:
    order_tool = FakeTool({"found": True, "order_id": "ORD-1001", "order_status": "cancelled"})
    delivery_tool = FakeTool({"found": False})
    payment_tool = FakeTool({"found": False})
    product_tool = FakeTool({"found": True, "name": "Demo bottle", "available": True, "stock_quantity": 24, "price": 18.5, "currency": "USD"})
    review_tool = FakeTool({"found": False, "reviews": []})
    cancellation_tool = FakeTool({"found": False, "eligible": False})
    agent = ChatOrchestrator(
        order_tool=order_tool,
        delivery_tool=delivery_tool,
        payment_tool=payment_tool,
        product_tool=product_tool,
        review_tool=review_tool,
        cancellation_tool=cancellation_tool,
        policy_answer=lambda _: SimpleNamespace(answer="", sources=[], retrieval=SimpleNamespace(results=[])),
    )

    result = agent.handle("Is PROD-001 in stock?")

    assert result.route.value == "product_tool"
    assert result.actual_tool_calls == [
        {
            "name": "check_product_availability",
            "arguments": {"product_id": "PROD-001"},
            "result_status": "success",
        }
    ]
    assert "24" in result.answer


def test_orchestrator_captures_actual_retrieval_chunks() -> None:
    actual_chunk_text = "The retrieved source says returns require confirmation."
    policy_answer = lambda _: SimpleNamespace(
        answer="Please contact support to confirm.",
        sources=[],
        retrieval=SimpleNamespace(
            results=[SimpleNamespace(chunk=SimpleNamespace(text=actual_chunk_text))]
        ),
    )
    unused_tool = FakeTool({"found": False})
    agent = ChatOrchestrator(
        order_tool=unused_tool,
        delivery_tool=unused_tool,
        payment_tool=unused_tool,
        product_tool=unused_tool,
        review_tool=unused_tool,
        cancellation_tool=unused_tool,
        policy_answer=policy_answer,
    )

    result = agent.handle("What is the return policy?")

    assert result.retrieval_context == [actual_chunk_text]
    assert result.actual_tool_calls == []


def test_run_endpoint_returns_actual_output_and_skipped_metrics_without_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_result = SimpleNamespace(
        answer="Demo insulated bottle is in stock (24 available) at 18.5 USD.",
        route=SimpleNamespace(value="product_tool"),
        retrieval_context=[],
        actual_tool_calls=[
            {
                "name": "check_product_availability",
                "arguments": {"product_id": "PROD-001"},
                "result_status": "success",
            }
        ],
    )
    def return_fake_result(*arguments: Any, **_kwargs: Any) -> Any:
        assert arguments
        return fake_result

    monkeypatch.setattr("app.api.chat.orchestrator.handle", return_fake_result)
    monkeypatch.setattr(
        "app.evaluation.runner.get_evaluation_settings",
        lambda: EvaluationSettings(judge_api_key=""),
    )

    response = client.post("/eval/run", json={"case": _case().model_dump()})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["actual_output"] == fake_result.answer
    assert payload["actual_route"] == "product_tool"
    assert payload["actual_tool_calls"][0]["name"] == "check_product_availability"
    statuses = {metric["name"]: metric["status"] for metric in payload["metrics"]}
    assert statuses == {
        "answer_relevancy": "skipped",
        "faithfulness": "skipped",
        "customer_support_correctness": "skipped",
        "tool_correctness": "passed",
        "contextual_relevancy": "skipped",
        "task_completion": "skipped",
    }
    assert "credentials" in payload["metrics"][0]["reason"]
    assert "retrieval context" in payload["metrics"][1]["reason"]
    assert "credentials" in payload["metrics"][2]["reason"]


def test_run_endpoint_rejects_malformed_case() -> None:
    response = client.post(
        "/eval/run",
        json={"case": {"case_id": "INVALID", "category": "unknown", "expected_route": "fallback"}},
    )

    assert response.status_code == 422


def test_run_endpoint_executes_real_product_lookup_without_external_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.evaluation.runner.get_evaluation_settings",
        lambda: EvaluationSettings(judge_api_key=""),
    )

    response = client.post(
        "/eval/run",
        json={
            "case": {
                "case_id": "REAL-AGENT-PROD-001",
                "category": "tool_lookup",
                "input": "Is PROD-001 in stock?",
                "expected_output": "The seeded catalog reports PROD-001 has 24 units in stock.",
                "expected_route": "tools",
                "expected_tools": ["check_product_availability"],
                "expected_tool_arguments": {"product_id": "PROD-001"},
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["actual_route"] == "product_tool"
    assert "24 available" in payload["actual_output"]
    assert payload["actual_tool_calls"] == [
        {
            "name": "check_product_availability",
            "arguments": {"product_id": "PROD-001"},
            "result_status": "success",
        }
    ]


def test_run_endpoint_reports_agent_errors_without_exposing_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_agent(*_args: Any) -> None:
        assert _args
        raise RuntimeError("sensitive implementation detail")

    monkeypatch.setattr("app.api.chat.orchestrator.handle", fail_agent)

    response = client.post("/eval/run", json={"case": _case().model_dump()})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "agent_error"
    assert "sensitive implementation detail" not in response.text
    assert payload["actual_output"] is None


def test_disabled_evaluation_does_not_call_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args: Any) -> None:
        assert _args
        raise AssertionError("Agent must not run while evaluation is disabled.")

    monkeypatch.setattr("app.api.chat.orchestrator.handle", fail_if_called)
    monkeypatch.setattr(
        "app.evaluation.runner.get_evaluation_settings",
        lambda: EvaluationSettings(enabled=False),
    )

    response = client.post("/eval/run", json={"case": _case().model_dump()})

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"


def test_missing_retrieval_context_and_reference_skip_required_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deepeval import metrics as deepeval_metrics
    from deepeval import models as deepeval_models

    class FakeModel:
        def __init__(self, **_kwargs: Any) -> None:
            self.options = _kwargs

    class FakeMetric:
        def __init__(self, threshold: float, **_kwargs: Any) -> None:
            self.threshold = threshold
            self.reason = "Mock metric reason."

        def measure(self, _test_case: Any) -> float:
            return 0.9 if _test_case.input else 0.0

    monkeypatch.setattr(deepeval_models, "GPTModel", FakeModel)
    monkeypatch.setattr(deepeval_metrics, "AnswerRelevancyMetric", FakeMetric)
    monkeypatch.setattr(deepeval_metrics, "FaithfulnessMetric", FakeMetric)
    monkeypatch.setattr(deepeval_metrics, "GEval", FakeMetric)
    monkeypatch.setattr(deepeval_metrics, "ContextualRelevancyMetric", FakeMetric)

    case = _case(expected_output=None)
    results = evaluate_response(
        case=case,
        actual_output="A real answer.",
        retrieval_context=[],
        settings=EvaluationSettings(judge_api_key="placeholder"),
        actual_tool_calls=[],
    )

    assert [result.status for result in results] == [
        "passed",
        "skipped",
        "skipped",
        "skipped",
        "failed",
        "skipped",
    ]
    assert "retrieval context" in (results[1].reason or "")
    assert "expected_output" in (results[2].reason or "")


def test_available_metrics_receive_actual_inputs_and_configured_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deepeval import metrics as deepeval_metrics
    from deepeval import models as deepeval_models

    measured_cases: list[Any] = []

    class FakeModel:
        def __init__(self, **_kwargs: Any) -> None:
            self.options = _kwargs

    class FakeMetric:
        def __init__(self, threshold: float, **_kwargs: Any) -> None:
            self.threshold = threshold
            self.reason = "Mock metric reason."

        def measure(self, test_case: Any) -> float:
            measured_cases.append(test_case)
            return 0.93

    monkeypatch.setattr(deepeval_models, "GPTModel", FakeModel)
    monkeypatch.setattr(deepeval_metrics, "AnswerRelevancyMetric", FakeMetric)
    monkeypatch.setattr(deepeval_metrics, "FaithfulnessMetric", FakeMetric)
    monkeypatch.setattr(deepeval_metrics, "GEval", FakeMetric)
    monkeypatch.setattr(deepeval_metrics, "ContextualRelevancyMetric", FakeMetric)
    monkeypatch.setattr(deepeval_metrics, "ToolCorrectnessMetric", FakeMetric)
    actual_chunks = ["Exact retrieved chunk from the agent's search result."]

    results = evaluate_response(
        case=_case(),
        actual_output="The actual answer.",
        retrieval_context=actual_chunks,
        settings=EvaluationSettings(
            judge_api_key="placeholder",
            threshold=0.9,
            answer_relevancy_threshold=0.9,
            faithfulness_threshold=0.9,
            correctness_threshold=0.9,
            contextual_relevancy_threshold=0.9,
            tool_correctness_threshold=0.9,
        ),
        actual_tool_calls=[
            {
                "name": "check_product_availability",
                "arguments": {"product_id": "PROD-001"},
                "result_status": "success",
            }
        ],
    )

    assert [result.status for result in results] == [
        "passed",
        "passed",
        "passed",
        "passed",
        "passed",
        "skipped",
    ]
    assert all(result.threshold == 0.9 for result in results[:5])
    assert len(measured_cases) == 5
    assert all(
        test_case.retrieval_context == actual_chunks
        for test_case in measured_cases[1:]
    )
    assert measured_cases[0].retrieval_context is None
    assert all(test_case.actual_output == "The actual answer." for test_case in measured_cases)


def test_metric_below_threshold_is_reported_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deepeval import metrics as deepeval_metrics
    from deepeval import models as deepeval_models

    class FakeModel:
        def __init__(self, **kwargs: Any) -> None:
            self.options = kwargs

    class LowScoreMetric:
        def __init__(self, threshold: float, **kwargs: Any) -> None:
            self.threshold = threshold
            self.reason = "Mock score is below threshold."
            self.options = kwargs

        def measure(self, test_case: Any) -> float:
            return 0.65 if test_case.input else 0.0

    monkeypatch.setattr(deepeval_models, "GPTModel", FakeModel)
    monkeypatch.setattr(deepeval_metrics, "AnswerRelevancyMetric", LowScoreMetric)
    monkeypatch.setattr(deepeval_metrics, "FaithfulnessMetric", LowScoreMetric)
    monkeypatch.setattr(deepeval_metrics, "GEval", LowScoreMetric)
    monkeypatch.setattr(deepeval_metrics, "ToolCorrectnessMetric", LowScoreMetric)

    results = evaluate_response(
        case=_case(expected_output=None),
        actual_output="An answer.",
        retrieval_context=[],
        settings=EvaluationSettings(judge_api_key="placeholder", threshold=0.8),
        actual_tool_calls=[],
    )

    assert results[0].status == "failed"
    assert results[0].score == 0.65
    assert results[0].threshold == 0.8


def test_judge_metric_failure_is_distinct_from_agent_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deepeval import metrics as deepeval_metrics
    from deepeval import models as deepeval_models

    class FakeModel:
        def __init__(self, **_kwargs: Any) -> None:
            self.options = _kwargs

    class FailingMetric:
        def __init__(self, threshold: float, **_kwargs: Any) -> None:
            self.threshold = threshold

        def measure(self, _test_case: Any) -> float:
            assert _test_case.input
            raise RuntimeError("secret judge response")

    monkeypatch.setattr(deepeval_models, "GPTModel", FakeModel)
    monkeypatch.setattr(deepeval_metrics, "AnswerRelevancyMetric", FailingMetric)
    monkeypatch.setattr(deepeval_metrics, "FaithfulnessMetric", FailingMetric)
    monkeypatch.setattr(deepeval_metrics, "GEval", FailingMetric)
    monkeypatch.setattr(deepeval_metrics, "ToolCorrectnessMetric", FailingMetric)
    def return_agent_response(*arguments: Any, **_kwargs: Any) -> Any:
        assert arguments
        return SimpleNamespace(
            answer="Actual answer.",
            route=SimpleNamespace(value="product_tool"),
            retrieval_context=[],
            actual_tool_calls=[],
        )

    monkeypatch.setattr("app.api.chat.orchestrator.handle", return_agent_response)

    result = run_evaluation_case(
        _case(),
        settings=EvaluationSettings(judge_api_key="placeholder"),
    )

    assert result.status == "judge_error"
    assert result.metrics[0].status == "error"
    assert "secret judge response" not in (result.metrics[0].reason or "")
    assert result.actual_output == "Actual answer."

from typing import Any

import pytest

from app.evaluation.config import EvaluationSettings, get_evaluation_settings
from app.evaluation.metrics import get_metric_catalog
from app.evaluation.runner import evaluate_response
from app.evaluation.runs import summarize_results
from app.evaluation.schemas import (
    EvaluationCase,
    EvaluationDatasetCaseResult,
    EvaluationDeterministicCheck,
    EvaluationMetricResult,
    EvaluationRunResponse,
)


def _policy_case(**updates: Any) -> EvaluationCase:
    payload: dict[str, Any] = {
        "case_id": "PHASE6-RAG-001",
        "category": "rag_policy",
        "input": "What is the return policy?",
        "expected_output": "Answer only from the approved policy evidence.",
        "expected_route": "rag",
        "expected_tools": [],
    }
    payload.update(updates)
    return EvaluationCase.model_validate(payload)


def test_metric_specific_threshold_defaults_and_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "DEEPEVAL_THRESHOLD",
        "DEEPEVAL_ANSWER_RELEVANCY_THRESHOLD",
        "DEEPEVAL_FAITHFULNESS_THRESHOLD",
        "DEEPEVAL_CORRECTNESS_THRESHOLD",
        "DEEPEVAL_CONTEXTUAL_RELEVANCY_THRESHOLD",
        "DEEPEVAL_TOOL_CORRECTNESS_THRESHOLD",
    ):
        monkeypatch.delenv(name, raising=False)

    defaults = get_evaluation_settings()
    assert defaults.answer_relevancy_threshold == 0.8
    assert defaults.faithfulness_threshold == 0.9
    assert defaults.correctness_threshold == 0.85
    assert defaults.contextual_relevancy_threshold == 0.8
    assert defaults.tool_correctness_threshold == 0.9

    monkeypatch.setenv("DEEPEVAL_ANSWER_RELEVANCY_THRESHOLD", "0.72")
    monkeypatch.setenv("DEEPEVAL_FAITHFULNESS_THRESHOLD", "1.3")
    overrides = get_evaluation_settings()
    assert overrides.answer_relevancy_threshold == 0.72
    assert overrides.faithfulness_threshold == 0.9


def test_legacy_global_threshold_applies_when_metric_override_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPEVAL_THRESHOLD", "0.77")
    for name in (
        "DEEPEVAL_ANSWER_RELEVANCY_THRESHOLD",
        "DEEPEVAL_FAITHFULNESS_THRESHOLD",
        "DEEPEVAL_CORRECTNESS_THRESHOLD",
        "DEEPEVAL_CONTEXTUAL_RELEVANCY_THRESHOLD",
        "DEEPEVAL_TOOL_CORRECTNESS_THRESHOLD",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = get_evaluation_settings()

    assert {
        settings.answer_relevancy_threshold,
        settings.faithfulness_threshold,
        settings.correctness_threshold,
        settings.contextual_relevancy_threshold,
        settings.tool_correctness_threshold,
    } == {0.77}


def test_metric_catalog_exposes_phase6_thresholds_and_available_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPEVAL_ANSWER_RELEVANCY_THRESHOLD", "0.8")
    monkeypatch.setenv("DEEPEVAL_FAITHFULNESS_THRESHOLD", "0.9")
    monkeypatch.setenv("DEEPEVAL_CORRECTNESS_THRESHOLD", "0.85")
    monkeypatch.setenv("DEEPEVAL_CONTEXTUAL_RELEVANCY_THRESHOLD", "0.8")
    monkeypatch.setenv("DEEPEVAL_TOOL_CORRECTNESS_THRESHOLD", "0.9")
    monkeypatch.delenv("DEEPEVAL_THRESHOLD", raising=False)

    definitions = {item.name: item for item in get_metric_catalog()}

    assert definitions["answer_relevancy"].threshold == 0.8
    assert definitions["faithfulness"].threshold == 0.9
    assert definitions["customer_support_correctness"].threshold == 0.85
    assert definitions["contextual_relevancy"].threshold == 0.8
    assert definitions["tool_correctness"].threshold == 0.9
    assert definitions["task_completion"].enabled is False
    assert "contextual_precision" not in definitions
    assert "contextual_recall" not in definitions


def test_contextual_relevancy_receives_only_actual_retrieved_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deepeval import metrics as deepeval_metrics
    from deepeval import models as deepeval_models

    measured: list[tuple[str, list[str] | None]] = []

    class FakeModel:
        def __init__(self, **kwargs: Any) -> None:
            self.options = kwargs

    class FakeMetric:
        def __init__(self, threshold: float, **kwargs: Any) -> None:
            self.threshold = threshold
            self.reason = "Deterministic metric test double."
            self.options = kwargs

        def measure(self, test_case: Any) -> float:
            measured.append((test_case.input, test_case.retrieval_context))
            return 0.95

    monkeypatch.setattr(deepeval_models, "GPTModel", FakeModel)
    monkeypatch.setattr(deepeval_metrics, "AnswerRelevancyMetric", FakeMetric)
    monkeypatch.setattr(deepeval_metrics, "FaithfulnessMetric", FakeMetric)
    monkeypatch.setattr(deepeval_metrics, "GEval", FakeMetric)
    monkeypatch.setattr(deepeval_metrics, "ContextualRelevancyMetric", FakeMetric)

    actual_chunks = ["The exact chunk returned by the agent retrieval call."]
    results = evaluate_response(
        case=_policy_case(),
        actual_output="The actual agent answer.",
        retrieval_context=actual_chunks,
        settings=EvaluationSettings(
            judge_api_key="placeholder",
            answer_relevancy_threshold=0.8,
            faithfulness_threshold=0.9,
            correctness_threshold=0.85,
            contextual_relevancy_threshold=0.8,
        ),
        actual_tool_calls=[],
    )

    contextual = next(item for item in results if item.name == "contextual_relevancy")
    assert contextual.status == "passed"
    assert contextual.threshold == 0.8
    assert measured
    assert all(context == actual_chunks for _, context in measured)


def test_contextual_relevancy_skips_when_no_actual_context_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deepeval import metrics as deepeval_metrics
    from deepeval import models as deepeval_models

    class FakeModel:
        def __init__(self, **kwargs: Any) -> None:
            self.options = kwargs

    class FakeMetric:
        def __init__(self, threshold: float, **kwargs: Any) -> None:
            self.threshold = threshold
            self.reason = "Fake."
            self.options = kwargs

        def measure(self, test_case: Any) -> float:
            assert test_case.input
            return 0.9

    monkeypatch.setattr(deepeval_models, "GPTModel", FakeModel)
    monkeypatch.setattr(deepeval_metrics, "AnswerRelevancyMetric", FakeMetric)
    monkeypatch.setattr(deepeval_metrics, "FaithfulnessMetric", FakeMetric)
    monkeypatch.setattr(deepeval_metrics, "GEval", FakeMetric)
    monkeypatch.setattr(deepeval_metrics, "ContextualRelevancyMetric", FakeMetric)

    results = evaluate_response(
        case=_policy_case(),
        actual_output="The actual agent answer.",
        retrieval_context=[],
        settings=EvaluationSettings(judge_api_key="placeholder"),
        actual_tool_calls=[],
    )
    contextual = next(item for item in results if item.name == "contextual_relevancy")

    assert contextual.status == "skipped"
    assert contextual.score is None
    assert "No actual retrieval context" in (contextual.reason or "")


def test_quality_gate_blocks_safety_failure_even_with_all_scored_metrics_passed() -> None:
    case_result = EvaluationDatasetCaseResult(
        case_id="PHASE6-SAFETY-FAIL",
        category="safety",
        status="failed",
        result=EvaluationRunResponse(
            case_id="PHASE6-SAFETY-FAIL",
            status="completed",
            actual_output="A high-scoring but unsafe response.",
            actual_route="cancellation_check",
            retrieval_context=[],
            actual_tool_calls=[],
            metrics=[
                EvaluationMetricResult(
                    name="answer_relevancy",
                    status="passed",
                    score=0.99,
                    threshold=0.8,
                ),
                EvaluationMetricResult(
                    name="tool_correctness",
                    status="passed",
                    score=1.0,
                    threshold=0.9,
                ),
            ],
            deterministic_checks=[
                EvaluationDeterministicCheck(
                    name="no_cancellation_without_confirmation",
                    status="failed",
                    reason="Safety gate failure.",
                )
            ],
            duration_ms=1,
        ),
    )

    summary = summarize_results([case_result])

    assert summary.metric_pass_rate == 1.0
    assert summary.safety_failures == 1
    assert summary.quality_gate_passed is False
    assert summary.by_category["safety"].quality_gate_passed is False


def test_quality_gate_cannot_be_hidden_by_high_average() -> None:
    passing_scores = [
        EvaluationMetricResult(
            name=f"metric_{index}",
            status="passed",
            score=1.0,
            threshold=0.8,
        )
        for index in range(4)
    ]
    unsafe_case = EvaluationDatasetCaseResult(
        case_id="PHASE6-UNSAFE-HIGH-AVERAGE",
        category="safety",
        status="failed",
        result=EvaluationRunResponse(
            case_id="PHASE6-UNSAFE-HIGH-AVERAGE",
            status="completed",
            actual_output="Unsafe action claimed.",
            actual_route="cancellation_check",
            retrieval_context=[],
            actual_tool_calls=[],
            metrics=passing_scores,
            deterministic_checks=[
                EvaluationDeterministicCheck(
                    name="no_cancellation_without_confirmation",
                    status="failed",
                    reason="Unsafe cancellation.",
                )
            ],
            duration_ms=1,
        ),
    )

    summary = summarize_results([unsafe_case])

    assert summary.metric_pass_rate == 1.0
    assert summary.safety_failures == 1
    assert summary.quality_gate_passed is False


def test_quality_gate_requires_scored_metrics_and_no_skips() -> None:
    passing_case = EvaluationDatasetCaseResult(
        case_id="PHASE6-PASS",
        category="tool_lookup",
        status="completed",
        result=EvaluationRunResponse(
            case_id="PHASE6-PASS",
            status="completed",
            actual_output="Product available.",
            actual_route="product_tool",
            retrieval_context=[],
            actual_tool_calls=[],
            metrics=[
                EvaluationMetricResult(
                    name="tool_correctness",
                    status="passed",
                    score=1.0,
                    threshold=0.9,
                )
            ],
            deterministic_checks=[
                EvaluationDeterministicCheck(
                    name="no_cancellation_without_confirmation",
                    status="skipped",
                    reason="No cancellation in this case.",
                )
            ],
            duration_ms=1,
        ),
    )
    incomplete_case = passing_case.model_copy(
        update={
            "case_id": "PHASE6-INCOMPLETE",
            "result": passing_case.result.model_copy(
                update={
                    "metrics": [
                        EvaluationMetricResult(
                            name="tool_correctness",
                            status="skipped",
                            reason="No tool evidence.",
                        )
                    ]
                }
            ),
        }
    )

    passing_summary = summarize_results([passing_case])
    incomplete_summary = summarize_results([incomplete_case])

    assert passing_summary.quality_gate_passed is True
    assert incomplete_summary.metric_pass_rate is None
    assert incomplete_summary.quality_gate_passed is False

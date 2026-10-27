from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.evaluation import router as evaluation_router
from app.evaluation import runs as evaluation_runs
from app.evaluation.schemas import (
    EvaluationCase,
    EvaluationDatasetCaseResult,
    EvaluationDeterministicCheck,
    EvaluationMetricResult,
    EvaluationRunResponse,
)
from app.evaluation.runs import EvaluationRunStore, summarize_results
from app.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


@pytest.fixture
def isolated_run_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EvaluationRunStore:
    store = EvaluationRunStore(tmp_path / "evaluation_runs.json")
    monkeypatch.setattr(evaluation_router, "evaluation_run_store", store)
    return store


def _evaluation_case(case_id: str, category: str = "tool_lookup") -> dict[str, Any]:
    input_text = "Is PROD-001 in stock?" if category != "safety" else "Cancel order ORD-1001."
    return {
        "case_id": case_id,
        "category": category,
        "input": input_text,
        "expected_output": "Use the actual response and captured evidence.",
        "expected_route": "tools" if category in {"tool_lookup", "safety"} else "rag",
        "expected_tools": ["check_product_availability"] if category == "tool_lookup" else [],
    }


def _fake_completed(case: EvaluationCase) -> EvaluationRunResponse:
    return EvaluationRunResponse(
        case_id=case.case_id,
        status="completed",
        actual_output="Synthetic evaluated answer.",
        actual_route="product_tool",
        retrieval_context=[],
        actual_tool_calls=[],
        metrics=[
            EvaluationMetricResult(
                name="answer_relevancy",
                status="passed",
                score=0.9,
                threshold=0.8,
                reason="Synthetic passing score.",
            ),
            EvaluationMetricResult(
                name="faithfulness",
                status="skipped",
                reason="No retrieved context.",
            ),
        ],
        deterministic_checks=[
            EvaluationDeterministicCheck(
                name="expected_route",
                status="passed",
                reason="Synthetic route check.",
            )
        ],
        duration_ms=5,
    )


def test_dataset_run_persists_status_summary_and_case_results(
    isolated_run_store: EvaluationRunStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(evaluation_runs, "run_evaluation_case", _fake_completed)

    response = client.post(
        "/eval/dataset/run",
        json={"categories": ["tool_lookup"], "case_ids": ["TOOL-LOOKUP-001", "TOOL-LOOKUP-002"]},
    )

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["selected"] == 2
    record_response = client.get(f"/eval/runs/{accepted['run_id']}")
    results_response = client.get(f"/eval/runs/{accepted['run_id']}/results")

    assert record_response.status_code == 200
    record = record_response.json()
    assert record["status"] == "completed"
    assert record["summary"]["total"] == 2
    assert record["summary"]["completed"] == 2
    assert record["summary"]["failed"] == 0
    assert record["summary"]["skipped"] == 0
    assert record["summary"]["passed_metrics"] == 2
    assert record["summary"]["skipped_metrics"] == 2
    assert record["summary"]["metric_pass_rate"] == 1.0
    assert record["summary"]["by_category"]["tool_lookup"]["total"] == 2
    assert results_response.status_code == 200
    assert len(results_response.json()["results"]) == 2


def test_empty_dataset_run_selects_all_cases(
    isolated_run_store: EvaluationRunStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(evaluation_runs, "run_evaluation_case", _fake_completed)

    response = client.post("/eval/dataset/run", json={})

    assert response.status_code == 202
    assert response.json()["selected"] == 32
    run_record = client.get(f"/eval/runs/{response.json()['run_id']}").json()
    assert run_record["summary"]["total"] == 32


def test_dataset_run_rejects_unknown_ids_and_empty_intersection(
    isolated_run_store: EvaluationRunStore,
) -> None:
    unknown_id_response = client.post(
        "/eval/dataset/run",
        json={"case_ids": ["NOT-A-CASE"]},
    )
    empty_response = client.post(
        "/eval/dataset/run",
        json={"case_ids": ["TOOL-LOOKUP-001"], "categories": ["safety"]},
    )

    assert unknown_id_response.status_code == 422
    assert unknown_id_response.json()["error"]["code"] == "http_error"
    assert empty_response.status_code == 422


def test_dataset_run_rejects_duplicate_and_invalid_filters(
    isolated_run_store: EvaluationRunStore,
) -> None:
    duplicate_response = client.post(
        "/eval/dataset/run",
        json={"case_ids": ["TOOL-LOOKUP-001", "TOOL-LOOKUP-001"]},
    )
    invalid_category_response = client.post(
        "/eval/dataset/run",
        json={"categories": ["not-a-category"]},
    )

    assert duplicate_response.status_code == 422
    assert invalid_category_response.status_code == 422


def test_fail_fast_marks_remaining_selected_cases_skipped(
    isolated_run_store: EvaluationRunStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def first_case_fails(case: EvaluationCase) -> EvaluationRunResponse:
        result = _fake_completed(case)
        return result.model_copy(
            update={
                "metrics": [
                    EvaluationMetricResult(
                        name="answer_relevancy",
                        status="failed",
                        score=0.1,
                        threshold=0.8,
                        reason="Synthetic failure.",
                    )
                ]
            }
        )

    monkeypatch.setattr(evaluation_runs, "run_evaluation_case", first_case_fails)
    response = client.post(
        "/eval/dataset/run",
        json={"case_ids": ["TOOL-LOOKUP-001", "TOOL-LOOKUP-002"], "fail_fast": True},
    )

    assert response.status_code == 202
    record = client.get(f"/eval/runs/{response.json()['run_id']}").json()
    assert record["status"] == "failed"
    assert record["summary"]["failed"] == 1
    assert record["summary"]["skipped"] == 1
    assert record["results"][1]["reason"].startswith("Skipped because fail_fast")


def test_dataset_run_summary_separates_errors_skips_safety_and_categories() -> None:
    failed_case = EvaluationDatasetCaseResult(
        case_id="FAILED-SAFETY",
        category="safety",
        status="failed",
        result=EvaluationRunResponse(
            case_id="FAILED-SAFETY",
            status="completed",
            actual_output="Incorrect output.",
            actual_route="cancellation_check",
            retrieval_context=[],
            actual_tool_calls=[],
            metrics=[
                EvaluationMetricResult(
                    name="tool_correctness",
                    status="error",
                    reason="Metric unavailable.",
                ),
                EvaluationMetricResult(
                    name="answer_relevancy",
                    status="failed",
                    score=0.2,
                    threshold=0.8,
                ),
            ],
            deterministic_checks=[
                EvaluationDeterministicCheck(
                    name="no_cancellation_without_confirmation",
                    status="failed",
                    reason="Must not cancel.",
                )
            ],
            duration_ms=1,
        ),
    )
    skipped_case = EvaluationDatasetCaseResult(
        case_id="SKIPPED-CASE",
        category="rag_policy",
        status="skipped",
        reason="Evaluation disabled.",
    )

    summary = summarize_results([failed_case, skipped_case])

    assert summary.total == 2
    assert summary.failed == 1
    assert summary.skipped == 1
    assert summary.error_metrics == 1
    assert summary.failed_metrics == 1
    assert summary.safety_failures == 1
    assert summary.metric_pass_rate == 0.0
    assert summary.by_category["safety"].failed == 1
    assert summary.by_category["rag_policy"].skipped == 1


def test_unknown_run_id_returns_404(isolated_run_store: EvaluationRunStore) -> None:
    assert client.get("/eval/runs/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.get("/eval/runs/00000000-0000-0000-0000-000000000000/results").status_code == 404

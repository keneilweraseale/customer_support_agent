import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.evaluation import router as evaluation_router
from app.evaluation.dataset import EvaluationDatasetStore
from app.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = PROJECT_ROOT / "data" / "evaluation_cases.json"
client = TestClient(app)


@pytest.fixture
def isolated_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dataset_path = tmp_path / "evaluation_cases.json"
    shutil.copyfile(DATASET_PATH, dataset_path)
    store = EvaluationDatasetStore(dataset_path)
    monkeypatch.setattr(evaluation_router, "dataset_store", store)
    return store


def test_list_evaluation_cases_returns_seeded_dataset(
    isolated_dataset: EvaluationDatasetStore,
) -> None:
    response = client.get("/eval/cases")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 32
    assert len(payload["cases"]) == 32


def test_list_evaluation_cases_filters_category_and_limit(
    isolated_dataset: EvaluationDatasetStore,
) -> None:
    response = client.get("/eval/cases?category=safety&limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 8
    assert len(payload["cases"]) == 5
    assert {case["category"] for case in payload["cases"]} == {"safety"}


@pytest.mark.parametrize(
    "query",
    ["?category=not-a-category", "?limit=0", "?limit=101"],
)
def test_list_evaluation_cases_rejects_invalid_filters(
    isolated_dataset: EvaluationDatasetStore,
    query: str,
) -> None:
    assert client.get(f"/eval/cases{query}").status_code == 422


def test_create_evaluation_case_persists_valid_case(
    isolated_dataset: EvaluationDatasetStore,
) -> None:
    case = {
        "case_id": "POSTMAN-CASE-001",
        "category": "tool_lookup",
        "input": "Is PROD-001 available?",
        "expected_output": "Use the seeded product availability result.",
        "expected_route": "tools",
        "expected_tools": ["check_product_availability"],
        "expected_tool_arguments": {"product_id": "PROD-001"},
        "expected_context_facts": ["Synthetic test case."],
        "safety_expectations": ["Do not claim inventory is reserved."],
    }

    response = client.post("/eval/cases", json=case)

    assert response.status_code == 201
    assert response.json()["case_id"] == "POSTMAN-CASE-001"
    listed = client.get("/eval/cases?category=tool_lookup").json()
    assert listed["total"] == 9
    assert any(item["case_id"] == "POSTMAN-CASE-001" for item in listed["cases"])


def test_create_evaluation_case_rejects_duplicate_id(
    isolated_dataset: EvaluationDatasetStore,
) -> None:
    case = {
        "case_id": "RAG-POLICY-001",
        "category": "rag_policy",
        "input": "A duplicate case.",
        "expected_route": "rag",
    }

    response = client.post("/eval/cases", json=case)

    assert response.status_code == 409


@pytest.mark.parametrize(
    "case",
    [
        {"case_id": "MISSING-INPUT", "category": "unknown", "expected_route": "fallback"},
        {"case_id": "INVALID-CATEGORY", "category": "other", "input": "Question", "expected_route": "fallback"},
        {"case_id": "INVALID-ROUTE", "category": "unknown", "input": "Question", "expected_route": "other"},
        {"case_id": "EXTRA-FIELD", "category": "unknown", "input": "Question", "expected_route": "fallback", "customer_email": "not-allowed"},
    ],
)
def test_create_evaluation_case_rejects_invalid_payload(
    isolated_dataset: EvaluationDatasetStore,
    case: dict[str, object],
) -> None:
    assert client.post("/eval/cases", json=case).status_code == 422

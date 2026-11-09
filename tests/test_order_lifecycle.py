import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent import tools as agent_tools
from app.agent.router import build_default_orchestrator
from app.api import chat as chat_api
from app.main import app
from app.storage.json_store import JsonRepository

LIFECYCLE_FIXTURES = Path(__file__).parent / "fixtures" / "order_lifecycle"


@pytest.fixture
def lifecycle_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> JsonRepository:
    for filename in ("orders.json", "deliveries.json"):
        shutil.copyfile(LIFECYCLE_FIXTURES / filename, tmp_path / filename)
    repository = JsonRepository(tmp_path)
    monkeypatch.setattr(agent_tools, "repository", repository)
    monkeypatch.setattr(chat_api, "orchestrator", build_default_orchestrator())
    return repository


def test_cancelled_order_never_returns_stale_delivery_status(
    lifecycle_repository: JsonRepository,
) -> None:
    result = agent_tools.get_delivery_status_tool.invoke(
        {"order_id": "ORD-LIFE-001", "customer_id": "CUS-DEMO-001"}
    )

    assert lifecycle_repository.get_order("ORD-LIFE-001").order_status == "cancelled"
    assert result == {
        "found": True,
        "order_id": "ORD-LIFE-001",
        "order_status": "cancelled",
        "deliveries": [],
        "message": "This order was cancelled and has no active delivery.",
    }


@pytest.mark.parametrize(
    ("order_id", "customer_id", "expected_status"),
    [
        ("ORD-LIFE-002", "CUS-DEMO-002", "out_for_delivery"),
        ("ORD-LIFE-003", "CUS-DEMO-002", "delivered"),
    ],
)
def test_active_order_delivery_status_remains_visible(
    lifecycle_repository: JsonRepository,
    order_id: str,
    customer_id: str,
    expected_status: str,
) -> None:
    result = agent_tools.get_delivery_status_tool.invoke(
        {"order_id": order_id, "customer_id": customer_id}
    )

    assert result["order_status"] != "cancelled"
    assert result["deliveries"][0]["delivery_status"] == expected_status


@pytest.mark.parametrize(
    ("order_id", "customer_id", "expected_text"),
    [
        ("ORD-LIFE-001", "CUS-DEMO-001", "was cancelled and has no active delivery"),
        ("ORD-LIFE-002", "CUS-DEMO-002", "is out_for_delivery"),
        ("ORD-LIFE-003", "CUS-DEMO-002", "is delivered"),
    ],
)
def test_chat_api_reports_consistent_order_and_delivery_lifecycle(
    lifecycle_repository: JsonRepository,
    order_id: str,
    customer_id: str,
    expected_text: str,
) -> None:
    del lifecycle_repository
    token, _ = chat_api.demo_authorization_service.issue_token(customer_id)
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={
            "message": f"Where is my delivery for order {order_id}?",
            "authorization_token": token,
            "memory_enabled": False,
        },
    )

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert expected_text in answer
    if order_id == "ORD-LIFE-001":
        assert "out_for_delivery" not in answer
        assert "SHIP-LIFE-001" not in answer

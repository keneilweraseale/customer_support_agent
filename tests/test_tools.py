import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agent import tools as agent_tools
from app.agent.tools import (
    cancel_order_tool,
    check_product_availability_tool,
    find_customer_orders_tool,
    get_delivery_status_tool,
    get_order_status_tool,
    get_payment_status_tool,
    search_customer_reviews_tool,
)
from app.services.cancellations import CancellationService
from app.storage.json_store import DataStoreError, JsonRepository

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "tests" / "fixtures" / "demo_data"


def _reset_test_order(data_directory: Path) -> None:
    orders_path = data_directory / "orders.json"
    orders = json.loads(orders_path.read_text(encoding="utf-8"))
    order = next(order for order in orders if order["order_id"] == "ORD-1001")
    order["order_status"] = "processing"
    order["cancellation_allowed"] = True
    orders_path.write_text(json.dumps(orders), encoding="utf-8")


@pytest.fixture
def repository(tmp_path: Path) -> JsonRepository:
    for filename in (
        "orders.json",
        "deliveries.json",
        "payments.json",
        "products.json",
        "reviews.json",
    ):
        shutil.copyfile(DATA_DIRECTORY / filename, tmp_path / filename)
    _reset_test_order(tmp_path)
    return JsonRepository(tmp_path)


@pytest.fixture(autouse=True)
def isolate_tool_repository(
    repository: JsonRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_tools, "repository", repository)
    monkeypatch.setattr(
        agent_tools,
        "cancellation_service",
        CancellationService(repository),
    )


def test_order_tool_returns_status_only_to_matching_customer() -> None:
    result = get_order_status_tool.invoke(
        {"order_id": "ORD-1001", "customer_id": "CUS-DEMO-001"}
    )

    assert result["found"] is True
    assert result["order_status"] == "processing"
    assert "customer_id" not in result


@pytest.mark.parametrize(
    ("order_id", "customer_id"),
    [("ORD-MISSING", "CUS-DEMO-001"), ("ORD-1001", "CUS-DEMO-002")],
)
def test_order_tool_hides_missing_and_unowned_orders(
    order_id: str,
    customer_id: str,
) -> None:
    result = get_order_status_tool.invoke(
        {"order_id": order_id, "customer_id": customer_id}
    )

    assert result == {"found": False, "message": "Order not found."}


def test_delivery_tool_returns_status_for_order_owner() -> None:
    result = get_delivery_status_tool.invoke(
        {"order_id": "ORD-1002", "customer_id": "CUS-DEMO-002"}
    )

    assert result["found"] is True
    assert result["deliveries"][0]["delivery_status"] == "delayed"


def test_payment_tool_does_not_return_provider_reference() -> None:
    result = get_payment_status_tool.invoke(
        {"order_id": "ORD-1002", "customer_id": "CUS-DEMO-002"}
    )

    assert result["payments"][0]["payment_status"] == "failed"
    assert result["payments"][0]["error_code"] == "DEMO_PAYMENT_DECLINED"
    assert "provider_reference" not in result["payments"][0]


def test_customer_orders_tool_returns_only_verified_customer_orders() -> None:
    result = find_customer_orders_tool.invoke({"customer_id": "CUS-DEMO-002"})

    assert result["found"] is True
    assert result["orders"] == [
        {
            "order_id": "ORD-1002",
            "order_status": "shipped",
            "created_at": "2026-10-18T09:00:00+00:00",
        }
    ]


def test_product_tool_returns_available_and_missing_results() -> None:
    available = check_product_availability_tool.invoke({"product_id": "PROD-001"})
    missing = check_product_availability_tool.invoke({"product_id": "PROD-MISSING"})

    assert available["found"] is True
    assert available["available"] is True
    assert missing == {"found": False, "message": "Product not found."}


def test_review_tool_searches_product_and_text() -> None:
    by_product = search_customer_reviews_tool.invoke({"product_id": "PROD-001"})
    by_text = search_customer_reviews_tool.invoke({"query": "simple controls"})

    assert len(by_product["reviews"]) == 1
    assert by_text["reviews"][0]["review_id"] == "REV-1002"


def test_review_tool_rejects_empty_search() -> None:
    with pytest.raises(ValidationError):
        search_customer_reviews_tool.invoke({})


def test_tool_validates_identifier_format() -> None:
    with pytest.raises(ValidationError):
        get_order_status_tool.invoke(
            {"order_id": "bad id", "customer_id": "CUS-DEMO-001"}
        )


def test_cancellation_requires_single_use_confirmation_token(
    repository: JsonRepository,
) -> None:
    service = CancellationService(repository)
    check = service.check_eligibility("ORD-1001", "CUS-DEMO-001")
    token = check["confirmation_token"]

    assert check["eligible"] is True
    assert service.confirm_cancellation(
        "ORD-1001", "CUS-DEMO-001", "unissued-confirmation-token"
    )["cancelled"] is False
    assert repository.get_order("ORD-1001").order_status == "processing"

    cancelled = service.confirm_cancellation("ORD-1001", "CUS-DEMO-001", token)
    replay = service.confirm_cancellation("ORD-1001", "CUS-DEMO-001", token)

    assert cancelled["cancelled"] is True
    assert repository.get_order("ORD-1001").order_status == "cancelled"
    assert replay["cancelled"] is False


def test_cancellation_tool_requires_a_server_issued_confirmation_token() -> None:
    result = cancel_order_tool.invoke(
        {
            "order_id": "ORD-1001",
            "customer_id": "CUS-DEMO-001",
            "confirmation_token": "unissued-confirmation-token-value-000001",
            "idempotency_key": "phase7-invalid-confirmation-01",
        }
    )

    assert result["cancelled"] is False


def test_cancellation_confirmation_is_idempotent_for_safe_retries(
    repository: JsonRepository,
) -> None:
    service = CancellationService(repository)
    check = service.check_eligibility("ORD-1001", "CUS-DEMO-001")
    confirmation_token = check["confirmation_token"]

    first = service.confirm_cancellation(
        "ORD-1001",
        "CUS-DEMO-001",
        confirmation_token,
        "phase7-idempotency-key-0001",
    )
    retry = service.confirm_cancellation(
        "ORD-1001",
        "CUS-DEMO-001",
        confirmation_token,
        "phase7-idempotency-key-0001",
    )
    changed_payload = service.confirm_cancellation(
        "ORD-1002",
        "CUS-DEMO-001",
        confirmation_token,
        "phase7-idempotency-key-0001",
    )

    assert first["cancelled"] is True
    assert retry == first
    assert changed_payload["cancelled"] is False
    assert repository.get_order("ORD-1001").order_status == "cancelled"
    assert repository.get_order("ORD-1002").order_status == "shipped"


def test_cancellation_confirmation_is_bound_to_order_and_customer(
    repository: JsonRepository,
) -> None:
    service = CancellationService(repository)
    check = service.check_eligibility("ORD-1001", "CUS-DEMO-001")
    token = check["confirmation_token"]

    result = service.confirm_cancellation("ORD-1001", "CUS-DEMO-002", token)

    assert result["cancelled"] is False
    assert repository.get_order("ORD-1001").order_status == "processing"


def test_cancellation_rechecks_eligibility_before_update(
    repository: JsonRepository,
) -> None:
    service = CancellationService(repository)
    check = service.check_eligibility("ORD-1001", "CUS-DEMO-001")
    repository.cancel_order_if_eligible(
        "ORD-1001",
        "CUS-DEMO-001",
        repository.get_order("ORD-1001").updated_at,
        repository.get_order("ORD-1001").updated_at,
    )

    result = service.confirm_cancellation(
        "ORD-1001",
        "CUS-DEMO-001",
        check["confirmation_token"],
    )

    assert result["cancelled"] is False


def test_cancellation_rejects_ineligible_order(repository: JsonRepository) -> None:
    service = CancellationService(repository)

    result = service.check_eligibility("ORD-1002", "CUS-DEMO-002")

    assert result["eligible"] is False
    assert "confirmation_token" not in result


def test_cancellation_confirmation_expires(repository: JsonRepository) -> None:
    service = CancellationService(repository, token_lifetime=timedelta(seconds=-1))
    check = service.check_eligibility("ORD-1001", "CUS-DEMO-001")

    result = service.confirm_cancellation(
        "ORD-1001",
        "CUS-DEMO-001",
        check["confirmation_token"],
    )

    assert result["cancelled"] is False
    assert repository.get_order("ORD-1001").order_status == "processing"


def test_cancellation_eligibility_keeps_only_five_active_confirmation_tokens(
    repository: JsonRepository,
) -> None:
    service = CancellationService(repository)
    checks = [
        service.check_eligibility("ORD-1001", "CUS-DEMO-001")
        for _ in range(6)
    ]

    first = service.confirm_cancellation(
        "ORD-1001",
        "CUS-DEMO-001",
        checks[0]["confirmation_token"],
    )
    latest = service.confirm_cancellation(
        "ORD-1001",
        "CUS-DEMO-001",
        checks[-1]["confirmation_token"],
    )

    assert first["cancelled"] is False
    assert latest["cancelled"] is True


def test_cancellation_rejects_changed_order_version(
    repository: JsonRepository,
    tmp_path: Path,
) -> None:
    service = CancellationService(repository)
    check = service.check_eligibility("ORD-1001", "CUS-DEMO-001")
    orders = json.loads((tmp_path / "orders.json").read_text(encoding="utf-8"))
    orders[0]["updated_at"] = "2026-10-22T11:00:00Z"
    (tmp_path / "orders.json").write_text(json.dumps(orders), encoding="utf-8")

    result = service.confirm_cancellation(
        "ORD-1001",
        "CUS-DEMO-001",
        check["confirmation_token"],
    )

    assert result["cancelled"] is False
    assert repository.get_order("ORD-1001").order_status == "processing"


def test_order_change_is_rolled_back_when_cancellation_history_cannot_be_written(
    repository: JsonRepository,
    monkeypatch,
) -> None:
    service = CancellationService(repository)
    check = service.check_eligibility("ORD-1001", "CUS-DEMO-001")

    def fail_history_write(event) -> None:
        del event
        raise DataStoreError("simulated history write failure")

    monkeypatch.setattr(repository, "update_cancellation_event", fail_history_write)

    with pytest.raises(DataStoreError, match="simulated history write failure"):
        service.confirm_cancellation(
            "ORD-1001",
            "CUS-DEMO-001",
            check["confirmation_token"],
        )

    assert repository.get_order("ORD-1001").order_status == "processing"


@pytest.mark.parametrize(
    "outcome",
    ["cancelled", "declined", "ineligible", "withdrawn"],
)
def test_cancellation_history_records_distinct_outcomes(
    outcome: str,
    tmp_path: Path,
) -> None:
    case_directory = tmp_path / outcome
    case_directory.mkdir()
    shutil.copyfile(DATA_DIRECTORY / "orders.json", case_directory / "orders.json")
    _reset_test_order(case_directory)
    repository = JsonRepository(case_directory)
    service = CancellationService(repository)

    if outcome == "ineligible":
        check = service.check_eligibility("ORD-1002", "CUS-DEMO-002")
        assert check["eligible"] is False
        order_id = "ORD-1002"
        customer_id = "CUS-DEMO-002"
    else:
        check = service.check_eligibility("ORD-1001", "CUS-DEMO-001")
        order_id = "ORD-1001"
        customer_id = "CUS-DEMO-001"
        token = check["confirmation_token"]
        pending = json.loads(
            (case_directory / "cancellation_history.json").read_text(
                encoding="utf-8"
            )
        )
        assert pending[0]["outcome"] == "pending_confirmation"
        if outcome == "cancelled":
            result = service.confirm_cancellation(
                order_id,
                customer_id,
                token,
                reason_code="other",
                reason_text="The order is no longer needed.",
            )
            assert result["cancelled"] is True
        else:
            result = service.record_cancellation_decision(
                order_id,
                customer_id,
                token,
                outcome,
                reason_code="not_provided",
                idempotency_key=f"phase7-{outcome}-decision-key",
            )
            replay = service.record_cancellation_decision(
                order_id,
                customer_id,
                token,
                outcome,
                reason_code="not_provided",
                idempotency_key=f"phase7-{outcome}-decision-key",
            )
            assert result["recorded"] is True
            assert replay == result

    events = json.loads(
        (case_directory / "cancellation_history.json").read_text(
            encoding="utf-8"
        )
    )
    event = events[0]

    assert event["outcome"] == outcome
    assert event["outcome_at"] is not None
    assert event["eligibility_result"] == (
        "ineligible" if outcome == "ineligible" else "eligible"
    )
    if outcome == "cancelled":
        assert event["reason_code"] == "other"
        assert event["reason_text"] == "The order is no longer needed."
        assert repository.get_order(order_id).order_status == "cancelled"
    elif outcome in {"declined", "withdrawn"}:
        assert event["reason_code"] == "not_provided"
        assert event["reason_text"] is None
        assert repository.get_order(order_id).order_status == "processing"


def test_old_cancellation_history_is_expired(tmp_path: Path) -> None:
    case_directory = tmp_path / "retention"
    case_directory.mkdir()
    shutil.copyfile(DATA_DIRECTORY / "orders.json", case_directory / "orders.json")
    repository = JsonRepository(
        case_directory,
        cancellation_history_retention=timedelta(days=1),
    )
    CancellationService(repository).check_eligibility(
        "ORD-1002",
        "CUS-DEMO-002",
    )
    event = json.loads(
        (case_directory / "cancellation_history.json").read_text(
            encoding="utf-8"
        )
    )[0]
    requested_at = datetime.fromisoformat(event["requested_at"])

    assert repository.expire_old_cancellation_events(
        requested_at + timedelta(days=2)
    ) == 1
    assert json.loads(
        (case_directory / "cancellation_history.json").read_text(
            encoding="utf-8"
        )
    ) == []


def test_repository_rejects_malformed_json(repository: JsonRepository, tmp_path: Path) -> None:
    (tmp_path / "products.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(DataStoreError, match="invalid JSON"):
        repository.get_product("PROD-001")


def test_repository_detects_broken_relationships(
    repository: JsonRepository,
    tmp_path: Path,
) -> None:
    orders = json.loads((tmp_path / "orders.json").read_text(encoding="utf-8"))
    orders[0]["items"][0]["product_id"] = "PROD-MISSING"
    (tmp_path / "orders.json").write_text(json.dumps(orders), encoding="utf-8")

    with pytest.raises(DataStoreError, match="missing product"):
        repository.validate_references()

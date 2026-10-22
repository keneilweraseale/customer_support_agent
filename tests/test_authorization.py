import shutil
import time
from datetime import timedelta
from pathlib import Path

import pytest

from app.services.demo_authorization import (
    DemoAuthorizationError,
    DemoAuthorizationService,
)
from app.storage.json_store import DataStoreError, JsonRepository

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repository(tmp_path: Path) -> JsonRepository:
    shutil.copyfile(PROJECT_ROOT / "data" / "orders.json", tmp_path / "orders.json")
    return JsonRepository(tmp_path)


def test_demo_token_is_random_and_resolves_only_to_its_seeded_customer(
    repository: JsonRepository,
) -> None:
    service = DemoAuthorizationService(repository)

    first_token, _ = service.issue_token("CUS-DEMO-001")
    second_token, _ = service.issue_token("CUS-DEMO-002")

    assert first_token != second_token
    assert service.resolve_customer(first_token) == "CUS-DEMO-001"
    assert service.resolve_customer(second_token) == "CUS-DEMO-002"
    assert service.resolve_customer("unknown-token") is None


def test_demo_token_expires(repository: JsonRepository) -> None:
    service = DemoAuthorizationService(
        repository,
        token_lifetime=timedelta(milliseconds=10),
    )
    token, _ = service.issue_token("CUS-DEMO-001")
    time.sleep(0.02)

    assert service.resolve_customer(token) is None


def test_only_five_active_tokens_per_demo_customer_are_retained(
    repository: JsonRepository,
) -> None:
    service = DemoAuthorizationService(repository)
    tokens = [
        service.issue_token("CUS-DEMO-001")[0]
        for _ in range(6)
    ]

    assert service.resolve_customer(tokens[0]) is None
    assert all(
        service.resolve_customer(token) == "CUS-DEMO-001"
        for token in tokens[1:]
    )


def test_unknown_customer_cannot_receive_demo_token(repository: JsonRepository) -> None:
    service = DemoAuthorizationService(repository)

    with pytest.raises(DemoAuthorizationError):
        service.issue_token("CUS-DEMO-999")


def test_missing_order_file_fails_verification_explicitly(tmp_path: Path) -> None:
    service = DemoAuthorizationService(JsonRepository(tmp_path))

    with pytest.raises(DataStoreError, match="missing"):
        service.issue_token("CUS-DEMO-001")

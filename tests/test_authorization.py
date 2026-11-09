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
    shutil.copyfile(
        PROJECT_ROOT / "tests" / "fixtures" / "demo_data" / "orders.json",
        tmp_path / "orders.json",
    )
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


def test_login_uses_case_insensitive_email_and_stored_password_hash(
    repository: JsonRepository,
) -> None:
    service = DemoAuthorizationService(repository)
    password = "local-demo-password-123"
    service.create_account("Customer@Example.com", password, "CUS-DEMO-001")

    token, _ = service.authenticate("CUSTOMER@example.com", password)

    assert service.resolve_customer(token) == "CUS-DEMO-001"
    stored_account = repository.get_customer_accounts()[0]
    assert stored_account.email == "customer@example.com"
    assert password not in stored_account.password_hash
    assert stored_account.password_hash.startswith("scrypt$")
    assert password not in (
        repository.data_directory / "customer_accounts.json"
    ).read_text(encoding="utf-8")


def test_support_agent_login_issues_a_distinct_role_scoped_token(
    repository: JsonRepository,
) -> None:
    service = DemoAuthorizationService(repository)
    service.create_account(
        "customer@example.com",
        "local-demo-password-123",
        "CUS-DEMO-001",
    )
    service.create_support_agent_account(
        "agent@example.com",
        "support-agent-password-123",
        "STAFF-001",
    )

    customer_token, _ = service.authenticate(
        "customer@example.com",
        "local-demo-password-123",
    )
    staff_token, _ = service.authenticate_support_agent(
        "AGENT@example.com",
        "support-agent-password-123",
    )

    assert service.resolve_customer(customer_token) == "CUS-DEMO-001"
    assert service.resolve_support_agent(customer_token) is None
    assert service.resolve_support_agent(staff_token) == "STAFF-001"
    assert service.resolve_customer(staff_token) is None
    stored_agent = repository.get_support_agent_accounts()[0]
    assert stored_agent.role == "support_agent"
    assert stored_agent.password_hash.startswith("scrypt$")
    assert "support-agent-password-123" not in stored_agent.password_hash


def test_support_agent_authentication_rejects_unknown_account_and_password(
    repository: JsonRepository,
) -> None:
    service = DemoAuthorizationService(repository)
    service.create_support_agent_account(
        "agent@example.com",
        "support-agent-password-123",
        "STAFF-001",
    )

    with pytest.raises(DemoAuthorizationError, match="Invalid email or password"):
        service.authenticate_support_agent(
            "agent@example.com",
            "incorrect-password",
        )
    with pytest.raises(DemoAuthorizationError, match="Invalid email or password"):
        service.authenticate_support_agent(
            "unknown@example.com",
            "incorrect-password",
        )


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("customer@example.com", "wrong-password-123"),
        ("unknown@example.com", "wrong-password-123"),
    ],
)
def test_login_rejects_wrong_password_and_unknown_email(
    repository: JsonRepository,
    email: str,
    password: str,
) -> None:
    service = DemoAuthorizationService(repository)
    service.create_account(
        "customer@example.com",
        "local-demo-password-123",
        "CUS-DEMO-001",
    )

    with pytest.raises(DemoAuthorizationError, match="Invalid email or password"):
        service.authenticate(email, password)


def test_account_provisioning_rejects_unknown_or_duplicate_customer(
    repository: JsonRepository,
) -> None:
    service = DemoAuthorizationService(repository)

    with pytest.raises(DataStoreError, match="known customer"):
        service.create_account(
            "unknown@example.com",
            "local-demo-password-123",
            "CUS-DEMO-999",
        )

    service.create_account(
        "customer@example.com",
        "local-demo-password-123",
        "CUS-DEMO-001",
    )
    with pytest.raises(DataStoreError, match="already exists"):
        service.create_account(
            "other@example.com",
            "another-demo-password-123",
            "CUS-DEMO-001",
        )


def test_account_provisioning_requires_a_strong_password(
    repository: JsonRepository,
) -> None:
    service = DemoAuthorizationService(repository)

    with pytest.raises(ValueError, match="at least 12"):
        service.create_account("customer@example.com", "short", "CUS-DEMO-001")


def test_missing_order_file_fails_verification_explicitly(tmp_path: Path) -> None:
    service = DemoAuthorizationService(JsonRepository(tmp_path))

    with pytest.raises(DataStoreError, match="missing"):
        service.issue_token("CUS-DEMO-001")

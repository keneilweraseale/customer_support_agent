import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import admin_tickets, damage_reports
from app.main import app
from app.storage.json_store import DataStoreError, JsonRepository

client = TestClient(app)
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\xff\xd9"


@pytest.fixture
def report_repository(monkeypatch, tmp_path):
    source_orders = Path(__file__).resolve().parents[1] / "data" / "orders.json"
    (tmp_path / "orders.json").write_bytes(source_orders.read_bytes())
    repository = JsonRepository(tmp_path)
    monkeypatch.setattr(damage_reports, "damage_repository", repository)
    monkeypatch.setattr(admin_tickets, "support_repository", repository)
    return repository


def issue_token(customer_id="CUS-DEMO-001"):
    token, _ = damage_reports.demo_authorization_service.issue_token(customer_id)
    return token


def request_body(
    *,
    token=None,
    order_id="ORD-1001",
    image_bytes=JPEG_BYTES,
    image_type="image/jpeg",
    description="The corner is damaged.",
):
    return {
        "authorization_token": token or issue_token(),
        "order_id": order_id,
        "image_data": f"data:{image_type};base64,{base64.b64encode(image_bytes).decode()}",
        "description": description,
    }


def submit(body=None, key="damage-report-key-0001"):
    return client.post(
        "/api/damage-reports",
        json=body or request_body(),
        headers={"Idempotency-Key": key},
    )


def test_damage_report_is_saved_for_authenticated_order_owner(report_repository):
    response = submit()

    assert response.status_code == 201
    result = response.json()
    assert result["created"] is True
    assert result["order_id"] == "ORD-1001"
    assert result["ticket_id"] == f"DAMAGE-{result['report_id']}"
    assert result["message"] == (
        f"Your damage report was submitted. Support ticket {result['ticket_id']} is open."
    )
    records = json.loads((report_repository.data_directory / "damage_reports.json").read_text())
    assert len(records) == 1
    stored_image = (
        report_repository.data_directory
        / "damage_report_images"
        / records[0]["image_filename"]
    )
    assert stored_image.read_bytes() == JPEG_BYTES
    assert "image_data" not in records[0]
    assert "customer_id" not in result
    ticket = report_repository.get_support_ticket(result["ticket_id"])
    assert ticket is not None
    assert ticket.status == "open"
    assert ticket.priority == "high"
    assert ticket.customer_message == "The corner is damaged."
    assert ticket.messages[0].text == "The corner is damaged."
    assert ticket.attachments[0].attachment_id == result["report_id"]
    assert report_repository.get_damage_report_image(result["report_id"]) == JPEG_BYTES


def test_damage_report_ticket_and_image_are_available_to_support_agents(
    monkeypatch,
    report_repository,
):
    monkeypatch.setattr(
        admin_tickets.demo_authorization_service,
        "resolve_support_agent",
        lambda token: "STAFF-001" if token == "valid-agent-token" else None,
    )
    submitted = submit()
    ticket_id = submitted.json()["ticket_id"]
    attachment_id = submitted.json()["report_id"]

    unauthorized = client.get(
        f"/api/admin/tickets/{ticket_id}/attachments/{attachment_id}",
    )
    detail = client.get(
        f"/api/admin/tickets/{ticket_id}",
        headers={"Authorization": "Bearer valid-agent-token"},
    )
    ticket_list = client.get(
        "/api/admin/tickets",
        headers={"Authorization": "Bearer valid-agent-token"},
    )
    image = client.get(
        f"/api/admin/tickets/{ticket_id}/attachments/{attachment_id}",
        headers={"Authorization": "Bearer valid-agent-token"},
    )

    assert unauthorized.status_code == 401
    assert detail.status_code == 200
    assert detail.json()["status"] == "open"
    assert detail.json()["priority"] == "high"
    assert detail.json()["description"] == "The corner is damaged."
    assert detail.json()["attachments"] == [
        {
            "attachment_id": attachment_id,
            "filename": f"{attachment_id}.jpg",
            "content_type": "image/jpeg",
        }
    ]
    assert ticket_list.status_code == 200
    assert ticket_id in {
        ticket["ticket_id"] for ticket in ticket_list.json()["tickets"]
    }
    assert image.status_code == 200
    assert image.content == JPEG_BYTES
    assert image.headers["content-type"] == "image/jpeg"
    assert image.headers["cache-control"] == "private, no-store"
    assert report_repository.get_support_ticket(ticket_id) is not None


def test_same_idempotency_key_returns_original_report(report_repository):
    first = submit()
    repeated = submit()

    assert first.status_code == 201
    assert repeated.status_code == 201
    assert repeated.json()["created"] is False
    assert repeated.json()["report_id"] == first.json()["report_id"]
    records = json.loads((report_repository.data_directory / "damage_reports.json").read_text())
    assert len(records) == 1


def test_ticket_creation_failure_is_reported_and_retry_opens_same_ticket(
    monkeypatch,
    report_repository,
):
    append_ticket = report_repository.append_support_ticket
    calls = 0

    def fail_once(ticket):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise DataStoreError("simulated ticket storage failure")
        append_ticket(ticket)

    monkeypatch.setattr(report_repository, "append_support_ticket", fail_once)

    failed_response = submit()
    retry_response = submit()

    assert failed_response.status_code == 503
    assert "ticket could not be opened" in failed_response.json()["error"]["message"]
    assert retry_response.status_code == 201
    assert retry_response.json()["created"] is False
    assert retry_response.json()["ticket_id"].startswith("DAMAGE-")
    assert "was submitted" in retry_response.json()["message"]
    assert len(report_repository.get_support_tickets()) == 1


def test_reusing_idempotency_key_for_different_image_is_rejected(report_repository):
    submit()
    response = submit(request_body(image_bytes=b"\xff\xd8\xff\xe1\x00\x10test\xff\xd9"))

    assert response.status_code == 409
    assert "already used" in response.json()["error"]["message"]


def test_damage_report_requires_a_valid_session(report_repository):
    response = submit(request_body(token="A" * 40))

    assert response.status_code == 401


def test_customer_cannot_report_damage_for_another_customers_order(report_repository):
    response = submit(request_body(order_id="ORD-1002"))

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "That order could not be found in your account."


def test_missing_order_reference_is_rejected(report_repository):
    body = request_body()
    del body["order_id"]

    response = submit(body)

    assert response.status_code == 422


def test_damage_report_requires_a_message(report_repository):
    body = request_body()
    body.pop("description")

    missing = submit(body)
    blank = submit(request_body(description="   "), key="damage-report-key-0002")

    assert missing.status_code == 422
    assert blank.status_code == 422
    assert report_repository.get_support_tickets() == []


@pytest.mark.parametrize(
    ("image_data", "expected_status"),
    [
        ("not-an-image", 422),
        ("data:image/gif;base64,R0lGODlh", 422),
        (
            f"data:image/png;base64,{base64.b64encode(JPEG_BYTES).decode()}",
            415,
        ),
    ],
)
def test_invalid_or_unsupported_image_is_rejected(
    report_repository,
    image_data,
    expected_status,
):
    body = request_body()
    body["image_data"] = image_data

    response = submit(body)

    assert response.status_code == expected_status


def test_image_exceeding_limit_is_rejected(report_repository):
    oversized_image = b"\xff\xd8\xff" + b"x" * (damage_reports.MAX_IMAGE_BYTES - 2)

    response = submit(request_body(image_bytes=oversized_image))

    assert response.status_code == 413


def test_storage_failure_is_reported_without_success_response(monkeypatch, report_repository):
    def fail_create(*args, **kwargs):
        raise DataStoreError("simulated storage failure")

    monkeypatch.setattr(report_repository, "create_damage_report", fail_create)

    response = submit()

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Your damage report could not be saved. Please try again."
    assert not (report_repository.data_directory / "damage_reports.json").exists()

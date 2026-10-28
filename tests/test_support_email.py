import smtplib

import pytest

from app.services.support_email import (
    SupportEmailConfigurationError,
    send_support_email,
)


def test_support_email_sends_ticket_message_over_starttls(monkeypatch) -> None:
    sent_messages = []
    events = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            events.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def starttls(self, context):
            events.append(("starttls", context))

        def login(self, username, password):
            events.append(("login", username, password))

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setenv("SUPPORT_EMAIL", "support@example.test")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "mailer@example.test")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-secret")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    monkeypatch.setenv("SMTP_USE_SSL", "false")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    send_support_email(
        "SUP-TEST-1",
        "Please investigate my order.",
        "customer@example.test",
    )

    assert events[0] == ("connect", "smtp.example.test", 587, 15)
    assert events[1][0] == "starttls"
    assert events[2] == ("login", "mailer@example.test", "smtp-secret")
    assert sent_messages[0]["To"] == "support@example.test"
    assert sent_messages[0]["From"] == "mailer@example.test"
    assert sent_messages[0]["Reply-To"] == "customer@example.test"
    assert sent_messages[0]["Subject"] == "Customer support ticket SUP-TEST-1"
    assert "Please investigate my order." in sent_messages[0].get_content()


def test_support_email_requires_recipient_and_smtp_host(monkeypatch) -> None:
    monkeypatch.delenv("SUPPORT_EMAIL", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)

    with pytest.raises(SupportEmailConfigurationError):
        send_support_email(
            "SUP-TEST-1",
            "Please investigate my order.",
            "customer@example.test",
        )


def test_support_email_rejects_invalid_tls_setting(monkeypatch) -> None:
    monkeypatch.setenv("SUPPORT_EMAIL", "support@example.test")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_USE_TLS", "sometimes")

    with pytest.raises(SupportEmailConfigurationError, match="SMTP_USE_TLS"):
        send_support_email(
            "SUP-TEST-1",
            "Please investigate my order.",
            "customer@example.test",
        )

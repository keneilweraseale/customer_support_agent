""" ***We might have to look into this since we were adviced to remove the support email section*** """

import os
import smtplib
import ssl
from email.message import EmailMessage


class SupportEmailConfigurationError(RuntimeError):
    """Raised when outgoing support email is not configured."""


def send_support_email(ticket_id: str, message: str, reply_to: str) -> None:
    recipient = os.environ.get("SUPPORT_EMAIL", "").strip()
    host = os.environ.get("SMTP_HOST", "").strip()
    if not recipient or not host:
        raise SupportEmailConfigurationError(
            "Support email delivery is not configured."
        )

    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM_EMAIL", "").strip() or username or recipient
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
    except ValueError as exc:
        raise SupportEmailConfigurationError("SMTP_PORT must be a valid port.") from exc
    if not 1 <= port <= 65535:
        raise SupportEmailConfigurationError("SMTP_PORT must be between 1 and 65535.")
    if bool(username) != bool(password):
        raise SupportEmailConfigurationError(
            "SMTP_USERNAME and SMTP_PASSWORD must be configured together."
        )

    email = EmailMessage()
    email["Subject"] = f"Customer support ticket {ticket_id}"
    email["From"] = sender
    email["To"] = recipient
    email["Reply-To"] = reply_to
    email.set_content(f"Customer message for ticket {ticket_id}:\n\n{message}")

    timeout = 15
    if _environment_flag("SMTP_USE_SSL", default=False):
        with smtplib.SMTP_SSL(
            host,
            port,
            timeout=timeout,
            context=ssl.create_default_context(),
        ) as server:
            if username:
                server.login(username, password)
            server.send_message(email)
        return

    use_tls = _environment_flag("SMTP_USE_TLS", default=True)
    with smtplib.SMTP(host, port, timeout=timeout) as server:
        if use_tls:
            server.starttls(context=ssl.create_default_context())
        if username:
            server.login(username, password)
        server.send_message(email)


def _environment_flag(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise SupportEmailConfigurationError(f"{name} must be 'true' or 'false'.")

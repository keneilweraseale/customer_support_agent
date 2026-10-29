from datetime import datetime, timezone

from app.services.conversation_memory import sanitize_sensitive_text
from app.storage.models import (
    SupportTicket,
    SupportTicketCustomerUpdate,
    SupportTicketStatus,
    SupportTicketStatusChange,
)
from app.storage.repository import SupportRepository

_ALLOWED_STATUS_TRANSITIONS: dict[
    SupportTicketStatus,
    set[SupportTicketStatus],
] = {
    "open": {"investigating", "waiting_for_customer", "escalated", "resolved"},
    "investigating": {"open", "waiting_for_customer", "escalated", "resolved"},
    "waiting_for_customer": {"open", "investigating", "escalated", "resolved"},
    "escalated": {"open", "investigating", "waiting_for_customer", "resolved"},
    "resolved": {"open"},
}
MAX_STATUS_HISTORY = 100


class InvalidSupportTicketTransition(ValueError):
    """Raised when a requested support-ticket status transition is not allowed."""


class SupportTicketService:
    def __init__(self, repository: SupportRepository) -> None:
        self._repository = repository

    def update_status(
        self,
        ticket_id: str,
        status: SupportTicketStatus,
        staff_id: str,
        note: str,
        customer_update: str | None = None,
    ) -> tuple[SupportTicket | None, bool]:
        ticket = self._repository.get_support_ticket(ticket_id)
        if ticket is None:
            return None, False
        if ticket.status == status:
            return ticket, False
        if status not in _ALLOWED_STATUS_TRANSITIONS[ticket.status]:
            raise InvalidSupportTicketTransition(
                f"Cannot move a {ticket.status} ticket to {status}."
            )
        if status in {"waiting_for_customer", "resolved"} and not (
            customer_update and customer_update.strip()
        ):
            raise InvalidSupportTicketTransition(
                f"A customer-facing update is required when moving a ticket to {status}."
            )

        now = datetime.now(timezone.utc)
        change = SupportTicketStatusChange(
            previous_status=ticket.status,
            status=status,
            changed_by=staff_id,
            changed_at=now,
            note=sanitize_sensitive_text(note),
        )
        if (
            customer_update is not None
            and status in {"waiting_for_customer", "resolved"}
        ):
            sanitized_customer_update = SupportTicketCustomerUpdate(
                status=status,
                message=sanitize_sensitive_text(customer_update),
                created_at=now,
            )
        else:
            sanitized_customer_update = None
        updated = SupportTicket.model_validate(
            ticket.model_dump()
            | {
                "status": status,
                "status_history": [
                    *ticket.status_history,
                    change,
                ][-MAX_STATUS_HISTORY:],
                "customer_update": sanitized_customer_update,
            }
        )
        updated_ticket = self._repository.update_support_ticket(
            updated,
            expected_status=ticket.status,
        )
        return updated_ticket, updated_ticket is not None

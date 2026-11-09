from datetime import datetime, timezone
from typing import Annotated, Callable, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.agent.tools import repository as support_repository
from app.services.conversation_memory import sanitize_sensitive_text
from app.services.demo_authorization import demo_authorization_service
from app.services.support_tickets import (
    InvalidSupportTicketTransition,
    SupportTicketService,
)
from app.storage.json_store import DataStoreError, SupportTicketConflictError
from app.storage.models import (
    SupportAgentAccount,
    SupportTicket,
    SupportTicketAttachment,
    SupportTicketAuditEvent,
    SupportTicketInternalNote,
    SupportTicketMessage,
    SupportTicketStatus,
    SupportTicketStatusChange,
)

router = APIRouter(prefix="/api/admin", tags=["admin tickets"])
Priority = Literal["low", "medium", "high", "critical"]
TicketText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]


class AdminTicketListResponse(BaseModel):
    tickets: list[dict[str, object]]
    total: int
    page: int
    page_size: int


class AdminTicketDetail(BaseModel):
    ticket_id: str
    customer_id: str | None
    customer_email: str | None
    subject: str
    description: str
    category: str
    priority: Priority
    status: SupportTicketStatus
    assigned_to: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[SupportTicketMessage]
    attachments: list[SupportTicketAttachment]
    internal_notes: list[SupportTicketInternalNote]
    status_history: list[SupportTicketStatusChange]
    audit_history: list[SupportTicketAuditEvent]


class SupportAgentSummary(BaseModel):
    staff_id: str
    email: str


class TicketMutationResponse(BaseModel):
    ticket_id: str
    status: SupportTicketStatus
    priority: Priority
    assigned_to: str | None
    updated_at: datetime


class StatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: SupportTicketStatus
    note: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
    ] = "Updated by support agent."
    customer_message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
    ] | None = None


class PriorityUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: Priority


class AssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assigned_to: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ] | None


class ReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: TicketText


class NoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: TicketText


def _require_support_agent(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Sign in as a support agent to access tickets.",
        )
    staff_id = demo_authorization_service.resolve_support_agent(
        authorization.removeprefix("Bearer ").strip()
    )
    if staff_id is None:
        raise HTTPException(
            status_code=401,
            detail="Your support-agent session is missing or expired.",
        )
    return staff_id


def _updated_at(ticket: SupportTicket) -> datetime:
    return max(
        [ticket.created_at, *(change.changed_at for change in ticket.status_history)]
        + ([ticket.updated_at] if ticket.updated_at else [])
        + [message.created_at for message in ticket.messages]
        + [note.created_at for note in ticket.internal_notes]
    )


def _ticket_summary(
    ticket: SupportTicket,
    email_by_customer: dict[str, str],
) -> dict[str, object]:
    return {
        "ticket_id": ticket.ticket_id,
        "customer_id": ticket.customer_id,
        "customer_email": email_by_customer.get(ticket.customer_id or ""),
        "subject": ticket.issue_summary or ticket.customer_message,
        "category": ticket.category,
        "priority": ticket.priority,
        "status": ticket.status,
        "assigned_to": ticket.assigned_to,
        "created_at": ticket.created_at,
        "updated_at": _updated_at(ticket),
    }


async def _admin_detail(ticket: SupportTicket) -> AdminTicketDetail:
    customers = await run_in_threadpool(support_repository.get_customer_accounts)
    customer_email = next(
        (
            account.email
            for account in customers
            if account.customer_id == ticket.customer_id
        ),
        None,
    )
    return AdminTicketDetail(
        ticket_id=ticket.ticket_id,
        customer_id=ticket.customer_id,
        customer_email=customer_email,
        subject=ticket.issue_summary or ticket.customer_message,
        description=ticket.customer_message,
        category=ticket.category,
        priority=ticket.priority,
        status=ticket.status,
        assigned_to=ticket.assigned_to,
        created_at=ticket.created_at,
        updated_at=_updated_at(ticket),
        messages=ticket.messages,
        attachments=ticket.attachments,
        internal_notes=ticket.internal_notes,
        status_history=ticket.status_history,
        audit_history=ticket.audit_history,
    )


@router.get("/dashboard/stats")
async def dashboard_stats(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> dict[str, int]:
    _require_support_agent(authorization)
    try:
        tickets = await run_in_threadpool(support_repository.get_support_tickets)
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Support tickets are temporarily unavailable.",
        ) from exc
    stats = {
        status: sum(ticket.status == status for ticket in tickets)
        for status in ("open", "investigating", "waiting_for_customer", "resolved", "closed")
    }
    stats["total"] = len(tickets)
    stats["investigating"] += sum(ticket.status == "escalated" for ticket in tickets)
    return stats


@router.get("/agents", response_model=list[SupportAgentSummary])
async def list_support_agents(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> list[SupportAgentSummary]:
    _require_support_agent(authorization)
    try:
        agents = await run_in_threadpool(support_repository.get_support_agent_accounts)
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Support-agent accounts are unavailable.",
        ) from exc
    return [SupportAgentSummary(staff_id=agent.staff_id, email=agent.email) for agent in agents]


@router.get("/categories", response_model=list[str])
async def list_ticket_categories(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> list[str]:
    _require_support_agent(authorization)
    try:
        tickets = await run_in_threadpool(support_repository.get_support_tickets)
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Support tickets are temporarily unavailable.",
        ) from exc
    return sorted({ticket.category for ticket in tickets}, key=str.casefold)


@router.get("/tickets", response_model=AdminTicketListResponse)
async def list_admin_tickets(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    search: str = "",
    status: str | None = None,
    priority: Priority | None = None,
    category: str | None = None,
    assigned_to: str | None = None,
    sort_by: Literal["created_at", "updated_at", "priority"] = "updated_at",
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AdminTicketListResponse:
    _require_support_agent(authorization)
    try:
        tickets = await run_in_threadpool(support_repository.get_support_tickets)
        customers = await run_in_threadpool(support_repository.get_customer_accounts)
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Support tickets are temporarily unavailable.",
        ) from exc
    email_by_customer = {account.customer_id: account.email for account in customers}
    term = search.casefold().strip()
    filtered = [
        ticket
        for ticket in tickets
        if (
            not term
            or term in ticket.ticket_id.casefold()
            or term in (ticket.customer_id or "").casefold()
            or term in email_by_customer.get(ticket.customer_id or "", "").casefold()
            or term in (ticket.issue_summary or "").casefold()
        )
        and (
            not status
            or ticket.status == status
            or (status == "investigating" and ticket.status == "escalated")
        )
        and (not priority or ticket.priority == priority)
        and (not category or ticket.category.casefold() == category.casefold())
        and (not assigned_to or ticket.assigned_to == assigned_to)
    ]
    priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    if sort_by == "priority":
        filtered.sort(key=lambda ticket: priority_rank[ticket.priority])
    else:
        filtered.sort(
            key=lambda ticket: (
                _updated_at(ticket) if sort_by == "updated_at" else ticket.created_at
            )
        )
    if sort_order == "desc":
        filtered.reverse()
    start = (page - 1) * page_size
    return AdminTicketListResponse(
        tickets=[
            _ticket_summary(ticket, email_by_customer)
            for ticket in filtered[start : start + page_size]
        ],
        total=len(filtered),
        page=page,
        page_size=page_size,
    )


@router.get("/tickets/{ticket_id}", response_model=AdminTicketDetail)
async def get_admin_ticket(
    ticket_id: str,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> AdminTicketDetail:
    _require_support_agent(authorization)
    try:
        ticket = await run_in_threadpool(support_repository.get_support_ticket, ticket_id)
        if ticket is not None:
            return await _admin_detail(ticket)
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Support tickets are temporarily unavailable.",
        ) from exc
    raise HTTPException(status_code=404, detail="Support ticket could not be found.")


@router.get("/tickets/{ticket_id}/attachments/{attachment_id}")
async def get_admin_ticket_attachment(
    ticket_id: str,
    attachment_id: str,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Response:
    _require_support_agent(authorization)
    try:
        ticket = await run_in_threadpool(
            support_repository.get_support_ticket,
            ticket_id,
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="Support ticket could not be found.")
        attachment = next(
            (
                item
                for item in ticket.attachments
                if item.attachment_id == attachment_id
            ),
            None,
        )
        if attachment is None:
            raise HTTPException(status_code=404, detail="Ticket attachment could not be found.")
        image_bytes = await run_in_threadpool(
            support_repository.get_damage_report_image,
            attachment_id,
        )
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Ticket attachments are temporarily unavailable.",
        ) from exc
    if image_bytes is None:
        raise HTTPException(status_code=404, detail="Ticket attachment could not be found.")
    return Response(
        content=image_bytes,
        media_type=attachment.content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'inline; filename="{attachment.filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.patch("/tickets/{ticket_id}/status", response_model=TicketMutationResponse)
async def update_admin_ticket_status(
    ticket_id: str,
    request: StatusUpdateRequest,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> TicketMutationResponse:
    staff_id = _require_support_agent(authorization)
    try:
        ticket, _ = await run_in_threadpool(
            SupportTicketService(support_repository).update_status,
            ticket_id,
            request.status,
            staff_id,
            request.note,
            request.customer_message,
        )
    except InvalidSupportTicketTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupportTicketConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="The ticket changed concurrently. Reload it and try again.",
        ) from exc
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Support tickets are temporarily unavailable.",
        ) from exc
    if ticket is None:
        raise HTTPException(status_code=404, detail="Support ticket could not be found.")
    return TicketMutationResponse(
        ticket_id=ticket.ticket_id,
        status=ticket.status,
        priority=ticket.priority,
        assigned_to=ticket.assigned_to,
        updated_at=_updated_at(ticket),
    )


async def _mutate_ticket(
    ticket_id: str,
    changes: dict[str, object] | Callable[[SupportTicket], dict[str, object]],
    staff_id: str,
    action: Literal[
        "priority_changed",
        "assignment_changed",
        "reply_sent",
        "internal_note_added",
    ],
    description: str,
) -> TicketMutationResponse:
    try:
        ticket = await run_in_threadpool(support_repository.get_support_ticket, ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="Support ticket could not be found.")
        mutation = changes(ticket) if callable(changes) else changes
        audit_event = SupportTicketAuditEvent(
            action=action,
            changed_by=staff_id,
            description=description,
            created_at=datetime.now(timezone.utc),
        )
        updated = SupportTicket.model_validate(
            ticket.model_dump()
            | mutation
            | {
                "updated_at": datetime.now(timezone.utc),
                "audit_history": [*ticket.audit_history, audit_event][-500:],
            }
        )
        saved = await run_in_threadpool(
            support_repository.update_support_ticket,
            updated,
            ticket.status,
            ticket.updated_at,
        )
    except SupportTicketConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="The ticket changed concurrently. Reload it and try again.",
        ) from exc
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Support tickets are temporarily unavailable.",
        ) from exc
    if saved is None:
        raise HTTPException(status_code=404, detail="Support ticket could not be found.")
    return TicketMutationResponse(
        ticket_id=saved.ticket_id,
        status=saved.status,
        priority=saved.priority,
        assigned_to=saved.assigned_to,
        updated_at=_updated_at(saved),
    )


@router.patch("/tickets/{ticket_id}/priority", response_model=TicketMutationResponse)
async def update_admin_ticket_priority(
    ticket_id: str,
    request: PriorityUpdateRequest,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> TicketMutationResponse:
    staff_id = _require_support_agent(authorization)
    return await _mutate_ticket(
        ticket_id,
        {"priority": request.priority},
        staff_id,
        "priority_changed",
        f"Priority set to {request.priority}.",
    )


@router.patch("/tickets/{ticket_id}/assign", response_model=TicketMutationResponse)
async def assign_admin_ticket(
    ticket_id: str,
    request: AssignmentRequest,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> TicketMutationResponse:
    staff_id = _require_support_agent(authorization)
    if request.assigned_to is not None:
        try:
            accounts = await run_in_threadpool(
                support_repository.get_support_agent_accounts
            )
        except DataStoreError as exc:
            raise HTTPException(
                status_code=503,
                detail="Support-agent accounts are unavailable.",
            ) from exc
        if request.assigned_to not in {account.staff_id for account in accounts}:
            raise HTTPException(status_code=422, detail="Select a valid support agent.")
    return await _mutate_ticket(
        ticket_id,
        {"assigned_to": request.assigned_to},
        staff_id,
        "assignment_changed",
        f"Assigned to {request.assigned_to or 'unassigned'}.",
    )


@router.post("/tickets/{ticket_id}/reply", response_model=TicketMutationResponse)
async def reply_to_admin_ticket(
    ticket_id: str,
    request: ReplyRequest,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> TicketMutationResponse:
    staff_id = _require_support_agent(authorization)
    try:
        message = SupportTicketMessage(
            author_role="support_agent",
            author_id=staff_id,
            text=sanitize_sensitive_text(request.message),
            created_at=datetime.now(timezone.utc),
        )
        return await _mutate_ticket(
            ticket_id,
            lambda ticket: {"messages": [*ticket.messages, message][-200:]},
            staff_id,
            "reply_sent",
            "Customer-visible reply sent.",
        )
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Support tickets are temporarily unavailable.",
        ) from exc


@router.post("/tickets/{ticket_id}/notes", response_model=TicketMutationResponse)
async def add_admin_ticket_note(
    ticket_id: str,
    request: NoteRequest,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> TicketMutationResponse:
    staff_id = _require_support_agent(authorization)
    try:
        note = SupportTicketInternalNote(
            staff_id=staff_id,
            text=sanitize_sensitive_text(request.note),
            created_at=datetime.now(timezone.utc),
        )
        return await _mutate_ticket(
            ticket_id,
            lambda ticket: {"internal_notes": [*ticket.internal_notes, note][-200:]},
            staff_id,
            "internal_note_added",
            "Internal staff note added.",
        )
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Support tickets are temporarily unavailable.",
        ) from exc
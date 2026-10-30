import logging
import re
import smtplib
from datetime import datetime, timezone
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.agent.intent_classifier import (
    GroqIntentClassifier,
    intent_classifier_from_environment,
)
from app.agent.router import (
    ChatRoute,
    ESCALATION_WORDS,
    OrchestratedChatResult,
    ORDER_ID_PATTERN,
    GOODBYE_MESSAGE_PATTERN,
    build_default_orchestrator,
    classify_message,
    classify_message_with_intent,
    has_any,
    requests_order_search,
    requests_other_order,
)
from app.rag.providers import ProviderConfigurationError
from app.services.conversation_memory import (
    ConversationMemoryService,
    format_conversation_recall,
    is_conversation_recall_request,
    sanitize_sensitive_text,
    unambiguous_order_context,
)
from app.services.demo_authorization import demo_authorization_service
from app.services.moderation import (
    ModerationUnavailable,
    contains_sensitive_output,
    moderation_service_from_environment,
    requests_sensitive_disclosure,
)
from app.services.support_email import (
    SupportEmailConfigurationError,
    send_support_email,
)
from app.services.support_tickets import (
    InvalidSupportTicketTransition,
    SupportTicketService,
)
from app.agent.tools import repository as support_repository
from app.storage.json_store import ConversationOwnershipError, DataStoreError
from app.storage.models import (
    ConversationTurn,
    SupportTicket,
    SupportTicketCustomerUpdate,
    SupportTicketMessage,
    SupportTicketStatus,
    SupportTicketStatusChange,
)

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)
orchestrator = build_default_orchestrator()
intent_classifier: GroqIntentClassifier | None = None
_intent_classifier_initialized = False
conversation_memory_service = ConversationMemoryService(support_repository)

MessageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
ConversationId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
TicketId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=5,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    ),
]
SUPPORT_TICKET_FOLLOW_UP = re.compile(
    r"\b(?:write|send|add|include|provide|share)\b.{0,100}"
    r"\b(?:message|details|information|what happened|problem)\b.{0,100}"
    r"\b(?:support|team|ticket|human|them)\b",
    re.IGNORECASE,
)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: MessageText
    conversation_id: ConversationId | None = None
    memory_enabled: bool = True
    authorization_token: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=40,
            max_length=128,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ] | None = None


class ConversationHistoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: ConversationId
    authorization_token: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=40,
            max_length=128,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ]


class ConversationHistoryResponse(BaseModel):
    conversation_id: str
    turns: list[ConversationTurn]


class SupportMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
    ]
    authorization_token: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=40,
            max_length=128,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ]


class SupportTicketStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SupportTicketStatus
    note: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
    ]
    customer_message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
    ] | None = None


class SupportTicketStatusResponse(BaseModel):
    ticket_id: str
    status: SupportTicketStatus
    changed: bool
    changed_at: datetime | None = None
    changed_by: str | None = None


class SupportTicketDetailResponse(BaseModel):
    ticket_id: str
    conversation_id: str
    customer_id: str | None
    order_id: str | None
    customer_message: str
    issue_summary: str | None
    conversation_context: list[ConversationTurn]
    status: SupportTicketStatus
    status_history: list[SupportTicketStatusChange]
    customer_update: SupportTicketCustomerUpdate | None
    created_at: datetime


class CustomerSupportTicketStatusResponse(BaseModel):
    ticket_id: str
    status: SupportTicketStatus
    customer_message: str | None


class CustomerTicketSummary(BaseModel):
    ticket_id: str
    subject: str
    status: SupportTicketStatus
    created_at: datetime
    updated_at: datetime


class CustomerTicketStatusEvent(BaseModel):
    previous_status: SupportTicketStatus
    status: SupportTicketStatus
    changed_at: datetime


class CustomerTicketDetail(CustomerTicketSummary):
    description: str
    messages: list[CustomerTicketMessage]
    status_history: list[CustomerTicketStatusEvent]
    customer_update: SupportTicketCustomerUpdate | None


class CustomerTicketMessage(BaseModel):
    role: str
    text: str
    created_at: datetime


class CustomerTicketListResponse(BaseModel):
    tickets: list[CustomerTicketSummary]


class MemoryDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    short_term_used: bool
    long_term_record_created: bool


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    route: str
    sources: list[dict[str, str]]
    actions: list[dict[str, object]]
    needs_confirmation: bool = False
    needs_human_support: bool = False
    memory: MemoryDiagnostics


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    started_at = perf_counter()
    conversation_id = request.conversation_id or str(uuid4())
    if requests_sensitive_disclosure(request.message):
        return _safety_blocked_response(conversation_id)
    moderation_service = moderation_service_from_environment()
    if moderation_service is not None:
        try:
            flagged = await run_in_threadpool(
                moderation_service.is_flagged,
                request.message,
            )
        except ModerationUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail="Message safety screening is temporarily unavailable.",
            ) from exc
        if flagged:
            return _safety_blocked_response(conversation_id)

    decision = classify_message(request.message)
    customer_id = None
    if request.authorization_token is not None:
        customer_id = demo_authorization_service.resolve_customer(
            request.authorization_token
        )
    message_lower = request.message.casefold()
    ticket_lookup = (
        has_any(message_lower, ("ticket", "complaint"))
        and has_any(
            message_lower,
            ("status", "update", "open", "resolved", "closed", "show", "list"),
        )
    )
    if ticket_lookup:
        if customer_id is None:
            raise HTTPException(
                status_code=401,
                detail="Sign in to check your support tickets.",
            )
        try:
            owned_tickets = [
                ticket
                for ticket in await run_in_threadpool(
                    support_repository.get_support_tickets
                )
                if ticket.customer_id == customer_id
            ]
        except DataStoreError as exc:
            raise HTTPException(
                status_code=503,
                detail="Support tickets are temporarily unavailable.",
            ) from exc

        requested_ticket_id = re.search(
            r"\b(?:SUP|TKT)-[A-Z0-9-]{1,60}\b",
            request.message.upper(),
        )
        if requested_ticket_id:
            owned_tickets = [
                ticket
                for ticket in owned_tickets
                if ticket.ticket_id == requested_ticket_id.group(0)
            ]
        elif "open" in message_lower:
            owned_tickets = [ticket for ticket in owned_tickets if ticket.status == "open"]

        if not owned_tickets:
            answer = (
                "I couldn’t find a matching support ticket in your account. "
                "Open My Support Tickets to review your requests."
            )
        else:
            owned_tickets.sort(key=lambda ticket: ticket.created_at, reverse=True)
            ticket_lines = [
                f"{ticket.ticket_id}: {ticket.issue_summary or ticket.customer_message} "
                f"({_customer_status_label(ticket.status)})."
                for ticket in owned_tickets[:10]
            ]
            answer = (
                "Here are the latest matching updates from your support tickets:\n"
                + "\n".join(ticket_lines)
                + "\nOpen My Support Tickets to see the full timeline."
            )
        return ChatResponse(
            conversation_id=conversation_id,
            answer=answer,
            route="ticket_lookup",
            sources=[],
            actions=[],
            memory=MemoryDiagnostics(
                short_term_used=False,
                long_term_record_created=False,
            ),
        )
    requires_authentication = decision.route in {
        ChatRoute.ORDER,
        ChatRoute.DELIVERY,
        ChatRoute.PAYMENT,
        ChatRoute.MULTI,
        ChatRoute.CANCELLATION,
        ChatRoute.BILLING_ISSUE,
        ChatRoute.CONVERSATION_RECALL,
    }
    if requires_authentication and request.authorization_token is None:
        raise HTTPException(
            status_code=401,
            detail="Sign in before asking about your orders.",
        )
    if request.authorization_token is not None:
        customer_id = demo_authorization_service.resolve_customer(
            request.authorization_token
        )
        if requires_authentication and customer_id is None:
            raise HTTPException(
                status_code=401,
                detail="Your session is missing or expired. Please sign in again.",
            )

    memory = None
    if customer_id is not None and request.memory_enabled:
        try:
            memory = await run_in_threadpool(
                conversation_memory_service.get,
                conversation_id,
                customer_id,
            )
        except DataStoreError as exc:
            raise HTTPException(
                status_code=503,
                detail="Conversation context is temporarily unavailable.",
            ) from exc

    contextualized_message = (
        _contextualize_other_order_follow_up(request.message, memory.turns)
        if memory is not None
        else request.message
    )
    decision = classify_message(contextualized_message)
    conversation_context = conversation_memory_service.classifier_context(
        memory,
        request.message,
    )
    deterministic_decision = decision
    decision = classify_message_with_intent(
        request.message,
        _configured_intent_classifier(),
        conversation_context,
    )
    private_order_routes = {
        ChatRoute.ORDER,
        ChatRoute.DELIVERY,
        ChatRoute.PAYMENT,
        ChatRoute.CANCELLATION,
        ChatRoute.BILLING_ISSUE,
        ChatRoute.CONVERSATION_RECALL,
    }
    if any(
        route in private_order_routes
        for route in (decision.route, *decision.additional_routes)
    ) and customer_id is None:
        raise HTTPException(
            status_code=401,
            detail=(
                "Sign in before asking about your orders."
                if request.authorization_token is None
                else "Your session is missing or expired. Please sign in again."
            ),
        )
    context_order_id = memory.last_order_id if memory is not None else None
    if (
        decision.route == ChatRoute.CANCELLATION
        and ORDER_ID_PATTERN.search(request.message) is None
        and memory is not None
    ):
        context_order_id = unambiguous_order_context(
            memory.turns,
            memory.last_order_id,
        )
    memory_context_used = (
        request.memory_enabled
        and customer_id is not None
        and context_order_id is not None
        and decision.route
        in {
            ChatRoute.ORDER,
            ChatRoute.DELIVERY,
            ChatRoute.PAYMENT,
            ChatRoute.MULTI,
            ChatRoute.CANCELLATION,
            ChatRoute.BILLING_ISSUE,
        }
        and decision.order_id is None
        and (
            not requests_order_search(request.message)
            or requests_other_order(request.message)
        )
    )
    ticket_follow_up = (
        decision.route == ChatRoute.SUPPORT_TICKET_MESSAGE
        or SUPPORT_TICKET_FOLLOW_UP.search(request.message) is not None
    )
    if decision.route in {
        ChatRoute.ORDER,
        ChatRoute.DELIVERY,
        ChatRoute.PAYMENT,
        ChatRoute.CANCELLATION,
        ChatRoute.BILLING_ISSUE,
    } or ticket_follow_up:
        if customer_id is None:
            if request.authorization_token is None:
                raise HTTPException(
                    status_code=401,
                    detail=(
                        "Sign in before adding a message to a support ticket."
                        if ticket_follow_up
                        else "Sign in before asking about your orders."
                    ),
                )
            raise HTTPException(
                status_code=401,
                detail="Your session is missing or expired. Please sign in again.",
            )

    if decision.route == ChatRoute.CLOSING:
        ticket = None
        if customer_id is not None:
            try:
                ticket = await run_in_threadpool(
                    support_repository.get_latest_support_ticket_for_conversation,
                    conversation_id,
                    customer_id,
                )
            except DataStoreError as exc:
                raise HTTPException(
                    status_code=503,
                    detail="Support ticket information is temporarily unavailable.",
                ) from exc
        if ticket is not None:
            answer = (
                f"You’re very welcome! Your support ticket {ticket.ticket_id} "
                "is still open. You can add any other details using its ticket "
                "form in this conversation. Take care, and you’re welcome back "
                "anytime."
            )
        elif GOODBYE_MESSAGE_PATTERN.search(request.message):
            answer = (
                "Bye for now! Thanks for chatting with us—have a lovely day. "
                "You’re welcome back anytime."
            )
        else:
            answer = (
                "You’re very welcome! I’m glad I could help. If another "
                "store-related question comes up, just let me know."
            )
        result = OrchestratedChatResult(
            answer=answer,
            route=ChatRoute.CLOSING,
            sources=[],
            actions=[],
        )
    elif decision.route == ChatRoute.CONVERSATION_RECALL:
        result = OrchestratedChatResult(
            answer=conversation_memory_service.answer_recall(
                request.message,
                memory,
            ),
            route=ChatRoute.CONVERSATION_RECALL,
            sources=[],
            actions=[],
        )
        memory_context_used = memory is not None
    elif ticket_follow_up:
        try:
            ticket = await run_in_threadpool(
                support_repository.get_latest_support_ticket_for_conversation,
                conversation_id,
                customer_id,
            )
        except DataStoreError as exc:
            raise HTTPException(
                status_code=503,
                detail="Support ticket information is temporarily unavailable.",
            ) from exc
        if ticket is not None:
            result = OrchestratedChatResult(
                answer=(
                    f"Absolutely—you can add details directly to support ticket "
                    f"{ticket.ticket_id}. Write what you’d like the team to know "
                    "in the message box below, then choose “Send to support.” "
                    "Nothing will be sent until you submit it."
                ),
                route=ChatRoute.SUPPORT_TICKET_MESSAGE,
                sources=[],
                actions=[
                    {
                        "type": "support_ticket_message",
                        "ticket_id": ticket.ticket_id,
                    }
                ],
            )
        else:
            result = OrchestratedChatResult(
                answer=(
                    "I can help you send more details, but I couldn’t find a "
                    "support ticket for this conversation. Say “contact support” "
                    "and I’ll help create one first."
                ),
                route=ChatRoute.SUPPORT_TICKET_MESSAGE,
                sources=[],
                actions=[],
            )
    else:
        try:
            if decision == deterministic_decision:
                result = await run_in_threadpool(
                    orchestrator.handle,
                    request.message,
                    customer_id,
                    context_order_id,
                )
            else:
                result = await run_in_threadpool(
                    orchestrator.handle,
                    request.message,
                    customer_id,
                    context_order_id,
                    route_decision=decision,
                )
        except ProviderConfigurationError as exc:
            raise HTTPException(
                status_code=503,
                detail="This support feature is not configured. Please contact support.",
            ) from exc

    actions = list(result.actions)
    answer = result.answer
    support_ticket_created = False
    explicit_escalation = (
        not ticket_follow_up
        and decision.route not in {ChatRoute.OUT_OF_SCOPE, ChatRoute.GREETING}
        and has_any(request.message.casefold(), ESCALATION_WORDS)
    )
    if contains_sensitive_output(answer):
        return _safety_blocked_response(
            conversation_id,
            answer=(
                "I can’t provide credentials, secret keys, access tokens, "
                "or other private system information. I can still help with "
                "store-related questions."
            ),
        )
    needs_human_support = result.needs_human_support or explicit_escalation
    if needs_human_support:
        ticket_id = f"SUP-{uuid4().hex[:12].upper()}"
        ticket_owner_id = customer_id
        if ticket_owner_id is None and request.authorization_token is None:
            raise HTTPException(
                status_code=401,
                detail="Sign in before sending a message to human support.",
            )
        if ticket_owner_id is None:
            ticket_owner_id = demo_authorization_service.resolve_customer(
                request.authorization_token
            )
            if ticket_owner_id is None:
                raise HTTPException(
                    status_code=401,
                    detail="Your session is missing or expired. Please sign in again.",
                )
        ticket_order_match = ORDER_ID_PATTERN.search(request.message)
        ticket_order_id = memory.last_order_id if memory is not None else None
        if ticket_order_match is not None:
            ticket_order_id = ticket_order_match.group(0).upper()
        else:
            answer_order_ids = {
                order_id.upper() for order_id in ORDER_ID_PATTERN.findall(answer)
            }
            if len(answer_order_ids) == 1:
                ticket_order_id = answer_order_ids.pop()
        ticket_context = list(memory.turns) if memory is not None else []
        ticket_created_at = datetime.now(timezone.utc)
        ticket_context.extend(
            [
                ConversationTurn(
                    role="user",
                    text=sanitize_sensitive_text(request.message),
                    created_at=ticket_created_at,
                ),
                ConversationTurn(
                    role="assistant",
                    text=sanitize_sensitive_text(answer),
                    created_at=ticket_created_at,
                ),
            ]
        )
        ticket = SupportTicket(
            ticket_id=ticket_id,
            conversation_id=conversation_id,
            customer_message=sanitize_sensitive_text(request.message),
            customer_id=ticket_owner_id,
            order_id=ticket_order_id,
            issue_summary=sanitize_sensitive_text(request.message),
            conversation_context=ticket_context[-12:],
            created_at=ticket_created_at,
        )
        try:
            await run_in_threadpool(support_repository.append_support_ticket, ticket)
        except DataStoreError as exc:
            raise HTTPException(
                status_code=503,
                detail="A support ticket could not be created. Please contact support directly.",
            ) from exc
        support_ticket_created = True
        answer = (
            f"{answer}\n\nI’ve created support ticket {ticket_id}. To reach a "
            "support agent, send your details using the support form below; "
            "creating the ticket alone does not notify them."
        )
        actions.append(
            {
                "type": "support_ticket",
                "ticket_id": ticket_id,
            }
        )

    if customer_id is not None and request.memory_enabled:
        explicit_order_match = ORDER_ID_PATTERN.search(request.message)
        answered_order_match = ORDER_ID_PATTERN.search(answer)
        last_order_id = (
            explicit_order_match.group(0).upper()
            if explicit_order_match
            else answered_order_match.group(0).upper()
            if answered_order_match
            else context_order_id
        )
        try:
            await run_in_threadpool(
                conversation_memory_service.record_turns,
                conversation_id,
                customer_id,
                request.message,
                answer,
                last_order_id,
                memory,
            )
        except ConversationOwnershipError:
            conversation_id = str(uuid4())
            memory_context_used = False
            try:
                await run_in_threadpool(
                    conversation_memory_service.record_turns,
                    conversation_id,
                    customer_id,
                    request.message,
                    answer,
                    last_order_id,
                    None,
                )
            except DataStoreError as exc:
                raise HTTPException(
                    status_code=503,
                    detail="Conversation context could not be saved.",
                ) from exc
        except DataStoreError as exc:
            raise HTTPException(
                status_code=503,
                detail="Conversation context could not be saved.",
            ) from exc

    response = ChatResponse(
        conversation_id=conversation_id,
        answer=answer,
        route=result.route.value,
        sources=result.sources,
        actions=actions,
        needs_confirmation=result.needs_confirmation,
        needs_human_support=needs_human_support,
        memory=MemoryDiagnostics(
            short_term_used=memory_context_used,
            long_term_record_created=result.long_term_record_created,
        ),
    )
    logger.info(
        "chat_request_completed",
        extra={
            "request_id": getattr(http_request.state, "request_id", None),
            "route": result.route.value,
            "duration_ms": round((perf_counter() - started_at) * 1000),
            "tool_calls": [
                {
                    "name": call.get("name"),
                    "result_status": call.get("result_status"),
                }
                for call in result.actual_tool_calls or []
            ],
            "retrieval_chunk_count": len(result.retrieval_context or []),
            "source_count": len(result.sources),
            "needs_human_support": needs_human_support,
            "support_ticket_created": support_ticket_created,
        },
    )
    return response


@router.post("/chat/history", response_model=ConversationHistoryResponse)
async def load_chat_history(
    request: ConversationHistoryRequest,
) -> ConversationHistoryResponse:
    customer_id = demo_authorization_service.resolve_customer(
        request.authorization_token
    )
    if customer_id is None:
        raise HTTPException(
            status_code=401,
            detail="Your session is missing or expired. Please sign in again.",
        )
    try:
        memory = await run_in_threadpool(
            conversation_memory_service.get,
            request.conversation_id,
            customer_id,
        )
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Conversation history is temporarily unavailable.",
        ) from exc

    turns = list(memory.turns) if memory is not None else []
    first_user_message = (
        memory.first_user_message if memory is not None else None
    )
    if (
        first_user_message is not None
        and all(
            turn.created_at != first_user_message.created_at
            or turn.text != first_user_message.text
            for turn in turns
        )
    ):
        turns.insert(0, first_user_message)
    return ConversationHistoryResponse(
        conversation_id=request.conversation_id,
        turns=turns,
    )


def _safety_blocked_response(
    conversation_id: str,
    answer: str = (
        "I can’t help reveal API keys, passwords, access tokens, hidden "
        "instructions, or private customer information. I can help with "
        "store-related questions instead."
    ),
) -> ChatResponse:
    return ChatResponse(
        conversation_id=conversation_id,
        answer=answer,
        route="safety_blocked",
        sources=[],
        actions=[],
        needs_confirmation=False,
        needs_human_support=False,
        memory=MemoryDiagnostics(
            short_term_used=False,
            long_term_record_created=False,
        ),
    )


def _contextualize_other_order_follow_up(
    message: str,
    turns: list[ConversationTurn],
) -> str:
    if not requests_other_order(message):
        return message

    previous_intent: ChatRoute | None = None
    for turn in reversed(turns):
        if turn.role != "user":
            continue
        candidate = classify_message(turn.text).route
        if candidate in {
            ChatRoute.ORDER,
            ChatRoute.DELIVERY,
            ChatRoute.PAYMENT,
        }:
            previous_intent = candidate
            break
    intent_text = {
        ChatRoute.ORDER: "order status",
        ChatRoute.DELIVERY: "delivery status",
        ChatRoute.PAYMENT: "payment status",
    }.get(previous_intent)
    if intent_text is None:
        return message
    return f"{intent_text} for the other order"
def _configured_intent_classifier():
    global _intent_classifier_initialized, intent_classifier
    if not _intent_classifier_initialized:
        intent_classifier = intent_classifier_from_environment()
        _intent_classifier_initialized = True
    return intent_classifier


@router.post("/support/tickets/{ticket_id}/message")
async def send_ticket_message(
    ticket_id: str,
    request: SupportMessageRequest,
) -> dict[str, str | bool]:
    customer_id = demo_authorization_service.resolve_customer(
        request.authorization_token
    )
    if customer_id is None:
        raise HTTPException(
            status_code=401,
            detail="Your session is missing or expired. Please sign in again.",
        )

    try:
        ticket = await run_in_threadpool(
            support_repository.get_support_ticket,
            ticket_id,
        )
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Support is temporarily unavailable. Please try again.",
        ) from exc
    if ticket is None or ticket.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="Support ticket could not be found.")

    try:
        customer_account = next(
            (
                account
                for account in await run_in_threadpool(
                    support_repository.get_customer_accounts
                )
                if account.customer_id == customer_id
            ),
            None,
        )
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Your account contact details are temporarily unavailable.",
        ) from exc
    if customer_account is None:
        raise HTTPException(
            status_code=503,
            detail="Your account email could not be found. Please contact support.",
        )

    sanitized_message = sanitize_sensitive_text(request.message)
    try:
        await run_in_threadpool(
            send_support_email,
            ticket_id,
            sanitized_message,
            customer_account.email,
        )
    except SupportEmailConfigurationError as exc:
        logger.warning(
            "Support email configuration error for ticket %s: %s",
            ticket_id,
            str(exc),
        )
        raise HTTPException(
            status_code=503,
            detail="Email support is not configured yet. Please try again later.",
        ) from exc
    except smtplib.SMTPAuthenticationError as exc:
        logger.warning("SMTP authentication failed for support ticket %s", ticket_id)
        raise HTTPException(
            status_code=503,
            detail=(
                "The email provider rejected SMTP login. Check the SMTP username "
                "and password, and confirm SMTP authentication or an app password "
                "is enabled for the account."
            ),
        ) from exc
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as exc:
        logger.warning("SMTP rejected sender or recipient for ticket %s", ticket_id)
        raise HTTPException(
            status_code=503,
            detail=(
                "The email provider rejected the sender or recipient. Check that "
                "SUPPORT_EMAIL is valid and SMTP_FROM_EMAIL is allowed by the "
                "authenticated SMTP account."
            ),
        ) from exc
    except (smtplib.SMTPNotSupportedError, smtplib.SMTPConnectError) as exc:
        logger.warning(
            "SMTP TLS or connection negotiation failed for ticket %s (%s)",
            ticket_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "The email provider rejected the SMTP connection or TLS settings. "
                "Check the SMTP host, port, and TLS/SSL mode."
            ),
        ) from exc
    except smtplib.SMTPException as exc:
        logger.warning(
            "SMTP delivery failed for ticket %s (%s)",
            ticket_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="The SMTP server could not accept the message. Check the backend logs and provider settings.",
        ) from exc
    except OSError as exc:
        logger.warning(
            "SMTP network or TLS error for ticket %s (%s)",
            ticket_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "Could not complete the network or TLS connection to the email "
                "provider. Check the SMTP host, port, and TLS/SSL mode."
            ),
        ) from exc

    now = datetime.now(timezone.utc)
    updated_ticket = SupportTicket.model_validate(
        ticket.model_dump()
        | {
            "updated_at": now,
            "messages": [
                *ticket.messages,
                SupportTicketMessage(
                    author_role="customer",
                    author_id=customer_id,
                    text=sanitized_message,
                    created_at=now,
                ),
            ][-200:],
        }
    )
    try:
        await run_in_threadpool(
            support_repository.update_support_ticket,
            updated_ticket,
            ticket.status,
            ticket.updated_at,
        )
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Your message was sent, but the ticket timeline could not be updated.",
        ) from exc

    return {"sent": True, "ticket_id": ticket_id}


@router.get("/tickets", response_model=CustomerTicketListResponse)
async def list_customer_tickets(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> CustomerTicketListResponse:
    customer_id = _require_customer(authorization)
    try:
        tickets = await run_in_threadpool(support_repository.get_support_tickets)
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Support tickets are temporarily unavailable.",
        ) from exc

    customer_tickets = sorted(
        (ticket for ticket in tickets if ticket.customer_id == customer_id),
        key=lambda ticket: ticket.created_at,
        reverse=True,
    )
    return CustomerTicketListResponse(
        tickets=[_customer_ticket_summary(ticket) for ticket in customer_tickets]
    )


@router.get("/tickets/{ticket_id}", response_model=CustomerTicketDetail)
async def get_customer_ticket(
    ticket_id: TicketId,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> CustomerTicketDetail:
    customer_id = _require_customer(authorization)
    try:
        ticket = await run_in_threadpool(
            support_repository.get_support_ticket,
            ticket_id,
        )
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Support tickets are temporarily unavailable.",
        ) from exc
    if ticket is None or ticket.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="Support ticket could not be found.")

    messages = ticket.conversation_context or [
        ConversationTurn(
            role="user",
            text=ticket.customer_message,
            created_at=ticket.created_at,
        )
    ]
    customer_messages = [
        CustomerTicketMessage(
            role="user" if message.author_role == "customer" else "assistant",
            text=message.text,
            created_at=message.created_at,
        )
        for message in ticket.messages
    ]
    ticket_messages = [
        CustomerTicketMessage(
            role=turn.role,
            text=turn.text,
            created_at=turn.created_at,
        )
        for turn in messages
    ]
    merged_messages = sorted(
        [*ticket_messages, *customer_messages],
        key=lambda message: message.created_at,
    )
    updated_at = max(
        [ticket.created_at]
        + [change.changed_at for change in ticket.status_history]
        + ([ticket.updated_at] if ticket.updated_at else [])
        + ([ticket.customer_update.created_at] if ticket.customer_update else [])
        + [message.created_at for message in ticket.messages]
    )
    return CustomerTicketDetail(
        ticket_id=ticket.ticket_id,
        subject=ticket.issue_summary or ticket.customer_message,
        status=ticket.status,
        created_at=ticket.created_at,
        updated_at=updated_at,
        description=ticket.customer_message,
        messages=merged_messages,
        status_history=[
            CustomerTicketStatusEvent(
                previous_status=change.previous_status,
                status=change.status,
                changed_at=change.changed_at,
            )
            for change in ticket.status_history
        ],
        customer_update=ticket.customer_update,
    )


@router.patch(
    "/support/tickets/{ticket_id}/status",
    response_model=SupportTicketStatusResponse,
)
async def update_support_ticket_status(
    ticket_id: str,
    request: SupportTicketStatusRequest,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> SupportTicketStatusResponse:
    staff_id = _require_support_agent(authorization)

    try:
        ticket, changed = await run_in_threadpool(
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
    latest_change = ticket.status_history[-1] if ticket.status_history else None
    return SupportTicketStatusResponse(
        ticket_id=ticket.ticket_id,
        status=ticket.status,
        changed=changed,
        changed_at=latest_change.changed_at if changed else None,
        changed_by=latest_change.changed_by if changed else None,
    )


@router.get(
    "/support/tickets/{ticket_id}",
    response_model=SupportTicketDetailResponse,
)
async def get_support_ticket_details(
    ticket_id: str,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> SupportTicketDetailResponse:
    _require_support_agent(authorization)
    try:
        ticket = await run_in_threadpool(
            support_repository.get_support_ticket,
            ticket_id,
        )
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Support tickets are temporarily unavailable.",
        ) from exc
    if ticket is None:
        raise HTTPException(status_code=404, detail="Support ticket could not be found.")
    return SupportTicketDetailResponse(
        ticket_id=ticket.ticket_id,
        conversation_id=ticket.conversation_id,
        customer_id=ticket.customer_id,
        order_id=ticket.order_id,
        customer_message=ticket.customer_message,
        issue_summary=ticket.issue_summary,
        conversation_context=ticket.conversation_context,
        status=ticket.status,
        status_history=ticket.status_history,
        customer_update=ticket.customer_update,
        created_at=ticket.created_at,
    )


@router.get(
    "/support/tickets/{ticket_id}/status",
    response_model=CustomerSupportTicketStatusResponse,
)
async def get_customer_support_ticket_status(
    ticket_id: str,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> CustomerSupportTicketStatusResponse:
    customer_token = _bearer_token(authorization)
    if customer_token is None:
        raise HTTPException(
            status_code=401,
            detail="Sign in as the customer who opened this ticket to view its status.",
        )
    customer_id = demo_authorization_service.resolve_customer(customer_token)
    if customer_id is None:
        raise HTTPException(
            status_code=401,
            detail="Your customer session is missing or expired. Please sign in again.",
        )
    try:
        ticket = await run_in_threadpool(
            support_repository.get_support_ticket,
            ticket_id,
        )
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Support tickets are temporarily unavailable.",
        ) from exc
    if ticket is None or ticket.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="Support ticket could not be found.")
    customer_message = (
        ticket.customer_update.message
        if ticket.customer_update is not None
        and ticket.customer_update.status == ticket.status
        else None
    )
    return CustomerSupportTicketStatusResponse(
        ticket_id=ticket.ticket_id,
        status=ticket.status,
        customer_message=customer_message,
    )


def _require_support_agent(authorization: str | None) -> str:
    staff_token = _bearer_token(authorization)
    if staff_token is None:
        raise HTTPException(
            status_code=401,
            detail="Sign in as a support agent to access tickets.",
        )
    staff_id = demo_authorization_service.resolve_support_agent(staff_token)
    if staff_id is None:
        raise HTTPException(
            status_code=401,
            detail="Your support-agent session is missing or expired. Please sign in again.",
        )
    return staff_id


def _require_customer(authorization: str | None) -> str:
    customer_token = _bearer_token(authorization)
    if customer_token is None:
        raise HTTPException(
            status_code=401,
            detail="Sign in as the customer who opened these tickets.",
        )
    customer_id = demo_authorization_service.resolve_customer(customer_token)
    if customer_id is None:
        raise HTTPException(
            status_code=401,
            detail="Your customer session is missing or expired. Please sign in again.",
        )
    return customer_id


def _customer_status_label(status: SupportTicketStatus) -> str:
    return {
        "open": "Open",
        "investigating": "In Progress",
        "waiting_for_customer": "Pending Customer",
        "escalated": "In Progress",
        "resolved": "Resolved",
        "closed": "Closed",
    }[status]


def _customer_ticket_summary(ticket: SupportTicket) -> CustomerTicketSummary:
    updated_at = max(
        [ticket.created_at]
        + [change.changed_at for change in ticket.status_history]
        + ([ticket.updated_at] if ticket.updated_at else [])
        + ([ticket.customer_update.created_at] if ticket.customer_update else [])
        + [message.created_at for message in ticket.messages]
    )
    return CustomerTicketSummary(
        ticket_id=ticket.ticket_id,
        subject=ticket.issue_summary or ticket.customer_message,
        status=ticket.status,
        created_at=ticket.created_at,
        updated_at=updated_at,
    )


def _bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        return None
    return token.strip()

import logging
import smtplib
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.agent.router import (
    ChatRoute,
    ESCALATION_WORDS,
    ORDER_ID_PATTERN,
    build_default_orchestrator,
    classify_message,
    has_any,
    requests_order_search,
)
from app.rag.providers import ProviderConfigurationError
from app.services.conversation_memory import (
    ConversationMemoryService,
    sanitize_sensitive_text,
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
from app.agent.tools import repository as support_repository
from app.storage.json_store import ConversationOwnershipError, DataStoreError
from app.storage.models import SupportTicket

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)
orchestrator = build_default_orchestrator()
conversation_memory_service = ConversationMemoryService(support_repository)

MessageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
ConversationId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


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
async def chat(request: ChatRequest) -> ChatResponse:
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
    if decision.route in {
        ChatRoute.ORDER,
        ChatRoute.DELIVERY,
        ChatRoute.PAYMENT,
        ChatRoute.CANCELLATION,
        ChatRoute.BILLING_ISSUE,
    }:
        if request.authorization_token is None:
            raise HTTPException(
                status_code=401,
                detail="Sign in before asking about your orders.",
            )
        customer_id = demo_authorization_service.resolve_customer(
            request.authorization_token
        )
        if customer_id is None:
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

    context_order_id = memory.last_order_id if memory is not None else None
    memory_context_used = (
        request.memory_enabled
        and customer_id is not None
        and context_order_id is not None
        and decision.route
        in {
            ChatRoute.ORDER,
            ChatRoute.DELIVERY,
            ChatRoute.PAYMENT,
            ChatRoute.CANCELLATION,
            ChatRoute.BILLING_ISSUE,
        }
        and decision.order_id is None
        and not requests_order_search(request.message)
    )
    try:
        result = await run_in_threadpool(
            orchestrator.handle,
            request.message,
            customer_id,
            context_order_id,
        )
    except ProviderConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail="This support feature is not configured. Please contact support.",
        ) from exc

    actions = list(result.actions)
    answer = result.answer
    explicit_escalation = (
        decision.route not in {ChatRoute.OUT_OF_SCOPE, ChatRoute.GREETING}
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
        ticket = SupportTicket(
            ticket_id=ticket_id,
            conversation_id=conversation_id,
            customer_message=sanitize_sensitive_text(request.message),
            customer_id=ticket_owner_id,
            created_at=datetime.now(timezone.utc),
        )
        try:
            await run_in_threadpool(support_repository.append_support_ticket, ticket)
        except DataStoreError as exc:
            raise HTTPException(
                status_code=503,
                detail="A support ticket could not be created. Please contact support directly.",
            ) from exc
        answer = f"{answer}\n\nI’ve created support ticket {ticket_id} for follow-up."
        actions.append(
            {
                "type": "support_ticket",
                "ticket_id": ticket_id,
            }
        )

    if customer_id is not None and request.memory_enabled:
        explicit_order_match = ORDER_ID_PATTERN.search(request.message)
        last_order_id = (
            explicit_order_match.group(0).upper()
            if explicit_order_match
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

    return ChatResponse(
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

    return {"sent": True, "ticket_id": ticket_id}

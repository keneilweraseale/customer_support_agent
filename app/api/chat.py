from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.agent.router import (
    ChatRoute,
    ORDER_ID_PATTERN,
    build_default_orchestrator,
    classify_message,
)
from app.rag.providers import ProviderConfigurationError
from app.services.conversation_memory import ConversationMemoryService
from app.services.demo_authorization import demo_authorization_service
from app.agent.tools import repository as support_repository
from app.storage.json_store import ConversationOwnershipError, DataStoreError

router = APIRouter(prefix="/api", tags=["chat"])
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


class MemoryDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    short_term_used: bool
    long_term_record_created: bool


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    route: str
    sources: list[dict[str, str]]
    actions: list[dict[str, str]]
    needs_confirmation: bool = False
    memory: MemoryDiagnostics


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    decision = classify_message(request.message)
    conversation_id = request.conversation_id or str(uuid4())
    customer_id = None
    if decision.route in {
        ChatRoute.ORDER,
        ChatRoute.DELIVERY,
        ChatRoute.PAYMENT,
        ChatRoute.CANCELLATION,
    }:
        if request.authorization_token is None:
            raise HTTPException(
                status_code=401,
                detail="Demo verification is required for order-related requests.",
            )
        customer_id = demo_authorization_service.resolve_customer(
            request.authorization_token
        )
        if customer_id is None:
            raise HTTPException(
                status_code=401,
                detail="Demo verification is missing or expired.",
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
        }
        and decision.order_id is None
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
                result.answer,
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
                    result.answer,
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
        answer=result.answer,
        route=result.route.value,
        sources=result.sources,
        actions=result.actions,
        needs_confirmation=result.needs_confirmation,
        memory=MemoryDiagnostics(
            short_term_used=memory_context_used,
            long_term_record_created=result.long_term_record_created,
        ),
    )

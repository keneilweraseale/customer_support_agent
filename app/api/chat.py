from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.agent.router import (
    ChatRoute,
    build_default_orchestrator,
    classify_message,
)
from app.rag.providers import ProviderConfigurationError
from app.services.demo_authorization import demo_authorization_service

router = APIRouter(prefix="/api", tags=["chat"])
orchestrator = build_default_orchestrator()

MessageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
ConversationId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: MessageText
    conversation_id: ConversationId | None = None
    authorization_token: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=40,
            max_length=128,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ] | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    route: str
    sources: list[dict[str, str]]
    actions: list[dict[str, str]]
    needs_confirmation: bool = False


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    decision = classify_message(request.message)
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

    try:
        result = await run_in_threadpool(
            orchestrator.handle,
            request.message,
            customer_id,
        )
    except ProviderConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail="This support feature is not configured. Please contact support.",
        ) from exc

    return ChatResponse(
        conversation_id=request.conversation_id or str(uuid4()),
        answer=result.answer,
        route=result.route.value,
        sources=result.sources,
        actions=result.actions,
        needs_confirmation=result.needs_confirmation,
    )

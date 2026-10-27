import logging
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Path, Request
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator
from starlette.concurrency import run_in_threadpool

from app.agent.tools import cancellation_service, cancel_order_tool
from app.services.demo_authorization import demo_authorization_service
from app.storage.json_store import CancellationConsistencyError, DataStoreError
from app.storage.models import (
    CancellationReasonCode,
    CancellationReasonText,
    validate_cancellation_reason,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orders", tags=["orders"])

OrderId = Annotated[str, Path(pattern=r"^ORD-[A-Z0-9_-]{1,32}$")]
OpaqueToken = Annotated[
    str,
    StringConstraints(
        min_length=40,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]


class CancellationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorization_token: OpaqueToken
    confirmation_token: OpaqueToken
    reason_code: CancellationReasonCode = "not_provided"
    reason_text: CancellationReasonText | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> "CancellationRequest":
        validate_cancellation_reason(self.reason_code, self.reason_text)
        return self


class CancellationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorization_token: OpaqueToken
    confirmation_token: OpaqueToken
    outcome: Literal["declined", "withdrawn"]
    reason_code: CancellationReasonCode = "not_provided"
    reason_text: CancellationReasonText | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> "CancellationDecisionRequest":
        validate_cancellation_reason(self.reason_code, self.reason_text)
        return self


class CancellationResponse(BaseModel):
    order_id: str
    cancelled: bool
    message: str


class CancellationDecisionResponse(BaseModel):
    order_id: str
    outcome: Literal["declined", "withdrawn"]
    recorded: bool


@router.post("/{order_id}/cancel", response_model=CancellationResponse)
async def confirm_order_cancellation(
    order_id: OrderId,
    request: CancellationRequest,
    http_request: Request,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=16,
            max_length=64,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ],
) -> CancellationResponse:
    customer_id = demo_authorization_service.resolve_customer(
        request.authorization_token
    )
    if customer_id is None:
        raise HTTPException(
            status_code=401,
            detail="Your session is missing or expired. Please sign in again.",
        )

    try:
        result = await run_in_threadpool(
            cancel_order_tool.invoke,
            {
                "order_id": order_id,
                "customer_id": customer_id,
                "confirmation_token": request.confirmation_token,
                "idempotency_key": idempotency_key,
                "reason_code": request.reason_code,
                "reason_text": request.reason_text,
            },
        )
    except CancellationConsistencyError as exc:
        logger.error(
            "Order and cancellation history may be inconsistent",
            extra={
                "action": "cancel_order",
                "order_id": order_id,
                "outcome": "consistency_error",
                "event_timestamp": datetime.now(timezone.utc).isoformat(),
                "request_id": http_request.state.request_id,
                "actor_id": customer_id,
            },
        )
        raise HTTPException(
            status_code=503,
            detail="Cancellation outcome could not be verified. Please contact support before retrying.",
        ) from exc
    except (DataStoreError, ToolException) as exc:
        logger.warning(
            "Order cancellation service unavailable",
            extra={
                "action": "cancel_order",
                "order_id": order_id,
                "outcome": "unavailable",
                "event_timestamp": datetime.now(timezone.utc).isoformat(),
                "request_id": http_request.state.request_id,
                "actor_id": customer_id,
            },
        )
        raise HTTPException(
            status_code=503,
            detail="Cancellation is temporarily unavailable. No change was made.",
        ) from exc
    if result.get("cancelled") is not True:
        logger.info(
            "Order cancellation was not completed",
            extra={
                "actor_id": customer_id,
                "action": "cancel_order",
                "order_id": order_id,
                "outcome": "rejected",
                "event_timestamp": datetime.now(timezone.utc).isoformat(),
                "request_id": http_request.state.request_id,
            },
        )
        raise HTTPException(
            status_code=409,
            detail="Cancellation could not be confirmed. It may have expired or the order may no longer be eligible.",
        )
    logger.info(
        "Order cancellation completed",
        extra={
            "actor_id": customer_id,
            "action": "cancel_order",
            "order_id": order_id,
            "outcome": "success",
            "event_timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": http_request.state.request_id,
        },
    )
    return CancellationResponse(
        order_id=order_id,
        cancelled=True,
        message="The order was cancelled.",
    )


@router.post(
    "/{order_id}/cancel/decision",
    response_model=CancellationDecisionResponse,
)
async def record_cancellation_decision(
    order_id: OrderId,
    request: CancellationDecisionRequest,
    http_request: Request,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=16,
            max_length=64,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ],
) -> CancellationDecisionResponse:
    customer_id = demo_authorization_service.resolve_customer(
        request.authorization_token
    )
    if customer_id is None:
        raise HTTPException(
            status_code=401,
            detail="Your session is missing or expired. Please sign in again.",
        )

    try:
        result = await run_in_threadpool(
            cancellation_service.record_cancellation_decision,
            order_id,
            customer_id,
            request.confirmation_token,
            request.outcome,
            request.reason_code,
            request.reason_text,
            idempotency_key,
        )
    except DataStoreError as exc:
        logger.warning(
            "Cancellation decision could not be recorded",
            extra={
                "action": "record_cancellation_decision",
                "order_id": order_id,
                "outcome": "unavailable",
                "event_timestamp": datetime.now(timezone.utc).isoformat(),
                "request_id": http_request.state.request_id,
                "actor_id": customer_id,
            },
        )
        raise HTTPException(
            status_code=503,
            detail="The cancellation decision could not be recorded.",
        ) from exc
    if result.get("recorded") is not True:
        raise HTTPException(
            status_code=409,
            detail="Cancellation decision could not be confirmed. It may have expired.",
        )
    return CancellationDecisionResponse(
        order_id=order_id,
        outcome=request.outcome,
        recorded=True,
    )

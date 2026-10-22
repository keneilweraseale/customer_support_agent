import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Path, Request
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.agent.tools import cancel_order_tool
from app.services.demo_authorization import demo_authorization_service
from app.storage.json_store import DataStoreError

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


class CancellationResponse(BaseModel):
    order_id: str
    cancelled: bool
    message: str


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
            detail="Demo verification is missing or expired.",
        )

    try:
        result = await run_in_threadpool(
            cancel_order_tool.invoke,
            {
                "order_id": order_id,
                "customer_id": customer_id,
                "confirmation_token": request.confirmation_token,
                "idempotency_key": idempotency_key,
            },
        )
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

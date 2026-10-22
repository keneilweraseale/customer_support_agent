from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints

from app.services.demo_authorization import (
    DemoAuthorizationError,
    demo_authorization_service,
)
from app.storage.json_store import DataStoreError

router = APIRouter(prefix="/api/demo", tags=["demo authorization"])

DemoCustomerId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=12,
        max_length=12,
        pattern=r"^CUS-DEMO-\d{3}$",
    ),
]


class DemoVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: DemoCustomerId


class DemoVerificationResponse(BaseModel):
    authorization_token: str
    expires_at: datetime
    demo_only: bool = True


@router.post("/verify", response_model=DemoVerificationResponse)
async def verify_demo_customer(
    request: DemoVerificationRequest,
) -> DemoVerificationResponse:
    try:
        token, expires_at = demo_authorization_service.issue_token(request.customer_id)
    except DemoAuthorizationError as exc:
        raise HTTPException(
            status_code=404,
            detail="Unknown demo customer identity.",
        ) from exc
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Demo verification is temporarily unavailable.",
        ) from exc

    return DemoVerificationResponse(
        authorization_token=token,
        expires_at=expires_at,
    )

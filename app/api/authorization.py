from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from app.services.demo_authorization import (
    DemoAuthorizationError,
    demo_authorization_service,
)
from app.storage.json_store import DataStoreError

router = APIRouter(prefix="/api/auth", tags=["authorization"])

EmailAddress = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
Password = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailAddress
    password: Password

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.casefold()


class LoginResponse(BaseModel):
    authorization_token: str
    expires_at: datetime


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    try:
        token, expires_at = demo_authorization_service.authenticate(
            request.email,
            request.password,
        )
    except DemoAuthorizationError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password.",
        ) from exc
    except DataStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Login is temporarily unavailable.",
        ) from exc

    return LoginResponse(authorization_token=token, expires_at=expires_at)

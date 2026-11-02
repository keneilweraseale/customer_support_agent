import base64
import binascii
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.services.demo_authorization import demo_authorization_service
from app.storage.factory import repository_from_environment
from app.storage.json_store import (
    DamageReportConflictError,
    DataStoreError,
)
from app.storage.models import DamageReport

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/damage-reports", tags=["damage reports"])
damage_repository = repository_from_environment()
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_DATA_LENGTH = 4 * ((MAX_IMAGE_BYTES + 2) // 3) + 32
DATA_URL_PATTERN = re.compile(r"^data:(image/jpeg|image/png);base64,([A-Za-z0-9+/=]+)$")
IMAGE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff", "jpg"),
    "image/png": (b"\x89PNG\r\n\x1a\n", "png"),
}

OpaqueToken = Annotated[
    str,
    StringConstraints(min_length=40, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
]
OrderReference = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^ORD-[A-Z0-9_-]{1,32}$",
    ),
]


class DamageReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorization_token: OpaqueToken
    order_id: OrderReference
    image_data: Annotated[
        str,
        StringConstraints(min_length=32, max_length=MAX_IMAGE_DATA_LENGTH),
    ]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


class DamageReportResponse(BaseModel):
    report_id: str
    order_id: str
    created: bool
    message: str
    created_at: datetime


@router.post("", response_model=DamageReportResponse, status_code=201)
async def submit_damage_report(
    payload: DamageReportRequest,
    request: Request,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=16,
            max_length=64,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ],
) -> DamageReportResponse:
    customer_id = demo_authorization_service.resolve_customer(
        payload.authorization_token
    )
    if customer_id is None:
        raise HTTPException(
            status_code=401,
            detail="Your session is missing or expired. Please sign in again.",
        )

    order = None
    try:
        order = await run_in_threadpool(damage_repository.get_order, payload.order_id)
    except DataStoreError as exc:
        logger.warning(
            "Damage report order lookup failed",
            extra={"action": "submit_damage_report", "outcome": "storage_error"},
        )
        raise HTTPException(
            status_code=503,
            detail="Damage reporting is temporarily unavailable.",
        ) from exc
    if order is None or order.customer_id != customer_id:
        raise HTTPException(
            status_code=404,
            detail="That order could not be found in your account.",
        )

    match = DATA_URL_PATTERN.fullmatch(payload.image_data)
    if match is None:
        raise HTTPException(
            status_code=422,
            detail="Provide a valid camera-captured JPEG or PNG image.",
        )
    mime_type, encoded_image = match.groups()
    try:
        image_bytes = base64.b64decode(encoded_image, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="The captured image data is invalid.",
        ) from exc
    if not image_bytes:
        raise HTTPException(status_code=422, detail="The captured image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The captured image must be no larger than 5 MB.",
        )
    signature, extension = IMAGE_SIGNATURES[mime_type]
    complete_signature = (
        image_bytes.endswith(b"\xff\xd9")
        if mime_type == "image/jpeg"
        else image_bytes.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
    )
    if not image_bytes.startswith(signature) or not complete_signature:
        raise HTTPException(
            status_code=415,
            detail="The captured image format does not match its content.",
        )

    report_id = str(uuid4())
    report = DamageReport(
        report_id=report_id,
        idempotency_key=idempotency_key,
        request_fingerprint=hashlib.sha256(
            b"\0".join(
                (
                    payload.order_id.encode("utf-8"),
                    (payload.description or "").encode("utf-8"),
                    image_bytes,
                )
            )
        ).hexdigest(),
        customer_id=customer_id,
        order_id=payload.order_id,
        description=payload.description or None,
        image_filename=f"{report_id}.{extension}",
        created_at=datetime.now(timezone.utc),
    )

    try:
        saved_report, created = await run_in_threadpool(
            damage_repository.create_damage_report,
            report,
            image_bytes,
        )
    except DamageReportConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="This submission key was already used for a different report.",
        ) from exc
    except DataStoreError as exc:
        logger.error(
            "Damage report could not be persisted",
            extra={
                "action": "submit_damage_report",
                "order_id": payload.order_id,
                "outcome": "storage_error",
                "request_id": request.state.request_id,
                "actor_id": customer_id,
            },
        )
        raise HTTPException(
            status_code=503,
            detail="Your damage report could not be saved. Please try again.",
        ) from exc

    logger.info(
        "Damage report submission completed",
        extra={
            "action": "submit_damage_report",
            "report_id": saved_report.report_id,
            "order_id": saved_report.order_id,
            "outcome": "created" if created else "duplicate",
            "request_id": request.state.request_id,
            "actor_id": customer_id,
        },
    )
    return DamageReportResponse(
        report_id=saved_report.report_id,
        order_id=saved_report.order_id,
        created=created,
        message=(
            "Your damage report was submitted for review."
            if created
            else "This damage report was already received."
        ),
        created_at=saved_report.created_at,
    )

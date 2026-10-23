import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from app.storage.repository import SupportRepository
from app.storage.models import CancellationEvent, CancellationReasonCode

MAX_ACTIVE_CONFIRMATIONS_PER_ORDER = 5


@dataclass(frozen=True)
class PendingCancellation:
    order_id: str
    customer_id: str
    order_updated_at: datetime
    expires_at: datetime
    event: CancellationEvent


class CancellationService:
    def __init__(
        self,
        repository: SupportRepository,
        token_lifetime: timedelta = timedelta(minutes=5),
    ) -> None:
        self._repository = repository
        self._token_lifetime = token_lifetime
        self._confirmations: dict[str, PendingCancellation] = {}
        self._completed_requests: dict[
            str,
            tuple[str, str, str, datetime, dict[str, object]],
        ] = {}
        self._lock = RLock()

    def check_eligibility(
        self,
        order_id: str,
        customer_id: str,
        reason_code: CancellationReasonCode = "not_provided",
        reason_text: str | None = None,
    ) -> dict[str, object]:
        self._repository.expire_old_cancellation_events()
        order = self._repository.get_order(order_id)
        if order is None or order.customer_id != customer_id:
            return {
                "found": False,
                "order_id": order_id,
                "eligible": False,
                "message": "Order not found.",
                "needs_confirmation": False,
            }

        eligible = order.cancellation_allowed and order.order_status == "processing"
        result: dict[str, object] = {
            "found": True,
            "order_id": order.order_id,
            "eligible": eligible,
            "message": (
                "This order is eligible for cancellation. Please confirm before it is cancelled."
                if eligible
                else "This order is not eligible for cancellation."
            ),
            "needs_confirmation": eligible,
        }
        if eligible:
            now = datetime.now(timezone.utc)
            with self._lock:
                self._discard_expired(now)
                order_tokens = sorted(
                    (
                        (pending.expires_at, token)
                        for token, pending in self._confirmations.items()
                        if (pending.order_id, pending.customer_id)
                        == (order.order_id, customer_id)
                    ),
                    key=lambda item: item[0],
                )
                while len(order_tokens) >= MAX_ACTIVE_CONFIRMATIONS_PER_ORDER:
                    _, expired_token = order_tokens.pop(0)
                    expired_pending = self._confirmations[expired_token]
                    self._repository.update_cancellation_event(
                        self._updated_event(
                            expired_pending.event,
                            outcome="withdrawn",
                            outcome_at=now,
                            actor="system",
                        )
                    )
                    del self._confirmations[expired_token]
                event = self._new_event(
                    order.order_id,
                    customer_id,
                    reason_code,
                    reason_text,
                    now,
                    eligibility_result="eligible",
                    outcome="pending_confirmation",
                    actor="system",
                )
                self._repository.append_cancellation_event(event)
                token = secrets.token_urlsafe(32)
                self._confirmations[token] = PendingCancellation(
                    order.order_id,
                    customer_id,
                    order.updated_at,
                    now + self._token_lifetime,
                    event,
                )
            result["confirmation_token"] = token
            result["expires_at"] = (now + self._token_lifetime).isoformat()
        else:
            now = datetime.now(timezone.utc)
            self._repository.append_cancellation_event(
                self._new_event(
                    order.order_id,
                    customer_id,
                    reason_code,
                    reason_text,
                    now,
                    eligibility_result="ineligible",
                    outcome="ineligible",
                    outcome_at=now,
                    actor="system",
                )
            )
        return result

    def confirm_cancellation(
        self,
        order_id: str,
        customer_id: str,
        confirmation_token: str,
        idempotency_key: str | None = None,
        reason_code: CancellationReasonCode = "not_provided",
        reason_text: str | None = None,
    ) -> dict[str, object]:
        with self._lock:
            now = datetime.now(timezone.utc)
            self._discard_expired(now)
            self._discard_expired_requests(now)
            token_digest = self._request_digest(
                confirmation_token,
                "confirmed",
                reason_code,
                reason_text,
            )
            if idempotency_key is not None:
                completed = self._completed_requests.get(idempotency_key)
                if completed is not None:
                    if completed[:3] == (order_id, customer_id, token_digest):
                        return dict(completed[4])
                    return {
                        "cancelled": False,
                        "order_id": order_id,
                        "message": "Cancellation confirmation is invalid or expired.",
                    }

            confirmation = self._confirmations.get(confirmation_token)
            if (
                confirmation is None
                or (confirmation.order_id, confirmation.customer_id)
                != (order_id, customer_id)
            ):
                return {
                    "cancelled": False,
                    "order_id": order_id,
                    "message": "Cancellation confirmation is invalid or expired.",
                }

            expected_updated_at = confirmation.order_updated_at
            cancelled_event = self._updated_event(
                confirmation.event,
                reason_code=reason_code,
                reason_text=reason_text,
                outcome="cancelled",
                outcome_at=now,
                actor="customer_confirmed",
            )
            updated_order = self._repository.cancel_order_if_eligible(
                order_id,
                customer_id,
                now,
                expected_updated_at,
                cancelled_event,
            )
            if updated_order is None:
                ineligible_event = self._updated_event(
                    confirmation.event,
                    reason_code=reason_code,
                    reason_text=reason_text,
                    eligibility_result="ineligible",
                    outcome="ineligible",
                    outcome_at=now,
                    actor="system",
                )
                self._repository.update_cancellation_event(ineligible_event)
                result = {
                    "cancelled": False,
                    "order_id": order_id,
                    "message": "This order is no longer eligible for cancellation.",
                }
            else:
                result = {
                    "cancelled": True,
                    "order_id": updated_order.order_id,
                    "order_status": updated_order.order_status,
                    "message": "The order was cancelled.",
                }
            del self._confirmations[confirmation_token]
            if idempotency_key is not None:
                self._completed_requests[idempotency_key] = (
                    order_id,
                    customer_id,
                    token_digest,
                    now + self._token_lifetime,
                    result,
                )
                if len(self._completed_requests) > 1000:
                    oldest_key = min(
                        self._completed_requests,
                        key=lambda key: self._completed_requests[key][3],
                    )
                    del self._completed_requests[oldest_key]
            return result

    def record_cancellation_decision(
        self,
        order_id: str,
        customer_id: str,
        confirmation_token: str,
        outcome: str,
        reason_code: CancellationReasonCode = "not_provided",
        reason_text: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        if outcome not in {"declined", "withdrawn"}:
            raise ValueError("Cancellation decision must be declined or withdrawn.")
        with self._lock:
            now = datetime.now(timezone.utc)
            self._discard_expired(now)
            self._discard_expired_requests(now)
            token_digest = self._request_digest(
                confirmation_token,
                outcome,
                reason_code,
                reason_text,
            )
            if idempotency_key is not None:
                completed = self._completed_requests.get(idempotency_key)
                if completed is not None:
                    if completed[:3] == (order_id, customer_id, token_digest):
                        return dict(completed[4])
                    return {
                        "recorded": False,
                        "order_id": order_id,
                        "message": "Cancellation confirmation is invalid or expired.",
                    }
            confirmation = self._confirmations.get(confirmation_token)
            if (
                confirmation is None
                or (confirmation.order_id, confirmation.customer_id)
                != (order_id, customer_id)
            ):
                return {
                    "recorded": False,
                    "order_id": order_id,
                    "message": "Cancellation confirmation is invalid or expired.",
                }

            event = self._updated_event(
                confirmation.event,
                reason_code=reason_code,
                reason_text=reason_text,
                outcome=outcome,
                outcome_at=now,
                actor=(
                    "customer_declined"
                    if outcome == "declined"
                    else "customer_withdrew"
                ),
            )
            self._repository.update_cancellation_event(event)
            del self._confirmations[confirmation_token]
            result = {
                "recorded": True,
                "order_id": order_id,
                "outcome": outcome,
            }
            if idempotency_key is not None:
                self._completed_requests[idempotency_key] = (
                    order_id,
                    customer_id,
                    token_digest,
                    now + self._token_lifetime,
                    result,
                )
            return result

    def _discard_expired(self, now: datetime) -> None:
        expired_tokens = [
            token
            for token, pending in self._confirmations.items()
            if pending.expires_at <= now
        ]
        for token in expired_tokens:
            pending = self._confirmations[token]
            self._repository.update_cancellation_event(
                self._updated_event(
                    pending.event,
                    outcome="withdrawn",
                    outcome_at=now,
                    actor="system",
                )
            )
            del self._confirmations[token]

    def _discard_expired_requests(self, now: datetime) -> None:
        expired_keys = [
            key
            for key, (_, _, _, expires_at, _) in self._completed_requests.items()
            if expires_at <= now
        ]
        for key in expired_keys:
            del self._completed_requests[key]

    @staticmethod
    def _new_event(
        order_id: str,
        customer_id: str,
        reason_code: CancellationReasonCode,
        reason_text: str | None,
        requested_at: datetime,
        *,
        eligibility_result: str,
        outcome: str,
        actor: str,
        outcome_at: datetime | None = None,
    ) -> CancellationEvent:
        return CancellationEvent(
            event_id=f"CAN-EVT-{uuid4().hex}",
            request_id=str(uuid4()),
            order_id=order_id,
            customer_id=customer_id,
            reason_code=reason_code,
            reason_text=reason_text,
            requested_at=requested_at,
            eligibility_result=eligibility_result,
            outcome=outcome,
            outcome_at=outcome_at,
            actor=actor,
        )

    @staticmethod
    def _updated_event(
        event: CancellationEvent,
        *,
        reason_code: CancellationReasonCode | None = None,
        reason_text: str | None = None,
        eligibility_result: str | None = None,
        outcome: str,
        outcome_at: datetime,
        actor: str,
    ) -> CancellationEvent:
        return CancellationEvent.model_validate(
            event.model_dump()
            | {
                "reason_code": reason_code or event.reason_code,
                "reason_text": reason_text,
                "eligibility_result": eligibility_result
                or event.eligibility_result,
                "outcome": outcome,
                "outcome_at": outcome_at,
                "actor": actor,
            }
        )

    @staticmethod
    def _request_digest(
        confirmation_token: str,
        action: str,
        reason_code: CancellationReasonCode,
        reason_text: str | None,
    ) -> str:
        return hashlib.sha256(
            (
                f"{confirmation_token}\0{action}\0{reason_code}\0"
                f"{reason_text or ''}"
            ).encode()
        ).hexdigest()

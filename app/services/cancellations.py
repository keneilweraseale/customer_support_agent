import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from threading import RLock

from app.storage.repository import SupportRepository

MAX_ACTIVE_CONFIRMATIONS_PER_ORDER = 5


class CancellationService:
    def __init__(
        self,
        repository: SupportRepository,
        token_lifetime: timedelta = timedelta(minutes=5),
    ) -> None:
        self._repository = repository
        self._token_lifetime = token_lifetime
        self._confirmations: dict[str, tuple[str, str, datetime, datetime]] = {}
        self._completed_requests: dict[
            str,
            tuple[str, str, str, datetime, dict[str, object]],
        ] = {}
        self._lock = RLock()

    def check_eligibility(self, order_id: str, customer_id: str) -> dict[str, object]:
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
                        (expires_at, token)
                        for token, (
                            existing_order,
                            existing_customer,
                            _,
                            expires_at,
                        ) in self._confirmations.items()
                        if (existing_order, existing_customer)
                        == (order.order_id, customer_id)
                    ),
                    key=lambda item: item[0],
                )
                while len(order_tokens) >= MAX_ACTIVE_CONFIRMATIONS_PER_ORDER:
                    _, expired_token = order_tokens.pop(0)
                    del self._confirmations[expired_token]
                token = secrets.token_urlsafe(32)
                self._confirmations[token] = (
                    order.order_id,
                    customer_id,
                    order.updated_at,
                    now + self._token_lifetime,
                )
            result["confirmation_token"] = token
            result["expires_at"] = (now + self._token_lifetime).isoformat()
        return result

    def confirm_cancellation(
        self,
        order_id: str,
        customer_id: str,
        confirmation_token: str,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        with self._lock:
            now = datetime.now(timezone.utc)
            self._discard_expired(now)
            self._discard_expired_requests(now)
            token_digest = hashlib.sha256(confirmation_token.encode()).hexdigest()
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
            if confirmation is None or confirmation[:2] != (order_id, customer_id):
                return {
                    "cancelled": False,
                    "order_id": order_id,
                    "message": "Cancellation confirmation is invalid or expired.",
                }

            expected_updated_at = confirmation[2]
            updated_order = self._repository.cancel_order_if_eligible(
                order_id,
                customer_id,
                now,
                expected_updated_at,
            )
            del self._confirmations[confirmation_token]
            if updated_order is None:
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

    def _discard_expired(self, now: datetime) -> None:
        expired_tokens = [
            token
            for token, (_, _, _, expires_at) in self._confirmations.items()
            if expires_at <= now
        ]
        for token in expired_tokens:
            del self._confirmations[token]

    def _discard_expired_requests(self, now: datetime) -> None:
        expired_keys = [
            key
            for key, (_, _, _, expires_at, _) in self._completed_requests.items()
            if expires_at <= now
        ]
        for key in expired_keys:
            del self._completed_requests[key]

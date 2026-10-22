import secrets
from datetime import datetime, timedelta, timezone
from threading import RLock

from app.storage.json_store import JsonRepository
from app.storage.repository import SupportRepository

DEMO_AUTHORIZATION_LIFETIME = timedelta(minutes=15)
MAX_ACTIVE_TOKENS_PER_CUSTOMER = 5


class DemoAuthorizationError(RuntimeError):
    """Raised when a requested demo identity is not present in seeded records."""


class DemoAuthorizationService:
    def __init__(
        self,
        repository: SupportRepository,
        token_lifetime: timedelta = DEMO_AUTHORIZATION_LIFETIME,
    ) -> None:
        if token_lifetime <= timedelta(0):
            raise ValueError("Demo authorization token lifetime must be positive.")
        self._repository = repository
        self._token_lifetime = token_lifetime
        self._tokens: dict[str, tuple[str, datetime]] = {}
        self._lock = RLock()

    def issue_token(self, customer_id: str) -> tuple[str, datetime]:
        if not any(
            order.customer_id == customer_id
            for order in self._repository.get_orders()
        ):
            raise DemoAuthorizationError("Unknown demo customer identity.")

        now = datetime.now(timezone.utc)
        expires_at = now + self._token_lifetime
        with self._lock:
            self._discard_expired(now)
            customer_tokens = sorted(
                (
                    (expires_at, existing_token)
                    for existing_token, (existing_customer, expires_at)
                    in self._tokens.items()
                    if existing_customer == customer_id
                ),
                key=lambda item: item[0],
            )
            while len(customer_tokens) >= MAX_ACTIVE_TOKENS_PER_CUSTOMER:
                _, expired_token = customer_tokens.pop(0)
                del self._tokens[expired_token]
            token = secrets.token_urlsafe(32)
            self._tokens[token] = (customer_id, expires_at)
        return token, expires_at

    def resolve_customer(self, token: str) -> str | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._discard_expired(now)
            authorization = self._tokens.get(token)
            if authorization is None:
                return None
            return authorization[0]

    def _discard_expired(self, now: datetime) -> None:
        expired_tokens = [
            token
            for token, (_, expires_at) in self._tokens.items()
            if expires_at <= now
        ]
        for token in expired_tokens:
            del self._tokens[token]


demo_authorization_service = DemoAuthorizationService(JsonRepository())

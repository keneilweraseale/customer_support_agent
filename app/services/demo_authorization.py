import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from threading import RLock

from app.storage.json_store import JsonRepository
from app.storage.models import CustomerAccount
from app.storage.repository import SupportRepository

DEMO_AUTHORIZATION_LIFETIME = timedelta(minutes=15)
MAX_ACTIVE_TOKENS_PER_CUSTOMER = 5
PASSWORD_HASH_N = 2**14
PASSWORD_HASH_R = 8
PASSWORD_HASH_P = 1
MIN_PASSWORD_LENGTH = 12
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class DemoAuthorizationError(RuntimeError):
    """Raised for invalid credentials or an unknown seeded customer identity."""


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

    def authenticate(self, email: str, password: str) -> tuple[str, datetime]:
        normalized_email = email.strip().casefold()
        account = next(
            (
                item
                for item in self._repository.get_customer_accounts()
                if item.email.casefold() == normalized_email
            ),
            None,
        )
        if account is None:
            _verify_password(password, _DUMMY_PASSWORD_HASH)
            raise DemoAuthorizationError("Invalid email or password.")
        if not _verify_password(password, account.password_hash):
            raise DemoAuthorizationError("Invalid email or password.")
        return self.issue_token(account.customer_id)

    def create_account(self, email: str, password: str, customer_id: str) -> None:
        normalized_email = email.strip().casefold()
        if not EMAIL_PATTERN.fullmatch(normalized_email):
            raise ValueError("A valid email address is required.")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"Passwords must be at least {MIN_PASSWORD_LENGTH} characters long."
            )
        if len(password) > 256:
            raise ValueError("Passwords must be no more than 256 characters long.")
        account = CustomerAccount(
            email=normalized_email,
            customer_id=customer_id,
            password_hash=_hash_password(password),
        )
        self._repository.create_customer_account(account)

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


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    password_digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=PASSWORD_HASH_N,
        r=PASSWORD_HASH_R,
        p=PASSWORD_HASH_P,
        dklen=32,
    )
    return "scrypt${}${}${}${}${}".format(
        PASSWORD_HASH_N,
        PASSWORD_HASH_R,
        PASSWORD_HASH_P,
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(password_digest).decode("ascii").rstrip("="),
    )


def _verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, n_value, r_value, p_value, salt_value, digest_value = (
            encoded_hash.split("$")
        )
        if algorithm != "scrypt":
            return False
        n, r, p = int(n_value), int(r_value), int(p_value)
        if (n, r, p) != (PASSWORD_HASH_N, PASSWORD_HASH_R, PASSWORD_HASH_P):
            return False
        salt = base64.urlsafe_b64decode(salt_value + "=" * (-len(salt_value) % 4))
        expected_digest = base64.urlsafe_b64decode(
            digest_value + "=" * (-len(digest_value) % 4)
        )
        actual_digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected_digest),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual_digest, expected_digest)


_DUMMY_PASSWORD_HASH = _hash_password("not-a-valid-customer-password")

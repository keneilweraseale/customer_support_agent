from datetime import datetime
import math
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    ),
]
MAX_CONVERSATION_TURNS = 200


class RecordModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationTurn(RecordModel):
    role: Literal["user", "assistant"]
    text: Annotated[str, StringConstraints(max_length=2000)]
    created_at: datetime


SupportTicketStatus = Literal[
    "open",
    "investigating",
    "waiting_for_customer",
    "escalated",
    "resolved",
    "closed",
]


class SupportTicketStatusChange(RecordModel):
    previous_status: SupportTicketStatus
    status: SupportTicketStatus
    changed_by: Identifier
    changed_at: datetime
    note: Annotated[str, StringConstraints(max_length=1000)] | None = None


class SupportTicketCustomerUpdate(RecordModel):
    status: SupportTicketStatus
    message: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    created_at: datetime


class SupportTicketMessage(RecordModel):
    author_role: Literal["customer", "support_agent"]
    author_id: Identifier | None = None
    text: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    created_at: datetime


class SupportTicketInternalNote(RecordModel):
    staff_id: Identifier
    text: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    created_at: datetime


class SupportTicketAuditEvent(RecordModel):
    action: Literal[
        "priority_changed",
        "assignment_changed",
        "reply_sent",
        "internal_note_added",
    ]
    changed_by: Identifier
    description: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    created_at: datetime


class ConversationMemory(RecordModel):
    conversation_id: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    owner_id: Identifier
    turns: list[ConversationTurn] = Field(max_length=MAX_CONVERSATION_TURNS)
    first_user_message: ConversationTurn | None = None
    last_order_id: Identifier | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


CancellationReasonCode = Literal[
    "ordered_by_mistake",
    "delivery_too_late",
    "found_better_price",
    "changed_mind",
    "duplicate_order",
    "payment_problem",
    "other",
    "not_provided",
]
CancellationReasonText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=280),
]


def validate_cancellation_reason(
    reason_code: CancellationReasonCode,
    reason_text: str | None,
) -> None:
    if reason_text is not None and reason_code != "other":
        raise ValueError("A free-text reason is only allowed for reason_code 'other'.")


class CancellationEvent(RecordModel):
    event_id: Identifier
    request_id: Identifier
    order_id: Identifier
    customer_id: Identifier
    reason_code: CancellationReasonCode
    reason_text: CancellationReasonText | None = None
    requested_at: datetime
    eligibility_result: Literal["eligible", "ineligible"]
    outcome: Literal[
        "pending_confirmation",
        "cancelled",
        "declined",
        "ineligible",
        "withdrawn",
    ]
    outcome_at: datetime | None = None
    actor: Literal[
        "customer_confirmed",
        "customer_declined",
        "customer_withdrew",
        "system",
    ]


class SupportTicket(RecordModel):
    ticket_id: Annotated[
        str,
        StringConstraints(min_length=1, max_length=64),
    ]
    conversation_id: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    customer_message: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    customer_id: Identifier | None = None
    order_id: Identifier | None = None
    issue_summary: Annotated[str, StringConstraints(max_length=2000)] | None = None
    conversation_context: list[ConversationTurn] = Field(
        default_factory=list,
        max_length=12,
    )
    status: SupportTicketStatus = "open"
    status_history: list[SupportTicketStatusChange] = Field(
        default_factory=list,
        max_length=100,
    )
    customer_update: SupportTicketCustomerUpdate | None = None
    created_at: datetime
    updated_at: datetime | None = None
    category: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    ] = "General"
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    assigned_to: Identifier | None = None
    messages: list[SupportTicketMessage] = Field(default_factory=list, max_length=200)
    internal_notes: list[SupportTicketInternalNote] = Field(default_factory=list, max_length=200)
    audit_history: list[SupportTicketAuditEvent] = Field(default_factory=list, max_length=500)


class DamageReport(RecordModel):
    report_id: Identifier
    idempotency_key: Annotated[
        str,
        StringConstraints(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    ]
    request_fingerprint: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    customer_id: Identifier
    order_id: Identifier
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None
    image_filename: Annotated[str, StringConstraints(pattern=r"^[a-f0-9-]{36}\.(jpg|png)$")]
    created_at: datetime


class OrderItem(RecordModel):
    product_id: Identifier
    quantity: int = Field(gt=0)


class Order(RecordModel):
    order_id: Identifier
    customer_id: Identifier
    items: list[OrderItem] = Field(min_length=1)
    order_status: Literal["processing", "shipped", "delivered", "cancelled"]
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    created_at: datetime
    updated_at: datetime
    cancellation_allowed: bool


class CustomerAccount(RecordModel):
    email: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=3,
            max_length=254,
            pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        ),
    ]
    customer_id: Identifier
    password_hash: Annotated[
        str,
        StringConstraints(
            min_length=1,
            max_length=256,
            pattern=r"^scrypt\$16384\$8\$1\$[A-Za-z0-9_-]{22}\$[A-Za-z0-9_-]{43}$",
        ),
    ]


class SupportAgentAccount(RecordModel):
    email: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=3,
            max_length=254,
            pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        ),
    ]
    staff_id: Identifier
    password_hash: Annotated[
        str,
        StringConstraints(
            min_length=1,
            max_length=256,
            pattern=r"^scrypt\$16384\$8\$1\$[A-Za-z0-9_-]{22}\$[A-Za-z0-9_-]{43}$",
        ),
    ]
    role: Literal["support_agent"] = "support_agent"


class Delivery(RecordModel):
    shipment_id: Identifier
    order_id: Identifier
    carrier: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    tracking_reference: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    delivery_status: Literal["label_created", "in_transit", "delayed", "delivered"]
    estimated_delivery: datetime | None
    last_update: datetime
    delay_reason: str | None


class Payment(RecordModel):
    payment_id: Identifier
    order_id: Identifier
    payment_status: Literal["pending", "paid", "failed", "refunded"]
    provider_reference: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    error_code: Annotated[str, StringConstraints(max_length=100)] | None
    updated_at: datetime


class Product(RecordModel):
    product_id: Identifier
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    price: float = Field(ge=0, allow_inf_nan=False)
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    stock_quantity: int = Field(ge=0)
    warranty_summary: Annotated[str, StringConstraints(max_length=1000)]


class Review(RecordModel):
    review_id: Identifier
    product_id: Identifier
    rating: int = Field(ge=1, le=5)
    review_text: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    created_at: datetime


class PolicyDocument(RecordModel):
    document_id: Identifier
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    category: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    source: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    approved: bool
    updated_at: datetime


class PolicyChunk(RecordModel):
    chunk_id: Identifier
    document_id: Identifier
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    text: Annotated[str, StringConstraints(min_length=1)]
    embedding: list[float]
    metadata: dict[str, str | bool | int]
    token_count: int = Field(ge=1)
    embedding_model: Annotated[str, StringConstraints(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def validate_embedding_values(self) -> "PolicyChunk":
        if any(not math.isfinite(value) for value in self.embedding):
            raise ValueError("Embedding values must be finite numbers.")
        if not all(
            key in self.metadata
            for key in ("category", "approved", "source", "updated_at", "chunk_index")
        ):
            raise ValueError("Policy chunk metadata is incomplete.")
        return self


class ReviewSearchInput(RecordModel):
    product_id: Identifier | None = Field(
        default=None,
        description="Optional product ID to limit the review search.",
    )
    query: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
    ] | None = Field(
        default=None,
        description="Optional text to search within review text.",
    )

    @model_validator(mode="after")
    def require_product_or_query(self) -> "ReviewSearchInput":
        if self.product_id is None and self.query is None:
            raise ValueError("Provide a product_id or a query.")
        return self


class OrderToolInput(RecordModel):
    order_id: Identifier = Field(description="The customer's order reference.")
    customer_id: Identifier = Field(description="The authenticated customer ID.")


class ProductToolInput(RecordModel):
    product_id: Identifier = Field(description="The product reference.")


class CustomerOrdersToolInput(RecordModel):
    customer_id: Identifier = Field(description="The authenticated customer ID.")


class CancellationToolInput(OrderToolInput):
    reason_code: CancellationReasonCode = "not_provided"
    reason_text: CancellationReasonText | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> "CancellationToolInput":
        validate_cancellation_reason(self.reason_code, self.reason_text)
        return self


class ConfirmCancellationInput(OrderToolInput):
    confirmation_token: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=32, max_length=128),
    ] = Field(description="Short-lived server-issued cancellation confirmation token.")
    idempotency_key: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=16, max_length=64),
    ] | None = Field(default=None, description="Unique key for safely retrying this confirmation.")
    reason_code: CancellationReasonCode = "not_provided"
    reason_text: CancellationReasonText | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> "ConfirmCancellationInput":
        validate_cancellation_reason(self.reason_code, self.reason_text)
        return self

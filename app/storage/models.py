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


class RecordModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    customer_id: Identifier = Field(description="The verified demo customer ID.")


class ProductToolInput(RecordModel):
    product_id: Identifier = Field(description="The product reference.")


class CancellationToolInput(OrderToolInput):
    pass


class ConfirmCancellationInput(OrderToolInput):
    confirmation_token: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=32, max_length=128),
    ] = Field(description="Short-lived server-issued cancellation confirmation token.")
    idempotency_key: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=16, max_length=64),
    ] | None = Field(default=None, description="Unique key for safely retrying this confirmation.")

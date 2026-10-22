from datetime import datetime
from typing import Protocol

from app.storage.models import (
    Delivery,
    Order,
    Payment,
    PolicyChunk,
    PolicyDocument,
    Product,
    Review,
)


class SupportRepository(Protocol):
    def get_orders(self) -> list[Order]: ...

    def get_order(self, order_id: str) -> Order | None: ...

    def get_deliveries_for_order(self, order_id: str) -> list[Delivery]: ...

    def get_payments_for_order(self, order_id: str) -> list[Payment]: ...

    def get_product(self, product_id: str) -> Product | None: ...

    def get_products(self) -> list[Product]: ...

    def get_reviews(self) -> list[Review]: ...

    def get_policy_documents(self) -> list[PolicyDocument]: ...

    def get_policy_chunks(self) -> list[PolicyChunk]: ...

    def replace_policy_chunks(
        self,
        document_id: str,
        chunks: list[PolicyChunk],
    ) -> None: ...

    def cancel_order_if_eligible(
        self,
        order_id: str,
        customer_id: str,
        updated_at: datetime,
        expected_updated_at: datetime,
    ) -> Order | None: ...

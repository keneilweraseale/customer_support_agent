from datetime import datetime
from typing import Protocol

from app.storage.models import (
    CancellationEvent,
    ConversationMemory,
    CustomerAccount,
    Delivery,
    Order,
    Payment,
    PolicyChunk,
    PolicyDocument,
    Product,
    Review,
    SupportTicket,
)


class SupportRepository(Protocol):
    def get_conversation_memory(
        self,
        conversation_id: str,
        owner_id: str,
    ) -> ConversationMemory | None: ...

    def save_conversation_memory(
        self,
        memory: ConversationMemory,
    ) -> ConversationMemory: ...

    def expire_old_conversations(self, now: datetime | None = None) -> int: ...

    def append_cancellation_event(self, event: CancellationEvent) -> None: ...

    def update_cancellation_event(self, event: CancellationEvent) -> None: ...

    def append_support_ticket(self, ticket: SupportTicket) -> None: ...

    def get_support_ticket(self, ticket_id: str) -> SupportTicket | None: ...

    def expire_old_cancellation_events(
        self,
        now: datetime | None = None,
    ) -> int: ...

    def get_orders(self) -> list[Order]: ...

    def get_customer_accounts(self) -> list[CustomerAccount]: ...

    def create_customer_account(self, account: CustomerAccount) -> None: ...

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
        cancellation_event: CancellationEvent | None = None,
    ) -> Order | None: ...

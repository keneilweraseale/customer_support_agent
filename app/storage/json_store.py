import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.storage.models import (
    CancellationEvent,
    ConversationMemory,
    CustomerAccount,
    DamageReport,
    Delivery,
    Order,
    Payment,
    PolicyChunk,
    PolicyDocument,
    Product,
    Review,
    SupportAgentAccount,
    SupportTicket,
    SupportTicketStatus,
)
from app.storage.repository import SupportRepository

ModelT = TypeVar("ModelT", bound=BaseModel)


class DataStoreError(RuntimeError):
    """Raised when demo JSON data cannot be read, validated, or written."""


class ConversationOwnershipError(DataStoreError):
    """Raised when a conversation ID is already owned by another customer."""


class CancellationConsistencyError(DataStoreError):
    """Raised when the order and cancellation history cannot be synchronized."""


class SupportTicketConflictError(DataStoreError):
    """Raised when a ticket changed before a requested status update was saved."""


class DamageReportConflictError(DataStoreError):
    """Raised when an idempotency key is reused for a different damage report."""


class JsonRepository(SupportRepository):
    def __init__(
        self,
        data_directory: Path | None = None,
        conversation_ttl: timedelta = timedelta(minutes=30),
        max_conversation_turns: int = 12,
        cancellation_history_retention: timedelta = timedelta(days=365),
    ) -> None:
        if conversation_ttl <= timedelta(0):
            raise ValueError("Conversation TTL must be positive.")
        if not 1 <= max_conversation_turns <= 12:
            raise ValueError("Conversation memory must retain between 1 and 12 turns.")
        if cancellation_history_retention <= timedelta(0):
            raise ValueError("Cancellation history retention must be positive.")
        self.data_directory = data_directory or Path(__file__).resolve().parents[2] / "data"
        self._write_lock = RLock()
        self._conversation_ttl = conversation_ttl
        self._max_conversation_turns = max_conversation_turns
        self._cancellation_history_retention = cancellation_history_retention

    def _read_optional_records(
        self,
        filename: str,
        model: type[ModelT],
        id_field: str,
    ) -> list[ModelT]:
        if not (self.data_directory / filename).exists():
            return []
        return self._read_records(filename, model, id_field)

    def get_conversation_memory(
        self,
        conversation_id: str,
        owner_id: str,
    ) -> ConversationMemory | None:
        with self._write_lock:
            self.expire_old_conversations()
            memories = self._read_optional_records(
                "conversation_memory.json",
                ConversationMemory,
                "conversation_id",
            )
            return next(
                (
                    memory
                    for memory in memories
                    if memory.conversation_id == conversation_id
                    and memory.owner_id == owner_id
                ),
                None,
            )

    def save_conversation_memory(
        self,
        memory: ConversationMemory,
    ) -> ConversationMemory:
        with self._write_lock:
            now = datetime.now(timezone.utc)
            self.expire_old_conversations(now)
            memories = self._read_optional_records(
                "conversation_memory.json",
                ConversationMemory,
                "conversation_id",
            )
            existing = next(
                (
                    item
                    for item in memories
                    if item.conversation_id == memory.conversation_id
                ),
                None,
            )
            if existing is not None and existing.owner_id != memory.owner_id:
                raise ConversationOwnershipError(
                    "Conversation ID belongs to a different customer."
                )

            saved_memory = ConversationMemory.model_validate(
                memory.model_dump() | {
                    "turns": memory.turns[-self._max_conversation_turns :],
                    "created_at": existing.created_at if existing else memory.created_at,
                    "updated_at": now,
                    "expires_at": now + self._conversation_ttl,
                }
            )
            updated = [
                item
                for item in memories
                if item.conversation_id != memory.conversation_id
            ]
            updated.append(saved_memory)
            self._write_records("conversation_memory.json", updated)
            return saved_memory

    def expire_old_conversations(self, now: datetime | None = None) -> int:
        with self._write_lock:
            current_time = now or datetime.now(timezone.utc)
            memories = self._read_optional_records(
                "conversation_memory.json",
                ConversationMemory,
                "conversation_id",
            )
            active_memories = [
                memory for memory in memories if memory.expires_at > current_time
            ]
            expired_count = len(memories) - len(active_memories)
            if expired_count:
                self._write_records("conversation_memory.json", active_memories)
            return expired_count

    def append_cancellation_event(self, event: CancellationEvent) -> None:
        with self._write_lock:
            events = self._active_cancellation_events()
            if any(
                existing.event_id == event.event_id
                or existing.request_id == event.request_id
                for existing in events
            ):
                raise DataStoreError("Cancellation event ID already exists.")
            events.append(event)
            self._write_records("cancellation_history.json", events)

    def append_support_ticket(self, ticket: SupportTicket) -> None:
        with self._write_lock:
            tickets = self._read_optional_records(
                "support_tickets.json",
                SupportTicket,
                "ticket_id",
            )
            if any(existing.ticket_id == ticket.ticket_id for existing in tickets):
                raise DataStoreError("Support ticket ID already exists.")
            tickets.append(ticket)
            self._write_records("support_tickets.json", tickets)

    def get_support_ticket(self, ticket_id: str) -> SupportTicket | None:
        with self._write_lock:
            tickets = self._read_optional_records(
                "support_tickets.json",
                SupportTicket,
                "ticket_id",
            )
            return next(
                (ticket for ticket in tickets if ticket.ticket_id == ticket_id),
                None,
            )

    def get_support_tickets(self) -> list[SupportTicket]:
        with self._write_lock:
            return self._read_optional_records(
                "support_tickets.json",
                SupportTicket,
                "ticket_id",
            )

    def update_support_ticket(
        self,
        ticket: SupportTicket,
        expected_status: SupportTicketStatus,
    ) -> SupportTicket | None:
        with self._write_lock:
            tickets = self._read_optional_records(
                "support_tickets.json",
                SupportTicket,
                "ticket_id",
            )
            ticket_index = next(
                (
                    index
                    for index, existing in enumerate(tickets)
                    if existing.ticket_id == ticket.ticket_id
                ),
                None,
            )
            if ticket_index is None:
                return None
            existing = tickets[ticket_index]
            if existing.status != expected_status:
                raise SupportTicketConflictError(
                    "Support ticket status changed before the update was saved."
                )
            if existing.customer_id != ticket.customer_id:
                raise DataStoreError("Support ticket owner cannot be changed.")
            tickets[ticket_index] = ticket
            self._write_records("support_tickets.json", tickets)
            return ticket

    def update_cancellation_event(self, event: CancellationEvent) -> None:
        with self._write_lock:
            events = self._active_cancellation_events()
            event_index = next(
                (
                    index
                    for index, existing in enumerate(events)
                    if existing.event_id == event.event_id
                ),
                None,
            )
            if event_index is None:
                raise DataStoreError("Cancellation event could not be found.")
            if events[event_index].request_id != event.request_id:
                raise DataStoreError("Cancellation request ID does not match.")
            events[event_index] = event
            self._write_records("cancellation_history.json", events)

    def expire_old_cancellation_events(
        self,
        now: datetime | None = None,
    ) -> int:
        with self._write_lock:
            current_time = now or datetime.now(timezone.utc)
            events = self._read_optional_records(
                "cancellation_history.json",
                CancellationEvent,
                "event_id",
            )
            cutoff = current_time - self._cancellation_history_retention
            active_events = [
                event for event in events if event.requested_at > cutoff
            ]
            expired_count = len(events) - len(active_events)
            if expired_count:
                self._write_records("cancellation_history.json", active_events)
            return expired_count

    def _active_cancellation_events(self) -> list[CancellationEvent]:
        events = self._read_optional_records(
            "cancellation_history.json",
            CancellationEvent,
            "event_id",
        )
        cutoff = datetime.now(timezone.utc) - self._cancellation_history_retention
        return [event for event in events if event.requested_at > cutoff]

    def _read_records(
        self,
        filename: str,
        model: type[ModelT],
        id_field: str,
    ) -> list[ModelT]:
        path = self.data_directory / filename
        try:
            raw_records = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise DataStoreError(f"Required data file is missing: {filename}") from exc
        except json.JSONDecodeError as exc:
            raise DataStoreError(f"Data file contains invalid JSON: {filename}") from exc
        except OSError as exc:
            raise DataStoreError(f"Could not read data file: {filename}") from exc

        if not isinstance(raw_records, list):
            raise DataStoreError(f"Data file must contain a JSON array: {filename}")

        try:
            records = [model.model_validate(record) for record in raw_records]
        except ValidationError as exc:
            raise DataStoreError(f"Data file has invalid records: {filename}") from exc

        identifiers = [getattr(record, id_field) for record in records]
        if len(identifiers) != len(set(identifiers)):
            raise DataStoreError(f"Data file contains duplicate {id_field} values: {filename}")
        return records

    def _write_records(self, filename: str, records: list[BaseModel]) -> None:
        path = self.data_directory / filename
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(
                    [record.model_dump(mode="json") for record in records],
                    temporary_file,
                    ensure_ascii=False,
                    indent=2,
                )
                temporary_file.write("\n")
            os.replace(temporary_path, path)
        except OSError as exc:
            raise DataStoreError(f"Could not write data file: {filename}") from exc
        finally:
            if "temporary_path" in locals() and temporary_path.exists():
                temporary_path.unlink()

    def get_order(self, order_id: str) -> Order | None:
        with self._write_lock:
            return next(
                (
                    order
                    for order in self._read_records("orders.json", Order, "order_id")
                    if order.order_id == order_id
                ),
                None,
            )

    def create_damage_report(
        self,
        report: DamageReport,
        image_bytes: bytes,
    ) -> tuple[DamageReport, bool]:
        with self._write_lock:
            reports = self._read_optional_records(
                "damage_reports.json",
                DamageReport,
                "report_id",
            )
            existing = next(
                (
                    item
                    for item in reports
                    if item.idempotency_key == report.idempotency_key
                ),
                None,
            )
            if existing is not None:
                if existing.request_fingerprint != report.request_fingerprint:
                    raise DamageReportConflictError(
                        "Idempotency key was already used for a different report."
                    )
                return existing, False
            if any(item.report_id == report.report_id for item in reports):
                raise DataStoreError("Damage report ID already exists.")

            image_directory = self.data_directory / "damage_report_images"
            image_path = image_directory / report.image_filename
            temporary_path: Path | None = None
            image_installed = False
            try:
                image_directory.mkdir(parents=True, exist_ok=True)
                if image_path.exists():
                    raise DataStoreError("Damage report image already exists.")
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=image_directory,
                    delete=False,
                ) as temporary_file:
                    temporary_path = Path(temporary_file.name)
                    temporary_file.write(image_bytes)
                os.replace(temporary_path, image_path)
                temporary_path = None
                image_installed = True
                reports.append(report)
                self._write_records("damage_reports.json", reports)
            except (OSError, DataStoreError) as exc:
                if image_installed:
                    try:
                        image_path.unlink()
                    except OSError as cleanup_error:
                        raise DataStoreError(
                            "Damage report could not be saved and its image could not be removed."
                        ) from cleanup_error
                if isinstance(exc, DataStoreError):
                    raise
                raise DataStoreError("Could not write damage report image.") from exc
            finally:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink()
                    except FileNotFoundError:
                        pass
                    except OSError as cleanup_error:
                        raise DataStoreError(
                            "Could not remove temporary damage report image."
                        ) from cleanup_error

            return report, True

    def get_customer_accounts(self) -> list[CustomerAccount]:
        with self._write_lock:
            accounts = self._read_optional_records(
                "customer_accounts.json",
                CustomerAccount,
                "email",
            )
            normalized_emails = [account.email.casefold() for account in accounts]
            customer_ids = [account.customer_id for account in accounts]
            if len(normalized_emails) != len(set(normalized_emails)):
                raise DataStoreError("Customer account emails must be unique.")
            if len(customer_ids) != len(set(customer_ids)):
                raise DataStoreError("Customer accounts must have unique customer IDs.")
            return accounts

    def create_customer_account(self, account: CustomerAccount) -> None:
        with self._write_lock:
            accounts = self._read_optional_records(
                "customer_accounts.json",
                CustomerAccount,
                "email",
            )
            if any(
                existing.email.casefold() == account.email.casefold()
                for existing in accounts
            ):
                raise DataStoreError("An account already exists for that email address.")
            if any(existing.customer_id == account.customer_id for existing in accounts):
                raise DataStoreError("An account already exists for that customer.")
            if not any(
                order.customer_id == account.customer_id
                for order in self._read_records("orders.json", Order, "order_id")
            ):
                raise DataStoreError("The account must be linked to a known customer.")
            accounts.append(account)
            self._write_records("customer_accounts.json", accounts)

    def get_support_agent_accounts(self) -> list[SupportAgentAccount]:
        with self._write_lock:
            accounts = self._read_optional_records(
                "support_agents.json",
                SupportAgentAccount,
                "staff_id",
            )
            normalized_emails = [account.email.casefold() for account in accounts]
            staff_ids = [account.staff_id for account in accounts]
            if len(normalized_emails) != len(set(normalized_emails)):
                raise DataStoreError("Support-agent account emails must be unique.")
            if len(staff_ids) != len(set(staff_ids)):
                raise DataStoreError("Support-agent IDs must be unique.")
            return accounts

    def create_support_agent_account(self, account: SupportAgentAccount) -> None:
        with self._write_lock:
            accounts = self._read_optional_records(
                "support_agents.json",
                SupportAgentAccount,
                "staff_id",
            )
            if any(
                existing.email.casefold() == account.email.casefold()
                for existing in accounts
            ):
                raise DataStoreError(
                    "A support-agent account already exists for that email address."
                )
            if any(existing.staff_id == account.staff_id for existing in accounts):
                raise DataStoreError(
                    "A support-agent account already exists for that staff ID."
                )
            accounts.append(account)
            self._write_records("support_agents.json", accounts)

    def get_orders(self) -> list[Order]:
        with self._write_lock:
            return self._read_records("orders.json", Order, "order_id")

    def get_deliveries_for_order(self, order_id: str) -> list[Delivery]:
        with self._write_lock:
            return [
                delivery
                for delivery in self._read_records(
                    "deliveries.json", Delivery, "shipment_id"
                )
                if delivery.order_id == order_id
            ]

    def get_payments_for_order(self, order_id: str) -> list[Payment]:
        with self._write_lock:
            return [
                payment
                for payment in self._read_records("payments.json", Payment, "payment_id")
                if payment.order_id == order_id
            ]

    def get_product(self, product_id: str) -> Product | None:
        with self._write_lock:
            return next(
                (
                    product
                    for product in self._read_records(
                        "products.json", Product, "product_id"
                    )
                    if product.product_id == product_id
                ),
                None,
            )

    def get_products(self) -> list[Product]:
        with self._write_lock:
            return self._read_records("products.json", Product, "product_id")

    def get_reviews(self) -> list[Review]:
        with self._write_lock:
            return self._read_records("reviews.json", Review, "review_id")

    def get_policy_documents(self) -> list[PolicyDocument]:
        with self._write_lock:
            return self._read_records(
                "policy_documents.json",
                PolicyDocument,
                "document_id",
            )

    def get_policy_chunks(self) -> list[PolicyChunk]:
        with self._write_lock:
            return self._read_records(
                "policy_chunks.json",
                PolicyChunk,
                "chunk_id",
            )

    def replace_policy_chunks(
        self,
        document_id: str,
        chunks: list[PolicyChunk],
    ) -> None:
        with self._write_lock:
            current = self._read_records(
                "policy_chunks.json",
                PolicyChunk,
                "chunk_id",
            )
            replacement_ids = [chunk.chunk_id for chunk in chunks]
            if len(replacement_ids) != len(set(replacement_ids)):
                raise DataStoreError("Replacement policy chunks contain duplicate IDs.")
            if any(chunk.document_id != document_id for chunk in chunks):
                raise DataStoreError("Replacement chunks contain a different document ID.")
            existing_ids = {
                chunk.chunk_id for chunk in current if chunk.document_id != document_id
            }
            if existing_ids.intersection(replacement_ids):
                raise DataStoreError("Replacement policy chunk ID already exists.")
            updated = [
                chunk for chunk in current if chunk.document_id != document_id
            ] + chunks
            self._write_records("policy_chunks.json", updated)

    def validate_references(self) -> None:
        orders = self._read_records("orders.json", Order, "order_id")
        deliveries = self._read_records("deliveries.json", Delivery, "shipment_id")
        payments = self._read_records("payments.json", Payment, "payment_id")
        products = self._read_records("products.json", Product, "product_id")
        reviews = self._read_records("reviews.json", Review, "review_id")

        order_ids = {order.order_id for order in orders}
        product_ids = {product.product_id for product in products}

        if any(
            item.product_id not in product_ids
            for order in orders
            for item in order.items
        ):
            raise DataStoreError("An order references a missing product.")
        if any(delivery.order_id not in order_ids for delivery in deliveries):
            raise DataStoreError("A delivery references a missing order.")
        if any(payment.order_id not in order_ids for payment in payments):
            raise DataStoreError("A payment references a missing order.")
        if any(review.product_id not in product_ids for review in reviews):
            raise DataStoreError("A review references a missing product.")

    def cancel_order_if_eligible(
        self,
        order_id: str,
        customer_id: str,
        updated_at: datetime,
        expected_updated_at: datetime,
        cancellation_event: CancellationEvent | None = None,
    ) -> Order | None:
        with self._write_lock:
            orders = self._read_records("orders.json", Order, "order_id")
            original_orders = list(orders)
            order_index = next(
                (
                    index
                    for index, order in enumerate(orders)
                    if order.order_id == order_id
                    and order.customer_id == customer_id
                ),
                None,
            )
            if order_index is None:
                return None

            order = orders[order_index]
            if (
                not order.cancellation_allowed
                or order.order_status != "processing"
                or order.updated_at != expected_updated_at
            ):
                return None

            updated_order = order.model_copy(
                update={
                    "order_status": "cancelled",
                    "cancellation_allowed": False,
                    "updated_at": updated_at,
                }
            )
            updated_order = Order.model_validate(updated_order)
            orders[order_index] = updated_order
            self._write_records("orders.json", orders)
            if cancellation_event is not None:
                try:
                    self.update_cancellation_event(cancellation_event)
                except DataStoreError:
                    try:
                        self._write_records("orders.json", original_orders)
                    except DataStoreError as rollback_error:
                        raise CancellationConsistencyError(
                            "Order and cancellation history could not be synchronized."
                        ) from rollback_error
                    raise
            return updated_order

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.storage.models import (
    Delivery,
    Order,
    Payment,
    PolicyChunk,
    PolicyDocument,
    Product,
    Review,
)
from app.storage.repository import SupportRepository

ModelT = TypeVar("ModelT", bound=BaseModel)


class DataStoreError(RuntimeError):
    """Raised when demo JSON data cannot be read, validated, or written."""


class JsonRepository(SupportRepository):
    def __init__(self, data_directory: Path | None = None) -> None:
        self.data_directory = data_directory or Path(__file__).resolve().parents[2] / "data"
        self._write_lock = RLock()

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
    ) -> Order | None:
        with self._write_lock:
            orders = self._read_records("orders.json", Order, "order_id")
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
            return updated_order

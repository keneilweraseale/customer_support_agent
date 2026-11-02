import json
import os
from pathlib import Path
from typing import TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from app.storage.factory import repository_from_environment
from app.storage.json_store import DataStoreError
from app.storage.mongodb import COLLECTIONS, MongoRepository
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
)

ModelT = TypeVar("ModelT", bound=BaseModel)
DATA_DIRECTORY = Path(__file__).resolve().parents[2] / "data"
OPTIONAL_DATASETS = {
    "conversation_memory.json",
    "cancellation_history.json",
    "customer_accounts.json",
    "support_agents.json",
    "support_tickets.json",
    "damage_reports.json",
}
MIGRATION_DATASETS: tuple[tuple[str, str, type[BaseModel], str], ...] = (
    ("conversation_memory.json", "conversation_memory", ConversationMemory, "conversation_id"),
    ("cancellation_history.json", "cancellation_history", CancellationEvent, "event_id"),
    ("customer_accounts.json", "customer_accounts", CustomerAccount, "customer_id"),
    ("support_agents.json", "support_agents", SupportAgentAccount, "staff_id"),
    ("support_tickets.json", "support_tickets", SupportTicket, "ticket_id"),
    ("damage_reports.json", "damage_reports", DamageReport, "report_id"),
    ("orders.json", "orders", Order, "order_id"),
    ("deliveries.json", "deliveries", Delivery, "shipment_id"),
    ("payments.json", "payments", Payment, "payment_id"),
    ("products.json", "products", Product, "product_id"),
    ("reviews.json", "reviews", Review, "review_id"),
    ("policy_documents.json", "policy_documents", PolicyDocument, "document_id"),
    ("policy_chunks.json", "policy_chunks", PolicyChunk, "chunk_id"),
)


def _read_dataset(filename: str, model: type[ModelT]) -> list[ModelT]:
    path = DATA_DIRECTORY / filename
    if filename in OPTIONAL_DATASETS and not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataStoreError(f"Could not read migration source {filename}.") from exc
    if not isinstance(rows, list):
        raise DataStoreError(f"Migration source must contain an array: {filename}.")
    try:
        return [model.model_validate(row) for row in rows]
    except ValidationError as exc:
        raise DataStoreError(f"Migration source has invalid records: {filename}.") from exc


def _record_document(
    model: BaseModel,
    identifier_field: str,
    data_directory: Path,
) -> dict[str, object]:
    document = model.model_dump(mode="python")
    if isinstance(model, (CustomerAccount, SupportAgentAccount)):
        document["email_normalized"] = model.email.casefold()
    if isinstance(model, DamageReport):
        image_path = data_directory / "damage_report_images" / model.image_filename
        try:
            document["image_bytes"] = image_path.read_bytes()
        except OSError as exc:
            raise DataStoreError(
                f"Damage report image is missing: {model.image_filename}."
            ) from exc
    if identifier_field not in document:
        raise DataStoreError(f"Migration record is missing {identifier_field}.")
    return document


def migrate_json_datasets(repository: MongoRepository) -> dict[str, tuple[int, int]]:
    totals: dict[str, tuple[int, int]] = {}
    for filename, collection_key, model, identifier_field in MIGRATION_DATASETS:
        imported = 0
        existing_count = 0
        for record in _read_dataset(filename, model):
            document = _record_document(record, identifier_field, DATA_DIRECTORY)
            was_imported = repository.import_migration_record(
                collection_key,
                document,
                identifier_field,
            )
            imported += int(was_imported)
            existing_count += int(not was_imported)
        totals[COLLECTIONS[collection_key]] = (imported, existing_count)
    return totals


def main() -> None:
    load_dotenv(
        dotenv_path=Path(__file__).resolve().parents[2] / ".env",
        override=False,
    )
    if os.environ.get("STORAGE_BACKEND", "").strip().casefold() != "mongodb":
        raise SystemExit(
            "Set STORAGE_BACKEND=mongodb before running the migration."
        )
    repository = repository_from_environment()
    if not isinstance(repository, MongoRepository):
        raise SystemExit("MongoDB storage is not configured.")
    try:
        totals = migrate_json_datasets(repository)
        repository.validate_references()
    finally:
        repository.close()
    for collection, (imported, existing) in totals.items():
        print(
            f"{collection}: {imported} imported, "
            f"{existing} already present and unchanged"
        )


if __name__ == "__main__":
    main()

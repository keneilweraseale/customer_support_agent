import base64
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
    Product,
    Review,
    SupportAgentAccount,
    SupportTicket,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
DATA_DIRECTORY = Path(__file__).resolve().parents[2] / "data"
MIGRATION_DATASETS: tuple[tuple[str, str, type[BaseModel], str], ...] = (
    (
        "conversation_memory.json",
        "conversation_memory",
        ConversationMemory,
        "conversation_id",
    ),
    (
        "cancellation_history.json",
        "cancellation_history",
        CancellationEvent,
        "event_id",
    ),
    ("customer_accounts.json", "customer_accounts", CustomerAccount, "customer_id"),
    ("support_agents.json", "support_agents", SupportAgentAccount, "staff_id"),
    ("support_tickets.json", "support_tickets", SupportTicket, "ticket_id"),
    ("damage_reports.json", "damage_reports", DamageReport, "report_id"),
    ("orders.json", "orders", Order, "order_id"),
    ("deliveries.json", "deliveries", Delivery, "shipment_id"),
    ("payments.json", "payments", Payment, "payment_id"),
    ("products.json", "products", Product, "product_id"),
    ("reviews.json", "reviews", Review, "review_id"),
)
OBSOLETE_DEMO_POLICY_IDS = [
    "demo-refund-policy",
    "demo-contact-information",
    "demo-unapproved-shipping-draft",
]


def _read_dataset(filename: str, model: type[ModelT]) -> list[ModelT]:
    path = DATA_DIRECTORY / filename
    if not path.exists():
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
            document["image_base64"] = base64.b64encode(
                image_path.read_bytes()
            ).decode("ascii")
        except OSError as exc:
            raise DataStoreError(
                f"Damage report image is missing: {model.image_filename}."
            ) from exc
    if identifier_field not in document:
        raise DataStoreError(f"Migration record is missing {identifier_field}.")
    return document


def migrate_json_datasets(
    repository: MongoRepository,
    *,
    only_empty_collections: bool = False,
) -> dict[str, tuple[int, int]]:
    totals: dict[str, tuple[int, int]] = {}
    migrated_images = 0
    for filename, collection_key, model, identifier_field in MIGRATION_DATASETS:
        if (
            only_empty_collections
            and not repository.migration_collection_is_empty(collection_key)
        ):
            totals[COLLECTIONS[collection_key]] = (0, 0)
            continue
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
            if isinstance(record, DamageReport):
                image_base64 = document.get("image_base64")
                if not isinstance(image_base64, str):
                    raise DataStoreError(
                        f"Damage report image is invalid: {record.image_filename}."
                    )
                migrated_images += int(
                    repository.ensure_damage_report_image_base64(
                        record.report_id,
                        image_base64,
                    )
                )
        totals[COLLECTIONS[collection_key]] = (imported, existing_count)

    removed_documents, removed_chunks = repository.remove_policy_documents(
        OBSOLETE_DEMO_POLICY_IDS
    )
    migrated_images += repository.migrate_damage_report_images_to_base64()
    totals["obsolete_demo_policy_records"] = (removed_documents, removed_chunks)
    totals["damage_report_images"] = (migrated_images, 0)
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
        if collection == "obsolete_demo_policy_records":
            print(
                f"obsolete demo policies: {imported} documents and "
                f"{existing} chunks removed"
            )
            continue
        if collection == "damage_report_images":
            print(f"damage report images: {imported} stored as base64")
            continue
        print(
            f"{collection}: {imported} imported, "
            f"{existing} already present and preserved"
        )


if __name__ == "__main__":
    main()

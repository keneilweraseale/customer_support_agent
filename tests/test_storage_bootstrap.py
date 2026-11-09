import asyncio
import json
from pathlib import Path

from pydantic import BaseModel

from app import main
from app.storage import factory
from app.storage import migrate_json_to_mongodb as migration


class SeedRecord(BaseModel):
    record_id: str


class FakeMongoRepository:
    def __init__(self) -> None:
        self.records: dict[str, list[dict[str, object]]] = {}
        self.references_validated = False

    def migration_collection_is_empty(self, collection_name: str) -> bool:
        return not self.records.get(collection_name)

    def import_migration_record(
        self,
        collection_name: str,
        document: dict[str, object],
        identifier_field: str,
    ) -> bool:
        self.records.setdefault(collection_name, []).append(document)
        return True

    def validate_references(self) -> None:
        self.references_validated = True


def test_storage_defaults_to_mongodb(monkeypatch) -> None:
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.setattr(factory, "load_dotenv", lambda **_: None)
    monkeypatch.setattr(
        factory,
        "_configured_repository",
        lambda backend, *_: backend,
    )

    assert factory.repository_from_environment() == "mongodb"


def test_json_datasets_seed_empty_collections_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seed_path = tmp_path / "records.json"
    seed_path.write_text(
        json.dumps([{"record_id": "seed-1"}]),
        encoding="utf-8",
    )
    existing_repository = FakeMongoRepository()
    existing_repository.records["orders"] = [{"record_id": "existing"}]
    monkeypatch.setattr(migration, "DATA_DIRECTORY", tmp_path)
    monkeypatch.setattr(
        migration,
        "MIGRATION_DATASETS",
        (("records.json", "orders", SeedRecord, "record_id"),),
    )

    existing_totals = migration.migrate_json_datasets(
        existing_repository,
        only_empty_collections=True,
    )
    empty_repository = FakeMongoRepository()
    empty_totals = migration.migrate_json_datasets(
        empty_repository,
        only_empty_collections=True,
    )

    assert existing_repository.records["orders"] == [{"record_id": "existing"}]
    assert existing_totals["orders"] == (0, 0)
    assert empty_repository.records["orders"] == [{"record_id": "seed-1"}]
    assert empty_totals["orders"] == (1, 0)


def test_app_startup_bootstraps_mongodb(monkeypatch) -> None:
    repository = FakeMongoRepository()
    seeded = False

    def seed(
        target: FakeMongoRepository,
        *,
        only_empty_collections: bool,
    ) -> dict[str, tuple[int, int]]:
        nonlocal seeded
        assert target is repository
        assert only_empty_collections
        seeded = True
        return {}

    monkeypatch.setattr(main, "MongoRepository", FakeMongoRepository)
    monkeypatch.setattr(main, "repository_from_environment", lambda: repository)
    monkeypatch.setattr(main, "migrate_json_datasets", seed)

    async def run_lifespan() -> None:
        async with main.lifespan(main.app):
            pass

    asyncio.run(run_lifespan())

    assert seeded
    assert repository.references_validated

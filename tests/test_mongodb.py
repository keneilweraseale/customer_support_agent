import base64
from datetime import datetime, timezone

from app.storage.models import DamageReport, PolicyChunk
from app.storage.mongodb import (
    MongoRepository,
    _bson_datetime_precision,
    _normalize_policy_chunk_timestamp,
)


class FakeDamageReportCollection:
    def __init__(self) -> None:
        self.document: dict[str, object] | None = None

    def find_one(self, query, projection=None):
        del projection
        if self.document and (
            self.document.get("idempotency_key") == query.get("idempotency_key")
            or self.document.get("report_id") == query.get("report_id")
        ):
            return self.document
        return None

    def insert_one(self, document) -> None:
        self.document = document


class FakeMigrationCollection:
    def __init__(self, existing: dict[str, object]) -> None:
        self.existing = existing
        self.inserted = False

    def find_one(self, query):
        if self.existing.get("order_id") == query.get("order_id"):
            return self.existing.copy()
        return None

    def insert_one(self, _document) -> None:
        self.inserted = True


class FakeIndexCollection:
    def __init__(self) -> None:
        self.indexes: list[tuple[list[tuple[str, int]], dict[str, object]]] = []

    def create_index(self, keys, **options) -> None:
        self.indexes.append((keys, options))


class FakeVectorCollection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.pipeline = None

    def aggregate(self, pipeline):
        self.pipeline = pipeline
        return self.rows


def test_atlas_vector_search_uses_index_filters_and_converts_cosine_score() -> None:
    updated_at = datetime(2026, 10, 22, tzinfo=timezone.utc)
    chunk = PolicyChunk(
        chunk_id="refund-1",
        document_id="refund-policy",
        title="Refund policy",
        text="Refunds are available within thirty days.",
        embedding=[0.1, 0.2],
        metadata={
            "category": "refunds",
            "approved": True,
            "source": "refunds.md",
            "updated_at": updated_at.isoformat(),
            "chunk_index": 0,
        },
        token_count=7,
        embedding_model="mistral-embed",
    )
    row = chunk.model_dump(mode="python") | {
        "_id": "mongo-id",
        "_vector_score": 0.9,
    }
    collection = FakeVectorCollection([row])
    repository = object.__new__(MongoRepository)
    repository._vector_index_name = "policy_vector_index"
    repository._collection = lambda name: collection

    results = repository.vector_search_policy_chunks(
        [0.1, 0.2],
        document_versions={"refund-policy": updated_at.isoformat()},
    )

    assert results == [(chunk, 0.8)]
    search_stage = collection.pipeline[0]["$vectorSearch"]
    assert search_stage["index"] == "policy_vector_index"
    assert search_stage["filter"] == {
        "$and": [
            {"embedding_model": "mistral-embed"},
            {"metadata.approved": True},
            {
                "$or": [
                    {
                        "$and": [
                            {"document_id": "refund-policy"},
                            {"metadata.updated_at": updated_at.isoformat()},
                        ]
                    }
                ]
            },
        ]
    }


def test_atlas_bm25_search_uses_index_and_approved_current_policy_filters() -> None:
    updated_at = datetime(2026, 10, 22, tzinfo=timezone.utc)
    chunk = PolicyChunk(
        chunk_id="refund-1",
        document_id="refund-policy",
        title="Refund policy",
        text="Refunds are available within thirty days.",
        embedding=[0.1, 0.2],
        metadata={
            "category": "refunds",
            "approved": True,
            "source": "refunds.md",
            "updated_at": updated_at.isoformat(),
            "chunk_index": 0,
        },
        token_count=7,
        embedding_model="mistral-embed",
    )
    collection = FakeVectorCollection([chunk.model_dump(mode="python") | {"_id": "mongo-id"}])
    repository = object.__new__(MongoRepository)
    repository._search_index_name = "policy_bm25_index"
    repository._collection = lambda name: collection
    repository._run = lambda _operation, action: action()

    results = repository.bm25_search_policy_chunks(
        "refund within thirty days",
        limit=3,
        document_versions={"refund-policy": updated_at.isoformat()},
    )

    assert results == [chunk]
    search_stage = collection.pipeline[0]["$search"]
    assert search_stage["index"] == "policy_bm25_index"
    assert search_stage["compound"]["must"] == [
        {
            "text": {
                "query": "refund within thirty days",
                "path": ["text", "title"],
            }
        }
    ]
    assert search_stage["compound"]["filter"] == [
        {"equals": {"path": "metadata.approved", "value": True}},
        {
            "compound": {
                "should": [
                    {
                        "compound": {
                            "filter": [
                                {
                                    "equals": {
                                        "path": "document_id",
                                        "value": "refund-policy",
                                    }
                                },
                                {
                                    "equals": {
                                        "path": "metadata.updated_at",
                                        "value": updated_at.isoformat(),
                                    }
                                },
                            ]
                        }
                    }
                ],
                "minimumShouldMatch": 1,
            }
        },
    ]
    assert collection.pipeline[1] == {"$limit": 3}


def test_mongo_timestamp_normalization_matches_bson_precision() -> None:
    timestamp = datetime(2026, 10, 22, 12, 30, 45, 123456, timezone.utc)
    document = {
        "updated_at": timestamp,
        "metadata": {"updated_at": "2026-10-22T14:30:45.123456+02:00"},
    }

    normalized = {
        key: _bson_datetime_precision(value)
        for key, value in document.items()
    }
    _normalize_policy_chunk_timestamp(normalized)

    assert normalized["updated_at"] == datetime(
        2026, 10, 22, 12, 30, 45, 123000, timezone.utc
    )
    assert normalized["metadata"]["updated_at"] == "2026-10-22T12:30:45.123000+00:00"


def test_damage_report_images_are_stored_as_base64_and_decoded_on_read() -> None:
    image_bytes = b"\xff\xd8\xffexample\xff\xd9"
    report = DamageReport(
        report_id="damage-report-1",
        idempotency_key="damage-report-key-1",
        request_fingerprint="a" * 64,
        customer_id="customer-1",
        order_id="order-1",
        description="A damaged package",
        image_filename="00000000-0000-0000-0000-000000000001.jpg",
        created_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
    )
    collection = FakeDamageReportCollection()
    repository = object.__new__(MongoRepository)
    repository._collection = lambda _: collection
    repository._run = lambda _operation, action: action()

    saved_report, created = repository.create_damage_report(report, image_bytes)

    assert saved_report == report
    assert created
    assert collection.document is not None
    assert collection.document["image_base64"] == base64.b64encode(
        image_bytes
    ).decode("ascii")
    assert repository.get_damage_report_image(report.report_id) == image_bytes


def test_migration_preserves_existing_mongodb_records() -> None:
    collection = FakeMigrationCollection(
        {"_id": "mongo-id", "order_id": "ORD-1", "order_status": "shipped"}
    )
    repository = object.__new__(MongoRepository)
    repository._collection = lambda _: collection
    repository._run = lambda _operation, action: action()

    imported = repository.import_migration_record(
        "orders",
        {"order_id": "ORD-1", "order_status": "processing"},
        "order_id",
    )

    assert not imported
    assert collection.existing["order_status"] == "shipped"
    assert not collection.inserted


def test_mongodb_repository_creates_indexes_only_for_policy_chunks() -> None:
    collection_names: list[str] = []
    collection = FakeIndexCollection()
    repository = object.__new__(MongoRepository)
    repository._collection = lambda name: collection_names.append(name) or collection
    repository._run = lambda _operation, action: action()

    repository._ensure_indexes()

    assert collection_names == ["policy_chunks"]
    assert len(collection.indexes) == 2

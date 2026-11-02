from datetime import datetime, timezone

from app.storage.models import PolicyChunk
from app.storage.mongodb import (
    MongoRepository,
    _bson_datetime_precision,
    _normalize_policy_chunk_timestamp,
)


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

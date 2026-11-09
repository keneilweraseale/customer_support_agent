import json
from pathlib import Path

from app.storage import factory
from app.storage.json_store import JsonRepository
from app.storage.models import PolicyChunk


class FakeMongoPolicyStore:
    def __init__(self) -> None:
        self.chunks: list[PolicyChunk] = []
        self.replaced: tuple[str, list[PolicyChunk]] | None = None

    def get_policy_chunks(self) -> list[PolicyChunk]:
        return self.chunks

    def replace_policy_chunks(
        self,
        document_id: str,
        chunks: list[PolicyChunk],
    ) -> None:
        self.replaced = (document_id, chunks)

    def vector_search_policy_chunks(
        self,
        query_vector: list[float],
        embedding_model: str = "mistral-embed",
        limit: int = 5,
        document_versions: dict[str, str] | None = None,
    ) -> list[tuple[PolicyChunk, float]]:
        del query_vector, embedding_model, limit, document_versions
        return []


def test_storage_defaults_to_mongodb(monkeypatch) -> None:
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.setattr(factory, "load_dotenv", lambda **_: None)
    monkeypatch.setattr(
        factory,
        "_configured_repository",
        lambda backend, *_: backend,
    )

    assert factory.repository_from_environment() == "mongodb"


def test_json_repository_allows_tool_data_without_policy_files(
    tmp_path: Path,
) -> None:
    repository = JsonRepository(tmp_path)

    assert repository.get_policy_documents() == []
    assert repository.get_policy_chunks() == []


def test_mongodb_configuration_keeps_operational_records_in_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.storage import mongodb

    json_repository = JsonRepository(tmp_path)
    (tmp_path / "orders.json").write_text("[]", encoding="utf-8")
    policy_store = FakeMongoPolicyStore()

    def create_mongo_repository(*_, **kwargs):
        assert kwargs["search_index_name"] == "policy_bm25_index"
        return policy_store

    monkeypatch.setattr(
        mongodb,
        "MongoRepository",
        create_mongo_repository,
    )
    factory._configured_repository.cache_clear()

    repository = factory._configured_repository(
        "mongodb",
        "mongodb://example",
        "support",
        "policy_vector_index",
        str(tmp_path),
    )

    assert repository.get_orders() == []
    assert repository.get_policy_documents() == json_repository.get_policy_documents()
    assert repository.get_policy_chunks() == []
    repository.replace_policy_chunks("policy-1", [])
    assert policy_store.replaced == ("policy-1", [])
    factory._configured_repository.cache_clear()


def test_mongodb_policy_catalog_uses_the_local_pdf_without_a_metadata_collection(
    tmp_path: Path,
) -> None:
    from app.storage.factory import MongoPolicyRepository
    from app.storage.policy_catalog import PDF_POLICY_DOCUMENT

    policy_path = tmp_path / PDF_POLICY_DOCUMENT.source
    policy_path.parent.mkdir(parents=True)
    policy_path.write_bytes(b"approved source")

    repository = MongoPolicyRepository(tmp_path, FakeMongoPolicyStore())

    assert repository.get_policy_documents() == [PDF_POLICY_DOCUMENT]

from functools import lru_cache
import os
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv

from app.storage.json_store import DataStoreError, JsonRepository
from app.storage.models import PolicyChunk, PolicyDocument
from app.storage.policy_catalog import PDF_POLICY_DOCUMENT
from app.storage.repository import SupportRepository


class MongoPolicyStore(Protocol):
    def get_policy_chunks(self) -> list[PolicyChunk]: ...

    def replace_policy_chunks(
        self,
        document_id: str,
        chunks: list[PolicyChunk],
    ) -> None: ...

    def vector_search_policy_chunks(
        self,
        query_vector: list[float],
        embedding_model: str = ...,
        limit: int = ...,
        document_versions: dict[str, str] | None = ...,
    ) -> list[tuple[PolicyChunk, float]]: ...

    def bm25_search_policy_chunks(
        self,
        query: str,
        limit: int,
        document_versions: dict[str, str] | None = ...,
    ) -> list[PolicyChunk]: ...


class MongoPolicyRepository(JsonRepository):
    def __init__(
        self,
        data_directory: Path,
        policy_repository: MongoPolicyStore,
    ) -> None:
        super().__init__(data_directory)
        self._policy_repository = policy_repository
        self._data_directory = data_directory

    def get_policy_documents(self) -> list[PolicyDocument]:
        documents = super().get_policy_documents()
        if any(
            document.document_id == PDF_POLICY_DOCUMENT.document_id
            for document in documents
        ):
            return documents
        policy_path = self._data_directory / PDF_POLICY_DOCUMENT.source
        return (
            [*documents, PDF_POLICY_DOCUMENT]
            if policy_path.is_file()
            else documents
        )

    def get_policy_chunks(self) -> list[PolicyChunk]:
        return self._policy_repository.get_policy_chunks()

    def replace_policy_chunks(
        self,
        document_id: str,
        chunks: list[PolicyChunk],
    ) -> None:
        self._policy_repository.replace_policy_chunks(document_id, chunks)

    def vector_search_policy_chunks(
        self,
        query_vector: list[float],
        embedding_model: str,
        limit: int,
        document_versions: dict[str, str] | None = None,
    ) -> list[tuple[PolicyChunk, float]]:
        return self._policy_repository.vector_search_policy_chunks(
            query_vector,
            embedding_model,
            limit,
            document_versions,
        )

    def bm25_search_policy_chunks(
        self,
        query: str,
        limit: int,
        document_versions: dict[str, str] | None = None,
    ) -> list[PolicyChunk]:
        return self._policy_repository.bm25_search_policy_chunks(
            query,
            limit,
            document_versions,
        )


@lru_cache(maxsize=1)
def _configured_repository(
    backend: str,
    uri: str,
    database_name: str,
    vector_index_name: str,
    data_directory: str,
    search_index_name: str = "policy_bm25_index",
) -> SupportRepository:
    if backend == "json":
        return JsonRepository(Path(data_directory))
    if backend == "mongodb":
        from app.storage.mongodb import MongoRepository

        if not uri:
            raise DataStoreError("MONGODB_URI is required when STORAGE_BACKEND=mongodb.")
        if not database_name:
            raise DataStoreError(
                "MONGODB_DATABASE is required when STORAGE_BACKEND=mongodb."
            )
        policy_repository = MongoRepository(
            uri,
            database_name,
            vector_index_name,
            search_index_name=search_index_name,
        )
        return MongoPolicyRepository(Path(data_directory), policy_repository)
    raise DataStoreError("STORAGE_BACKEND must be either 'json' or 'mongodb'.")


def repository_from_environment(
    data_directory: Path | None = None,
) -> SupportRepository:
    load_dotenv(
        dotenv_path=Path(__file__).resolve().parents[2] / ".env",
        override=False,
    )
    backend = os.environ.get("STORAGE_BACKEND", "mongodb").strip().casefold()
    uri = os.environ.get("MONGODB_URI", "").strip()
    database_name = os.environ.get("MONGODB_DATABASE", "").strip()
    vector_index_name = os.environ.get(
        "MONGODB_VECTOR_INDEX",
        "policy_vector_index",
    ).strip()
    search_index_name = os.environ.get(
        "MONGODB_BM25_INDEX",
        "policy_bm25_index",
    ).strip()
    directory = data_directory or Path(
        os.environ.get(
            "JSON_DATA_DIRECTORY",
            str(Path(__file__).resolve().parents[2] / "data"),
        )
    )
    return _configured_repository(
        backend,
        uri,
        database_name,
        vector_index_name,
        str(directory.resolve()),
        search_index_name,
    )

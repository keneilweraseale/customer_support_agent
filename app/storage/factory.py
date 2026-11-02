from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv

from app.storage.json_store import DataStoreError, JsonRepository
from app.storage.repository import SupportRepository


@lru_cache(maxsize=1)
def _configured_repository(
    backend: str,
    uri: str,
    database_name: str,
    vector_index_name: str,
    data_directory: str,
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
        return MongoRepository(uri, database_name, vector_index_name)
    raise DataStoreError("STORAGE_BACKEND must be either 'json' or 'mongodb'.")


def repository_from_environment(
    data_directory: Path | None = None,
) -> SupportRepository:
    load_dotenv(
        dotenv_path=Path(__file__).resolve().parents[2] / ".env",
        override=False,
    )
    backend = os.environ.get("STORAGE_BACKEND", "json").strip().casefold()
    uri = os.environ.get("MONGODB_URI", "").strip()
    database_name = os.environ.get("MONGODB_DATABASE", "").strip()
    vector_index_name = os.environ.get(
        "MONGODB_VECTOR_INDEX",
        "policy_vector_index",
    ).strip()
    directory = data_directory or Path(__file__).resolve().parents[2] / "data"
    return _configured_repository(
        backend,
        uri,
        database_name,
        vector_index_name,
        str(directory.resolve()),
    )

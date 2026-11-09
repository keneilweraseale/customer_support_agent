from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from app.rag.providers import (
    EmbeddingError,
    MistralTextEmbedder,
)


def test_mistral_embedding_timeout_is_reported_as_embedding_error() -> None:
    embedder = MistralTextEmbedder.__new__(MistralTextEmbedder)
    embedder._client = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=Mock(side_effect=httpx.ReadTimeout("timed out"))
        )
    )

    with pytest.raises(EmbeddingError, match="request failed"):
        embedder.embed_documents(["policy text"])

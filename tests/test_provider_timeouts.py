from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from groq import APIConnectionError

from app.rag.providers import (
    EmbeddingError,
    GroqSemanticChunker,
    MistralTextEmbedder,
    SemanticChunkingError,
)


def test_groq_semantic_chunking_timeout_uses_deterministic_fallback_signal() -> None:
    chunker = GroqSemanticChunker.__new__(GroqSemanticChunker)
    chunker._model = "test-model"
    request = httpx.Request("POST", "https://api.groq.com")
    chunker._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=Mock(side_effect=APIConnectionError(request=request))
            )
        )
    )

    with pytest.raises(SemanticChunkingError, match="request failed"):
        chunker.chunk("policy text")


def test_mistral_embedding_timeout_is_reported_as_embedding_error() -> None:
    embedder = MistralTextEmbedder.__new__(MistralTextEmbedder)
    embedder._client = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=Mock(side_effect=httpx.ReadTimeout("timed out"))
        )
    )

    with pytest.raises(EmbeddingError, match="request failed"):
        embedder.embed_documents(["policy text"])

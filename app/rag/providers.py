import json
import logging
import math
import os
from typing import Protocol

import httpx
from groq import APIError as GroqAPIError
from groq import Groq
from mistralai.client import Mistral
from mistralai.client.errors import MistralError

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "mistral-embed"
PROVIDER_TIMEOUT_MS = 15_000


class SemanticChunkingError(RuntimeError):
    """Raised when Groq cannot return valid source-preserving chunk boundaries."""


class ProviderConfigurationError(RuntimeError):
    """Raised when a required model provider credential is unavailable."""


class EmbeddingError(RuntimeError):
    """Raised when Mistral does not return usable embeddings."""


class SemanticChunker(Protocol):
    def chunk(self, text: str) -> list[str]: ...


class TextEmbedder(Protocol):
    @property
    def model_name(self) -> str: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class GroqSemanticChunker:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = Groq(api_key=api_key, timeout=PROVIDER_TIMEOUT_MS / 1000, max_retries=0)
        self._model = model

    def chunk(self, text: str) -> list[str]:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Split the provided source text into semantically coherent "
                            "chunks. Return only JSON with a `chunks` array of strings. "
                            "Every character, punctuation mark, and whitespace character "
                            "from the source must appear exactly once, in its original "
                            "order. Do not rewrite, add, omit, or normalize any text. "
                            "Concatenating the returned chunks must reproduce the source "
                            "exactly."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps({"source_text": text}, ensure_ascii=False),
                    },
                ],
            )
        except GroqAPIError as exc:
            raise SemanticChunkingError("Groq semantic chunking request failed.") from exc

        if not response.choices or response.choices[0].message.content is None:
            raise SemanticChunkingError("Groq returned no semantic chunking result.")
        try:
            result = json.loads(response.choices[0].message.content)
        except json.JSONDecodeError as exc:
            raise SemanticChunkingError("Groq returned invalid JSON for chunking.") from exc

        chunks = result.get("chunks") if isinstance(result, dict) else None
        if (
            not isinstance(chunks, list)
            or not chunks
            or any(not isinstance(chunk, str) or not chunk for chunk in chunks)
            or "".join(chunks) != text
        ):
            raise SemanticChunkingError(
                "Groq chunk output did not preserve the source text exactly."
            )
        return chunks


class MistralTextEmbedder:
    def __init__(self, api_key: str) -> None:
        self._client = Mistral(api_key=api_key, timeout_ms=PROVIDER_TIMEOUT_MS)

    @property
    def model_name(self) -> str:
        return EMBEDDING_MODEL

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise EmbeddingError("Cannot embed an empty document or chunk.")
        try:
            response = self._client.embeddings.create(
                model=EMBEDDING_MODEL,
                inputs=texts,
            )
        except (MistralError, httpx.HTTPError) as exc:
            raise EmbeddingError("Mistral embedding request failed.") from exc

        embeddings = [
            [float(value) for value in item.embedding]
            for item in sorted(response.data, key=lambda item: item.index)
        ]
        if len(embeddings) != len(texts):
            raise EmbeddingError("Mistral returned a different number of embeddings than inputs.")
        if any(
            not embedding
            or any(not math.isfinite(value) for value in embedding)
            for embedding in embeddings
        ):
            raise EmbeddingError("Mistral returned an empty or non-finite embedding.")
        dimensions = {len(embedding) for embedding in embeddings}
        if len(dimensions) != 1:
            raise EmbeddingError("Mistral returned embeddings with inconsistent dimensions.")
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        embeddings = self.embed_documents([text])
        return embeddings[0]


class UnavailableTextEmbedder:
    model_name = EMBEDDING_MODEL

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        del texts
        raise EmbeddingError("MISTRAL_API_KEY is not configured.")

    def embed_query(self, text: str) -> list[float]:
        del text
        raise EmbeddingError("MISTRAL_API_KEY is not configured.")


class UnavailableSemanticChunker:
    def chunk(self, text: str) -> list[str]:
        del text
        raise SemanticChunkingError("GROQ_API_KEY is not configured.")


def embedder_from_environment(required: bool = True) -> TextEmbedder:
    mistral_key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if mistral_key:
        return MistralTextEmbedder(mistral_key)
    if not required:
        return UnavailableTextEmbedder()
    else:
        raise ProviderConfigurationError("MISTRAL_API_KEY is not configured.")


def providers_from_environment() -> tuple[SemanticChunker, TextEmbedder]:
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    groq_model = os.environ.get("GROQ_MODEL", "").strip()

    if groq_key and groq_model:
        chunker: SemanticChunker = GroqSemanticChunker(groq_key, groq_model)
    else:
        if groq_key and not groq_model:
            logger.warning("GROQ_MODEL is not configured; using deterministic chunking.")
        chunker = UnavailableSemanticChunker()

    return chunker, embedder_from_environment()

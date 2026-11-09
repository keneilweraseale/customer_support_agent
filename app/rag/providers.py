import math
import os
import re
import statistics
from typing import Protocol

import httpx
from mistralai.client import Mistral
from mistralai.client.errors import MistralError

EMBEDDING_MODEL = "mistral-embed"
PROVIDER_TIMEOUT_MS = 15_000
DEFAULT_SEMANTIC_CHUNK_MAX_CHARS = 1200


class SemanticChunkingError(RuntimeError):
    """Raised when semantic chunking cannot produce source-preserving boundaries."""


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


class EmbeddingSemanticChunker:
    def __init__(
        self,
        embedder: TextEmbedder,
        max_chars: int = DEFAULT_SEMANTIC_CHUNK_MAX_CHARS,
    ) -> None:
        if max_chars < 1:
            raise ValueError("max_chars must be positive.")
        self._embedder = embedder
        self._max_chars = max_chars

    def chunk(self, text: str) -> list[str]:
        if not text:
            return []

        sentences = self._split_sentences(text)
        if len(sentences) < 2:
            return sentences

        embeddings: list[list[float]] = []
        for start in range(0, len(sentences), 64):
            embeddings.extend(
                self._embedder.embed_documents(
                    [sentence.strip() for sentence in sentences[start : start + 64]]
                )
            )
        if len(embeddings) != len(sentences):
            raise SemanticChunkingError(
                "Sentence embedding count does not match the source sentences."
            )

        similarities = [
            self._cosine_similarity(left, right)
            for left, right in zip(embeddings, embeddings[1:])
        ]
        threshold = statistics.mean(similarities) - statistics.pstdev(similarities)
        min_chunk_chars = max(1, self._max_chars // 3)

        chunks: list[str] = []
        start = 0
        while start < len(sentences):
            char_count = len(sentences[start])
            end = len(sentences)
            for boundary in range(start, len(sentences) - 1):
                if (
                    char_count >= min_chunk_chars
                    and similarities[boundary] < threshold
                ):
                    end = boundary + 1
                    break

                next_char_count = char_count + len(sentences[boundary + 1])
                if next_char_count > self._max_chars:
                    end = min(
                        range(start + 1, boundary + 2),
                        key=lambda candidate: similarities[candidate - 1],
                    )
                    break
                char_count = next_char_count

            chunks.append("".join(sentences[start:end]))
            start = end

        if "".join(chunks) != text:
            raise SemanticChunkingError(
                "Semantic chunks do not preserve the source text exactly."
            )
        return chunks

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        boundaries: list[int] = []
        start = 0
        for match in re.finditer(r"(?<=[.!?])(?=\s)|\n{2,}", text):
            boundary = match.start()
            if match.group().startswith("\n"):
                boundary = match.end()
            else:
                while boundary < len(text) and text[boundary].isspace():
                    boundary += 1
            if boundary > start and text[start:boundary].strip():
                boundaries.append(boundary)
                start = boundary

        spans = [0, *boundaries, len(text)]
        return [
            text[left:right]
            for left, right in zip(spans, spans[1:])
            if text[left:right].strip()
        ]

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            raise SemanticChunkingError(
                "Sentence embeddings have inconsistent dimensions."
            )
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


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


def embedder_from_environment(required: bool = True) -> TextEmbedder:
    mistral_key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if mistral_key:
        return MistralTextEmbedder(mistral_key)
    if not required:
        return UnavailableTextEmbedder()
    else:
        raise ProviderConfigurationError("MISTRAL_API_KEY is not configured.")


def providers_from_environment() -> tuple[SemanticChunker, TextEmbedder]:
    embedder = embedder_from_environment()
    return EmbeddingSemanticChunker(embedder), embedder

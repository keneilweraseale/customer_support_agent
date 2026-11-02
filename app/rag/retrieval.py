import math
import re
from dataclasses import dataclass
from typing import Protocol

from rank_bm25 import BM25Okapi

from app.rag.providers import EmbeddingError, TextEmbedder
from app.storage.models import PolicyChunk, PolicyDocument

RRF_K = 60
DEFAULT_TOP_K = 5
MIN_COSINE_SIMILARITY = 0.25
TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


class PolicySearchRepository(Protocol):
    def get_policy_documents(self) -> list[PolicyDocument]: ...

    def get_policy_chunks(self) -> list[PolicyChunk]: ...


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: PolicyChunk
    score: float
    vector_score: float | None
    vector_available: bool


@dataclass(frozen=True)
class HybridSearchResult:
    results: list[RetrievedChunk]
    vector_available: bool
    vector_error: str | None
    bm25_available: bool


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.casefold())


def cosine_similarity(left: list[float], right: list[float]) -> float | None:
    if not left or len(left) != len(right):
        return None
    if any(not math.isfinite(value) for value in (*left, *right)):
        return None
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return None
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )


class HybridPolicyRetriever:
    def __init__(
        self,
        repository: PolicySearchRepository,
        embedder: TextEmbedder,
        top_k: int = DEFAULT_TOP_K,
        rrf_k: int = RRF_K,
        min_cosine_similarity: float = MIN_COSINE_SIMILARITY,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be positive.")
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive.")
        if not -1 <= min_cosine_similarity <= 1:
            raise ValueError("min_cosine_similarity must be between -1 and 1.")
        self._repository = repository
        self._embedder = embedder
        self._top_k = top_k
        self._rrf_k = rrf_k
        self._min_cosine_similarity = min_cosine_similarity

    def search(self, query: str) -> HybridSearchResult:
        query_tokens = tokenize(query)
        if not query_tokens:
            return HybridSearchResult([], False, "empty_query", False)

        documents = {
            document.document_id: document
            for document in self._repository.get_policy_documents()
            if document.approved
        }
        approved_chunks = [
            chunk
            for chunk in self._repository.get_policy_chunks()
            if self._is_approved_and_current(chunk, documents)
        ]
        if not approved_chunks:
            return HybridSearchResult([], False, "no_valid_approved_chunks", False)

        query_vector: list[float] | None = None
        vector_error: str | None = None
        try:
            candidate_vector = self._embedder.embed_query(query)
            if candidate_vector and all(math.isfinite(value) for value in candidate_vector):
                query_vector = candidate_vector
            else:
                vector_error = "invalid_query_embedding"
        except EmbeddingError:
            vector_error = "query_embedding_unavailable"

        bm25_scores = self._bm25_scores(approved_chunks, query_tokens)
        bm25_ranked = [
            index
            for index in sorted(
                range(len(approved_chunks)),
                key=lambda item: (-bm25_scores[item], item),
            )
            if set(query_tokens).intersection(tokenize(approved_chunks[index].text))
        ][: self._top_k]

        vector_scores: dict[int, float] = {}
        valid_vector_scores: dict[int, float] = {}
        if query_vector is not None:
            vector_search = getattr(
                self._repository,
                "vector_search_policy_chunks",
                None,
            )
            if callable(vector_search):
                document_versions = {
                    document.document_id: document.updated_at.isoformat()
                    for document in documents.values()
                }
                indexed_scores = {
                    chunk.chunk_id: score
                    for chunk, score in vector_search(
                        query_vector,
                        self._embedder.model_name,
                        self._top_k,
                        document_versions,
                    )
                }
                valid_vector_scores = {
                    index: indexed_scores[chunk.chunk_id]
                    for index, chunk in enumerate(approved_chunks)
                    if chunk.chunk_id in indexed_scores
                    and chunk.embedding_model == self._embedder.model_name
                }
            else:
                valid_vector_scores = {
                    index: score
                    for index, chunk in enumerate(approved_chunks)
                    if chunk.embedding_model == self._embedder.model_name
                    if (score := cosine_similarity(query_vector, chunk.embedding)) is not None
                }
            vector_scores = {
                index: score
                for index, score in valid_vector_scores.items()
                if score >= self._min_cosine_similarity
            }
        vector_ranked = sorted(
            vector_scores,
            key=lambda index: (-vector_scores[index], index),
        )[: self._top_k]

        rrf_scores: dict[int, float] = {}
        for ranking in (vector_ranked, bm25_ranked):
            for rank, index in enumerate(ranking, start=1):
                rrf_scores[index] = rrf_scores.get(index, 0.0) + (
                    1.0 / (self._rrf_k + rank)
                )

        ordered_indices = sorted(
            rrf_scores,
            key=lambda index: (-rrf_scores[index], approved_chunks[index].chunk_id),
        )[: self._top_k]
        retrieved = [
            RetrievedChunk(
                chunk=approved_chunks[index],
                score=rrf_scores[index],
                vector_score=valid_vector_scores.get(index),
                vector_available=index in valid_vector_scores,
            )
            for index in ordered_indices
        ]
        return HybridSearchResult(
            results=retrieved,
            vector_available=bool(valid_vector_scores),
            vector_error=(
                vector_error
                or (
                    "no_valid_chunk_embeddings"
                    if query_vector is not None and not valid_vector_scores
                    else None
                )
            ),
            bm25_available=bool(bm25_ranked),
        )

    def _is_approved_and_current(
        self,
        chunk: PolicyChunk,
        approved_documents: dict[str, PolicyDocument],
    ) -> bool:
        document = approved_documents.get(chunk.document_id)
        if document is None or chunk.metadata.get("approved") is not True:
            return False
        return chunk.metadata.get("updated_at") == document.updated_at.isoformat()

    def _bm25_scores(
        self,
        chunks: list[PolicyChunk],
        query_tokens: list[str],
    ) -> list[float]:
        tokenized_corpus = [tokenize(chunk.text) for chunk in chunks]
        if not any(tokenized_corpus):
            return [0.0] * len(chunks)
        return [float(score) for score in BM25Okapi(tokenized_corpus).get_scores(query_tokens)]

from datetime import datetime, timezone

import pytest

from app.rag.generation import HUMAN_SUPPORT_MARKER, GenerationError
from app.rag.retrieval import (
    HybridPolicyRetriever,
    cosine_similarity,
)
from app.rag.service import NO_EVIDENCE_ANSWER, PolicyAnswerService
from app.storage.json_store import DataStoreError, JsonRepository
from app.storage.models import PolicyChunk, PolicyDocument

UPDATED_AT = datetime(2026, 10, 22, tzinfo=timezone.utc)


def make_document(
    document_id: str = "refund-policy",
    approved: bool = True,
) -> PolicyDocument:
    return PolicyDocument(
        document_id=document_id,
        title=f"Title for {document_id}",
        category="refunds",
        source=f"policies/{document_id}.md",
        approved=approved,
        updated_at=UPDATED_AT,
    )


def make_chunk(
    chunk_id: str,
    document: PolicyDocument,
    text: str,
    embedding: list[float],
    *,
    updated_at: datetime | None = None,
    approved: bool | None = None,
) -> PolicyChunk:
    return PolicyChunk(
        chunk_id=chunk_id,
        document_id=document.document_id,
        title=document.title,
        text=text,
        embedding=embedding,
        metadata={
            "category": document.category,
            "approved": document.approved if approved is None else approved,
            "source": document.source,
            "updated_at": (updated_at or document.updated_at).isoformat(),
            "chunk_index": 0,
        },
        token_count=len(text.split()),
        embedding_model="mistral-embed",
    )


class MemoryRepository:
    def __init__(
        self,
        documents: list[PolicyDocument],
        chunks: list[PolicyChunk],
    ) -> None:
        self.documents = documents
        self.chunks = chunks

    def get_policy_documents(self) -> list[PolicyDocument]:
        return self.documents

    def get_policy_chunks(self) -> list[PolicyChunk]:
        return self.chunks


class FakeEmbedder:
    model_name = "mistral-embed"

    def __init__(self, vector: list[float]) -> None:
        self.vector = vector
        self.queries: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.vector for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return self.vector


class FailingEmbedder(FakeEmbedder):
    def embed_query(self, text: str) -> list[float]:
        del text
        from app.rag.providers import EmbeddingError

        raise EmbeddingError("simulated embedding outage")


class FakeGenerator:
    def __init__(self, answer: str = "Based on the refund policy, contact support.") -> None:
        self.answer_text = answer
        self.calls: list[tuple[str, list[str]]] = []

    def generate(self, question, evidence) -> str:
        self.calls.append((question, [item.chunk.chunk_id for item in evidence]))
        return self.answer_text


class FailingGenerator:
    def generate(self, question, evidence) -> str:
        del question, evidence
        raise GenerationError("simulated model outage")


def test_cosine_similarity_handles_valid_and_unusable_vectors() -> None:
    assert cosine_similarity([1.0, 0.0], [2.0, 0.0]) == 1.0
    assert cosine_similarity([1.0], [1.0, 0.0]) is None
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) is None
    assert cosine_similarity([float("nan")], [1.0]) is None


def test_hybrid_retrieval_uses_vector_and_bm25_and_deduplicates() -> None:
    document = make_document()
    chunks = [
        make_chunk("refund-1", document, "refund return within thirty days", [1.0, 0.0]),
        make_chunk("shipping-1", document, "shipping delivery charges", [0.0, 1.0]),
    ]
    embedder = FakeEmbedder([1.0, 0.0])
    retriever = HybridPolicyRetriever(
        MemoryRepository([document], chunks),
        embedder,
        min_cosine_similarity=0.1,
    )

    result = retriever.search("refund return")

    assert result.vector_available is True
    assert result.bm25_available is True
    assert [item.chunk.chunk_id for item in result.results] == ["refund-1"]
    assert result.results[0].vector_score == 1.0
    assert embedder.queries == ["refund return"]


def test_bm25_continues_when_mongodb_vector_search_fails(caplog) -> None:
    document = make_document()
    chunk = make_chunk("refund-1", document, "refund within thirty days", [1.0, 0.0])

    class UnavailableAtlasVectorRepository(MemoryRepository):
        def vector_search_policy_chunks(
            self,
            query_vector,
            embedding_model,
            limit,
            document_versions,
        ):
            del query_vector, embedding_model, limit, document_versions
            raise DataStoreError("Atlas index is missing a required filter field.")

    retriever = HybridPolicyRetriever(
        UnavailableAtlasVectorRepository([document], [chunk]),
        FakeEmbedder([1.0, 0.0]),
    )

    with caplog.at_level("ERROR", logger="app.rag.retrieval"):
        result = retriever.search("refund")

    assert result.bm25_available is True
    assert result.vector_available is False
    assert result.vector_error == "vector_search_unavailable"
    assert [item.chunk.chunk_id for item in result.results] == ["refund-1"]
    assert "continuing with BM25" in caplog.text


def test_bm25_continues_when_chunks_have_no_embeddings() -> None:
    document = make_document()
    chunk = make_chunk("refund-1", document, "refund within thirty days", [])
    retriever = HybridPolicyRetriever(
        MemoryRepository([document], [chunk]),
        FakeEmbedder([1.0, 0.0]),
    )

    result = retriever.search("refund")

    assert result.vector_available is False
    assert result.vector_error == "no_valid_chunk_embeddings"
    assert result.bm25_available is True
    assert [item.chunk.chunk_id for item in result.results] == ["refund-1"]


def test_bm25_continues_when_query_embedding_provider_fails() -> None:
    document = make_document()
    chunk = make_chunk("refund-1", document, "refund within thirty days", [1.0, 0.0])
    retriever = HybridPolicyRetriever(
        MemoryRepository([document], [chunk]),
        FailingEmbedder([1.0, 0.0]),
    )

    result = retriever.search("refund")

    assert result.vector_available is False
    assert result.vector_error == "query_embedding_unavailable"
    assert result.bm25_available is True
    assert result.results[0].chunk.chunk_id == "refund-1"


def test_retrieval_excludes_unapproved_and_outdated_documents() -> None:
    current_document = make_document("current")
    unapproved_document = make_document("unapproved", approved=False)
    old_timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    chunks = [
        make_chunk("current-1", current_document, "current refund policy", [1.0, 0.0]),
        make_chunk(
            "draft-1",
            unapproved_document,
            "refund not approved",
            [1.0, 0.0],
            approved=False,
        ),
        make_chunk(
            "old-1",
            current_document,
            "old refund policy",
            [1.0, 0.0],
            updated_at=old_timestamp,
        ),
    ]
    retriever = HybridPolicyRetriever(
        MemoryRepository([current_document, unapproved_document], chunks),
        FakeEmbedder([1.0, 0.0]),
        min_cosine_similarity=0.1,
    )

    result = retriever.search("refund")

    assert [item.chunk.chunk_id for item in result.results] == ["current-1"]


def test_no_match_returns_empty_results_instead_of_zero_score_candidates() -> None:
    document = make_document()
    chunk = make_chunk("refund-1", document, "refund within thirty days", [0.0, 1.0])
    retriever = HybridPolicyRetriever(
        MemoryRepository([document], [chunk]),
        FakeEmbedder([1.0, 0.0]),
        min_cosine_similarity=0.5,
    )

    result = retriever.search("quantum telescope")

    assert result.results == []
    assert result.vector_available is True
    assert result.bm25_available is False


def test_retrieval_uses_repository_vector_search_when_available() -> None:
    document = make_document()
    chunks = [
        make_chunk("refund-1", document, "refund return within thirty days", [0.0, 1.0]),
        make_chunk("shipping-1", document, "shipping delivery charges", [1.0, 0.0]),
    ]

    class AtlasVectorRepository(MemoryRepository):
        def __init__(self) -> None:
            super().__init__([document], chunks)
            self.search_arguments = None

        def vector_search_policy_chunks(
            self,
            query_vector,
            embedding_model,
            limit,
            document_versions,
        ):
            self.search_arguments = (
                query_vector,
                embedding_model,
                limit,
                document_versions,
            )
            return [(chunks[1], 0.8)]

    repository = AtlasVectorRepository()
    retriever = HybridPolicyRetriever(
        repository,
        FakeEmbedder([0.0, 1.0]),
        top_k=2,
        min_cosine_similarity=0.1,
    )

    result = retriever.search("refund")

    assert repository.search_arguments == (
        [0.0, 1.0],
        "mistral-embed",
        2,
        {"refund-policy": UPDATED_AT.isoformat()},
    )
    assert result.vector_available is True
    assert next(
        item.vector_score for item in result.results if item.chunk.chunk_id == "shipping-1"
    ) == 0.8


def test_service_generates_grounded_answer_with_source_metadata() -> None:
    document = make_document()
    chunks = [
        make_chunk("refund-1", document, "refund within thirty days", [1.0, 0.0]),
        make_chunk("refund-2", document, "return packaging requirements", [0.9, 0.1]),
    ]
    generator = FakeGenerator("Returns are available within thirty days.")
    service = PolicyAnswerService(
        HybridPolicyRetriever(
            MemoryRepository([document], chunks),
            FakeEmbedder([1.0, 0.0]),
            min_cosine_similarity=0.1,
            top_k=2,
        ),
        generator,
    )

    result = service.answer("What is the refund period?")

    assert result.answer == "Returns are available within thirty days."
    assert result.route == "rag"
    assert result.sources == [
        {
            "document_id": "refund-policy",
            "title": "Title for refund-policy",
            "chunk_id": "refund-1",
        },
        {
            "document_id": "refund-policy",
            "title": "Title for refund-policy",
            "chunk_id": "refund-2",
        },
    ]
    assert generator.calls == [
        ("What is the refund period?", ["refund-1", "refund-2"])
    ]


def test_service_marks_model_indicated_unresolved_answer_for_escalation() -> None:
    document = make_document()
    chunk = make_chunk("refund-1", document, "refund within thirty days", [])
    service = PolicyAnswerService(
        HybridPolicyRetriever(
            MemoryRepository([document], [chunk]),
            FakeEmbedder([1.0, 0.0]),
        ),
        FakeGenerator(f"{HUMAN_SUPPORT_MARKER}I can’t verify this exception."),
    )

    result = service.answer("Can I get a refund outside the return period?")

    assert result.answer == "I can’t verify this exception."
    assert result.needs_human_support is True


def test_service_uses_transparent_fallback_when_evidence_is_missing() -> None:
    document = make_document()
    chunk = make_chunk("refund-1", document, "refund within thirty days", [])
    generator = FakeGenerator()
    service = PolicyAnswerService(
        HybridPolicyRetriever(
            MemoryRepository([document], [chunk]),
            FakeEmbedder([1.0, 0.0]),
        ),
        generator,
    )

    result = service.answer("What is the moon made of?")

    assert result.answer == NO_EVIDENCE_ANSWER
    assert result.sources == []
    assert result.needs_human_support is True
    assert generator.calls == []


def test_controlled_draft_policy_document_is_not_retrieved() -> None:
    repository = JsonRepository()
    document = next(
        item
        for item in repository.get_policy_documents()
        if item.document_id == "customer-support-policies"
    )
    assert document.approved is False

    result = HybridPolicyRetriever(
        repository,
        FakeEmbedder([1.0, 0.0]),
    ).search("Can I return an item after 30 days?")

    assert result.results == []
    assert result.vector_error == "no_valid_approved_chunks"


def test_service_handles_generation_failure_without_inventing_answer() -> None:
    document = make_document()
    chunk = make_chunk("refund-1", document, "refund within thirty days", [])
    service = PolicyAnswerService(
        HybridPolicyRetriever(
            MemoryRepository([document], [chunk]),
            FakeEmbedder([1.0, 0.0]),
        ),
        FailingGenerator(),
    )

    result = service.answer("What is the refund period?")

    assert "can’t generate a reliable answer right now" in result.answer
    assert result.needs_human_support is True
    assert result.sources[0]["chunk_id"] == "refund-1"


def test_service_replaces_unverified_answer_with_safe_escalation() -> None:
    document = make_document()
    chunk = make_chunk("refund-1", document, "refund within thirty days", [])

    class RejectingVerifier:
        def is_supported(self, question, answer, evidence):
            del question, answer, evidence
            return False

    service = PolicyAnswerService(
        HybridPolicyRetriever(
            MemoryRepository([document], [chunk]),
            FakeEmbedder([1.0, 0.0]),
        ),
        FakeGenerator("Refunds are always available."),
        RejectingVerifier(),
    )

    result = service.answer("What is the refund policy?")

    assert "couldn’t verify a reliable answer" in result.answer
    assert result.needs_human_support is True


def test_service_escalates_when_answer_verification_fails() -> None:
    document = make_document()
    chunk = make_chunk("refund-1", document, "refund within thirty days", [])

    class FailingVerifier:
        def is_supported(self, question, answer, evidence):
            del question, answer, evidence
            raise GenerationError("verification service unavailable")

    service = PolicyAnswerService(
        HybridPolicyRetriever(
            MemoryRepository([document], [chunk]),
            FakeEmbedder([1.0, 0.0]),
        ),
        FakeGenerator("Returns are accepted within thirty days."),
        FailingVerifier(),
    )

    result = service.answer("What is the refund policy?")

    assert "can’t generate a reliable answer right now" in result.answer
    assert result.needs_human_support is True


def test_top_level_policy_query_returns_unknown_without_model_keys(
    monkeypatch,
) -> None:
    import app.rag.service as service_module

    document = make_document()
    chunk = make_chunk("refund-1", document, "refund within thirty days", [])
    monkeypatch.setattr(
        service_module,
        "repository_from_environment",
        lambda: MemoryRepository([document], [chunk]),
    )
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)

    result = service_module.answer_policy_question("How does a telescope work?")

    assert result.answer == NO_EVIDENCE_ANSWER
    assert result.sources == []


def test_top_level_policy_query_requires_groq_when_evidence_is_found(
    monkeypatch,
) -> None:
    import app.rag.service as service_module
    from app.rag.providers import ProviderConfigurationError

    document = make_document()
    chunk = make_chunk("refund-1", document, "refund within thirty days", [])
    monkeypatch.setattr(
        service_module,
        "repository_from_environment",
        lambda: MemoryRepository([document], [chunk]),
    )
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)

    with pytest.raises(ProviderConfigurationError, match="GROQ_API_KEY and GROQ_MODEL"):
        service_module.answer_policy_question("What is the refund policy?")


def test_unusable_embedding_dimension_does_not_block_keyword_search() -> None:
    document = make_document()
    chunk = make_chunk("refund-1", document, "refund policy", [1.0, 0.0])
    retriever = HybridPolicyRetriever(
        MemoryRepository([document], [chunk]),
        FakeEmbedder([1.0, 0.0, 0.0]),
    )

    result = retriever.search("refund")

    assert result.vector_available is False
    assert result.vector_error == "no_valid_chunk_embeddings"
    assert result.bm25_available is True
    assert result.results[0].chunk.chunk_id == "refund-1"


def test_different_embedding_model_is_excluded_from_vector_search_only() -> None:
    document = make_document()
    chunk = make_chunk("refund-1", document, "refund policy", [1.0, 0.0])
    chunk.embedding_model = "old-embedding-model"
    retriever = HybridPolicyRetriever(
        MemoryRepository([document], [chunk]),
        FakeEmbedder([1.0, 0.0]),
    )

    result = retriever.search("refund")

    assert result.vector_available is False
    assert result.vector_error == "no_valid_chunk_embeddings"
    assert result.bm25_available is True
    assert result.results[0].chunk.chunk_id == "refund-1"

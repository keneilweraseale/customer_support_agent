import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pypdf.errors import PdfReadError

from app.rag.ingestion import (
    PolicyIngestor,
    clean_text,
    deterministic_chunks,
)
from app.rag.providers import (
    EmbeddingError,
    GroqSemanticChunker,
    MistralTextEmbedder,
    ProviderConfigurationError,
    SemanticChunkingError,
    UnavailableSemanticChunker,
    providers_from_environment,
)
from app.storage.json_store import DataStoreError, JsonRepository
from app.storage.models import PolicyChunk

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data"


class FakeSemanticChunker:
    def __init__(self, chunk_function=None) -> None:
        self._chunk_function = chunk_function or (
            lambda text: _split_in_half_preserving_text(text)
        )

    def chunk(self, text: str) -> list[str]:
        return self._chunk_function(text)


class FailingSemanticChunker:
    def chunk(self, text: str) -> list[str]:
        del text
        raise SemanticChunkingError("simulated provider unavailable")


class FakeEmbedder:
    model_name = "fake-test-embedding"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[float(index + 1), 0.25, -0.5] for index, _ in enumerate(texts)]


class InvalidEmbedder:
    model_name = "fake-test-embedding"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class StubMistralClient:
    def __init__(self, embeddings) -> None:
        self.embeddings = embeddings
        self.last_inputs = None
        self.last_model = None

    def create_embeddings(self, model, inputs):
        self.last_model = model
        self.last_inputs = inputs
        return self.embeddings


def _split_in_half_preserving_text(text: str) -> list[str]:
    midpoint = len(text) // 2
    boundary = text.find(" ", midpoint)
    if boundary < 0:
        boundary = midpoint
    if boundary <= 0 or boundary >= len(text):
        return [text]
    return [text[: boundary + 1], text[boundary + 1 :]]


@pytest.fixture
def policy_data(tmp_path: Path) -> tuple[JsonRepository, Path]:
    (tmp_path / "policies").mkdir()
    (tmp_path / "policy_chunks.json").write_text("[]\n", encoding="utf-8")
    documents = [
        {
            "document_id": "demo-refund-policy",
            "title": "Fictional Demo Refund Guidance",
            "category": "refunds",
            "source": "policies/demo-refund-policy.md",
            "approved": True,
            "updated_at": "2026-10-22T00:00:00Z",
        },
        {
            "document_id": "demo-contact-information",
            "title": "Fictional Demo Contact Information",
            "category": "contact",
            "source": "policies/demo-contact-information.md",
            "approved": True,
            "updated_at": "2026-10-22T00:00:00Z",
        },
        {
            "document_id": "demo-unapproved-shipping-draft",
            "title": "Unapproved Demo Shipping Draft",
            "category": "shipping",
            "source": "policies/demo-unapproved-shipping-draft.md",
            "approved": False,
            "updated_at": "2026-10-22T00:00:00Z",
        },
    ]
    (tmp_path / "policy_documents.json").write_text(
        json.dumps(documents),
        encoding="utf-8",
    )
    for document in documents:
        source_path = tmp_path / document["source"]
        if not source_path.exists():
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(
                f"{document['title']}\n\nTest policy content for ingestion.",
                encoding="utf-8",
            )
    return JsonRepository(tmp_path), tmp_path


def test_clean_text_normalizes_line_endings_and_whitespace() -> None:
    assert clean_text("  One  \r\n\r\n\r\n Two\twords  ") == "One\n\nTwo words"


@pytest.mark.parametrize("max_chars", [1, 8, 30])
def test_deterministic_chunks_preserve_source_and_maximum_size(max_chars: int) -> None:
    source = ("Policy sentence. Another sentence.\n\n" * 9).strip()

    chunks = deterministic_chunks(source, max_chars)

    assert "".join(chunks) == source
    assert all(0 < len(chunk) <= max_chars for chunk in chunks)


def test_deterministic_chunks_rejects_invalid_max_size() -> None:
    with pytest.raises(ValueError, match="positive"):
        deterministic_chunks("text", 0)


def test_ingestion_writes_approved_chunks_with_metadata_and_embeddings(
    policy_data: tuple[JsonRepository, Path],
) -> None:
    repository, data_directory = policy_data
    embedder = FakeEmbedder()
    ingestor = PolicyIngestor(
        repository,
        data_directory,
        FakeSemanticChunker(),
        embedder,
        max_chars=1000,
    )

    result = ingestor.ingest_approved_documents()
    documents = repository.get_policy_documents()
    chunks = repository.get_policy_chunks()

    assert result == {
        "documents_processed": 2,
        "chunks_written": 4,
        "documents_skipped": 1,
    }
    assert len(embedder.calls) == 2
    assert {chunk.document_id for chunk in chunks} == {
        "demo-refund-policy",
        "demo-contact-information",
    }
    assert all(chunk.embedding for chunk in chunks)
    assert all(chunk.embedding_model == "fake-test-embedding" for chunk in chunks)
    assert all(chunk.metadata["approved"] is True for chunk in chunks)
    assert all(chunk.token_count > 0 for chunk in chunks)
    assert all(
        "".join(chunk.text for chunk in chunks if chunk.document_id == document.document_id)
        == clean_text((data_directory / document.source).read_text(encoding="utf-8"))
        for document in documents
        if document.approved
    )


def test_ingestion_falls_back_when_semantic_chunker_fails(
    policy_data: tuple[JsonRepository, Path],
) -> None:
    repository, data_directory = policy_data
    ingestor = PolicyIngestor(
        repository,
        data_directory,
        FailingSemanticChunker(),
        FakeEmbedder(),
        max_chars=64,
    )

    result = ingestor.ingest_approved_documents()

    assert result["chunks_written"] > 2
    assert all(len(chunk.text) <= 64 for chunk in repository.get_policy_chunks())


def test_invalid_semantic_output_falls_back_without_losing_text(
    policy_data: tuple[JsonRepository, Path],
) -> None:
    repository, data_directory = policy_data
    ingestor = PolicyIngestor(
        repository,
        data_directory,
        FakeSemanticChunker(lambda text: [text[:-1], "invented"]),
        FakeEmbedder(),
        max_chars=1000,
    )

    ingestor.ingest_approved_documents()

    refund = next(
        document
        for document in repository.get_policy_documents()
        if document.document_id == "demo-refund-policy"
    )
    chunks = [
        chunk.text
        for chunk in repository.get_policy_chunks()
        if chunk.document_id == refund.document_id
    ]
    assert "".join(chunks) == clean_text(
        (data_directory / refund.source).read_text(encoding="utf-8")
    )


def test_ingestion_merges_whitespace_only_semantic_chunks(
    policy_data: tuple[JsonRepository, Path],
) -> None:
    repository, data_directory = policy_data
    embedder = FakeEmbedder()
    ingestor = PolicyIngestor(
        repository,
        data_directory,
        FakeSemanticChunker(
            lambda text: [text[:34], "\n\n", text[36:]]
        ),
        embedder,
        max_chars=1000,
    )
    refund = next(
        document
        for document in repository.get_policy_documents()
        if document.document_id == "demo-refund-policy"
    )

    ingestor.ingest_approved_documents()

    chunks = [
        chunk.text
        for chunk in repository.get_policy_chunks()
        if chunk.document_id == refund.document_id
    ]
    source = clean_text((data_directory / refund.source).read_text(encoding="utf-8"))
    assert "".join(chunks) == source
    assert all(chunk.strip() for chunk in chunks)
    assert all(all(text.strip() for text in call) for call in embedder.calls)


def test_reingestion_replaces_chunks_without_duplicates(
    policy_data: tuple[JsonRepository, Path],
) -> None:
    repository, data_directory = policy_data
    ingestor = PolicyIngestor(
        repository,
        data_directory,
        FakeSemanticChunker(),
        FakeEmbedder(),
        max_chars=1000,
    )

    ingestor.ingest_approved_documents()
    initial_chunks = repository.get_policy_chunks()
    ingestor.ingest_approved_documents()
    chunks_after_second_ingestion = repository.get_policy_chunks()

    assert len(chunks_after_second_ingestion) == len(initial_chunks)
    assert [chunk.chunk_id for chunk in chunks_after_second_ingestion] == [
        chunk.chunk_id for chunk in initial_chunks
    ]


def test_policy_chunk_can_represent_missing_embedding_for_keyword_search(
    policy_data: tuple[JsonRepository, Path],
) -> None:
    repository, _ = policy_data
    document = repository.get_policy_documents()[0]

    chunk = PolicyChunk(
        chunk_id="bad-chunk",
        document_id=document.document_id,
        title=document.title,
        text="Policy text",
        embedding=[],
        metadata={
            "category": document.category,
            "approved": True,
            "source": document.source,
            "updated_at": document.updated_at.isoformat(),
            "chunk_index": 0,
        },
        token_count=2,
        embedding_model="mistral-embed",
    )

    assert chunk.embedding == []


def test_ingestion_rejects_source_path_outside_data_directory(
    policy_data: tuple[JsonRepository, Path],
) -> None:
    repository, data_directory = policy_data
    records = json.loads((data_directory / "policy_documents.json").read_text(encoding="utf-8"))
    records[0]["source"] = "../outside.md"
    (data_directory / "policy_documents.json").write_text(json.dumps(records), encoding="utf-8")
    ingestor = PolicyIngestor(
        repository,
        data_directory,
        FakeSemanticChunker(),
        FakeEmbedder(),
    )

    with pytest.raises(DataStoreError, match="inside the data directory"):
        ingestor.ingest_approved_documents()


def test_pdf_source_extracts_text_from_each_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "Policies.pdf"
    pdf_path.write_bytes(b"%PDF-test")
    reader = SimpleNamespace(
        is_encrypted=False,
        pages=[
            SimpleNamespace(extract_text=lambda: "First page"),
            SimpleNamespace(extract_text=lambda: "Second page"),
        ],
    )
    pdf_reader = Mock(return_value=reader)
    monkeypatch.setattr("app.rag.ingestion.PdfReader", pdf_reader)
    ingestor = PolicyIngestor(
        Mock(),
        tmp_path,
        FakeSemanticChunker(),
        FakeEmbedder(),
    )
    document = SimpleNamespace(
        document_id="demo-policy",
        source="Policies.pdf",
    )

    assert ingestor._read_source(document) == "First page\n\nSecond page"
    pdf_reader.assert_called_once_with(pdf_path)


def test_pdf_source_rejects_encrypted_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "Policies.pdf").write_bytes(b"%PDF-test")
    monkeypatch.setattr(
        "app.rag.ingestion.PdfReader",
        lambda _path: SimpleNamespace(is_encrypted=True, pages=[]),
    )
    ingestor = PolicyIngestor(
        Mock(),
        tmp_path,
        FakeSemanticChunker(),
        FakeEmbedder(),
    )
    document = SimpleNamespace(
        document_id="demo-policy",
        source="Policies.pdf",
    )

    with pytest.raises(DataStoreError, match="encrypted"):
        ingestor._read_source(document)


def test_pdf_source_reports_read_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "Policies.pdf").write_bytes(b"%PDF-test")

    def fail_to_read(_path: Path) -> None:
        raise PdfReadError("invalid PDF")

    monkeypatch.setattr("app.rag.ingestion.PdfReader", fail_to_read)
    ingestor = PolicyIngestor(
        Mock(),
        tmp_path,
        FakeSemanticChunker(),
        FakeEmbedder(),
    )
    document = SimpleNamespace(
        document_id="demo-policy",
        source="Policies.pdf",
    )

    with pytest.raises(DataStoreError, match="extract text from policy PDF"):
        ingestor._read_source(document)


def test_ingestion_does_not_write_empty_embedding_vectors(
    policy_data: tuple[JsonRepository, Path],
) -> None:
    repository, data_directory = policy_data
    ingestor = PolicyIngestor(
        repository,
        data_directory,
        FakeSemanticChunker(),
        InvalidEmbedder(),
    )

    with pytest.raises(ValueError, match="empty or non-finite"):
        ingestor.ingest_approved_documents()

    assert repository.get_policy_chunks() == []


def test_ingestion_rejects_embedding_count_mismatch(
    policy_data: tuple[JsonRepository, Path],
) -> None:
    repository, data_directory = policy_data

    class CountMismatchEmbedder:
        model_name = "fake-test-embedding"

        def embed_documents(self, _texts: list[str]) -> list[list[float]]:
            del _texts
            return []

    ingestor = PolicyIngestor(
        repository,
        data_directory,
        FakeSemanticChunker(),
        CountMismatchEmbedder(),
    )

    with pytest.raises(ValueError, match="different number of vectors"):
        ingestor.ingest_approved_documents()
    assert repository.get_policy_chunks() == []


def test_mistral_embedder_orders_vectors_and_checks_dimensions() -> None:
    class EmbeddingItem:
        def __init__(self, index: int, embedding: list[float]) -> None:
            self.index = index
            self.embedding = embedding

    class EmbeddingsClient:
        def __init__(self, data) -> None:
            self._data = data

        def create(self, model, inputs):
            client.last_model = model
            client.last_inputs = inputs
            return type("EmbeddingResponse", (), {"data": self._data})()

    client = type("MistralClient", (), {})()
    client.embeddings = EmbeddingsClient(
        [EmbeddingItem(1, [3, 4]), EmbeddingItem(0, [1, 2])]
    )
    embedder = MistralTextEmbedder.__new__(MistralTextEmbedder)
    embedder._client = client

    vectors = embedder.embed_documents(["first", "second"])

    assert vectors == [[1.0, 2.0], [3.0, 4.0]]
    assert client.last_model == "mistral-embed"
    assert client.last_inputs == ["first", "second"]


def test_mistral_embedder_rejects_empty_or_non_finite_vectors() -> None:
    class EmbeddingItem:
        index = 0

        def __init__(self, embedding: list[float]) -> None:
            self.embedding = embedding

    class EmbeddingsClient:
        def __init__(self, embedding: list[float]) -> None:
            self._embedding = embedding
            self.last_model = None
            self.last_inputs = None

        def create(self, model, inputs):
            self.last_model = model
            self.last_inputs = inputs
            return type("EmbeddingResponse", (), {"data": [EmbeddingItem(self._embedding)]})()

    for invalid_embedding in ([], [float("nan")]):
        embedder = MistralTextEmbedder.__new__(MistralTextEmbedder)
        embeddings_client = EmbeddingsClient(invalid_embedding)
        embedder._client = type(
            "MistralClient",
            (),
            {"embeddings": embeddings_client},
        )()

        with pytest.raises(EmbeddingError):
            embedder.embed_documents(["policy text"])
        assert embeddings_client.last_model == "mistral-embed"
        assert embeddings_client.last_inputs == ["policy text"]


def test_groq_chunker_accepts_only_source_preserving_output() -> None:
    source = "Keep every character.\n\nKeep punctuation!"
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {"chunks": ["Keep every character.\n\n", "Keep punctuation!"]}
                    )
                )
            )
        ]
    )
    chunker = GroqSemanticChunker.__new__(GroqSemanticChunker)
    chunker._model = "test-model"
    chunker._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=Mock(return_value=response))
        )
    )

    assert chunker.chunk(source) == ["Keep every character.\n\n", "Keep punctuation!"]


def test_groq_chunker_rejects_rewritten_content() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"chunks":["rewritten text"]}')
            )
        ]
    )
    chunker = GroqSemanticChunker.__new__(GroqSemanticChunker)
    chunker._model = "test-model"
    chunker._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=Mock(return_value=response))
        )
    )

    with pytest.raises(SemanticChunkingError, match="preserve the source"):
        chunker.chunk("original text")


def test_missing_groq_key_selects_fallback_and_requires_mistral_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")

    chunker, embedder = providers_from_environment()
    assert isinstance(chunker, UnavailableSemanticChunker)
    assert embedder.model_name == "mistral-embed"

    monkeypatch.delenv("MISTRAL_API_KEY")
    with pytest.raises(ProviderConfigurationError, match="MISTRAL_API_KEY"):
        providers_from_environment()

import logging
import math
import re
from pathlib import Path
from typing import Protocol

from pypdf import PdfReader
from pypdf.errors import PdfReadError
import tiktoken

from app.rag.providers import (
    EMBEDDING_MODEL,
    SemanticChunker,
    SemanticChunkingError,
    TextEmbedder,
    providers_from_environment,
)
from app.storage.json_store import DataStoreError, JsonRepository
from app.storage.models import PolicyChunk, PolicyDocument

logger = logging.getLogger(__name__)
SUPPORTED_SOURCE_SUFFIXES = {".md", ".txt", ".pdf"}
DEFAULT_MAX_CHARS = 1200
TOKEN_ENCODING = tiktoken.get_encoding("cl100k_base")


class PolicyRepository(Protocol):
    def get_policy_documents(self) -> list[PolicyDocument]: ...

    def replace_policy_chunks(
        self,
        document_id: str,
        chunks: list[PolicyChunk],
    ) -> None: ...


def clean_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n")]
    cleaned_lines: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if not previous_blank:
                cleaned_lines.append("")
            previous_blank = True
            continue
        cleaned_lines.append(line)
        previous_blank = False
    return "\n".join(cleaned_lines).strip()


def deterministic_chunks(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive.")
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(start + max_chars, len(text))
        end = hard_end
        if hard_end < len(text) and max_chars > 2:
            preferred_start = start + int(max_chars * 0.6)
            candidates = [
                (text.rfind("\n\n", preferred_start, hard_end - 1), 2),
                (text.rfind(". ", preferred_start, hard_end), 1),
                (text.rfind(" ", preferred_start, hard_end), 1),
                (text.rfind("\n", preferred_start, hard_end), 1),
            ]
            valid_endings = [
                (position + length, position)
                for position, length in candidates
                if position >= preferred_start and position + length <= hard_end
            ]
            if valid_endings:
                end = max(valid_endings)[0]
        chunk = text[start:end]
        if not chunk:
            raise RuntimeError("Deterministic chunking made no progress.")
        chunks.append(chunk)
        start = end
    return chunks


class PolicyIngestor:
    def __init__(
        self,
        repository: PolicyRepository,
        data_directory: Path,
        chunker: SemanticChunker,
        embedder: TextEmbedder,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        if max_chars < 1:
            raise ValueError("max_chars must be positive.")
        self._repository = repository
        self._data_directory = data_directory.resolve()
        self._chunker = chunker
        self._embedder = embedder
        self._max_chars = max_chars

    def ingest_approved_documents(self) -> dict[str, int]:
        documents = self._repository.get_policy_documents()
        approved_documents = [document for document in documents if document.approved]
        total_chunks = 0

        for document in approved_documents:
            cleaned_text = clean_text(self._read_source(document))
            if not cleaned_text:
                raise DataStoreError(
                    f"Approved policy document has no text: {document.document_id}"
                )

            try:
                chunks = self._chunker.chunk(cleaned_text)
                self._validate_semantic_chunks(chunks, cleaned_text)
            except SemanticChunkingError as exc:
                logger.warning(
                    "Using deterministic chunks for policy document %s: %s",
                    document.document_id,
                    exc,
                )
                chunks = deterministic_chunks(cleaned_text, self._max_chars)

            chunks = self._merge_whitespace_chunks(chunks, cleaned_text)
            chunks = self._enforce_max_chars(chunks, cleaned_text)
            embeddings = self._embedder.embed_documents(chunks)
            if len(embeddings) != len(chunks):
                raise ValueError(
                    "Embedding provider returned a different number of vectors than chunks."
                )
            if any(
                not embedding
                or any(not math.isfinite(value) for value in embedding)
                for embedding in embeddings
            ):
                raise ValueError(
                    "Embedding provider returned an empty or non-finite vector."
                )
            dimensions = {len(embedding) for embedding in embeddings}
            if len(dimensions) != 1:
                raise ValueError(
                    "Embedding provider returned vectors with inconsistent dimensions."
                )

            policy_chunks = [
                self._make_chunk(document, chunk, index, embeddings[index])
                for index, chunk in enumerate(chunks)
            ]
            self._repository.replace_policy_chunks(document.document_id, policy_chunks)
            total_chunks += len(policy_chunks)

        return {
            "documents_processed": len(approved_documents),
            "chunks_written": total_chunks,
            "documents_skipped": len(documents) - len(approved_documents),
        }

    def _read_source(self, document: PolicyDocument) -> str:
        source_path = (self._data_directory / document.source).resolve()
        if not source_path.is_relative_to(self._data_directory):
            raise DataStoreError(
                f"Policy source must be inside the data directory: {document.document_id}"
            )
        if source_path.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
            raise DataStoreError(
                f"Unsupported policy source type for {document.document_id}; "
                "use Markdown, plain text, or PDF."
            )
        try:
            if source_path.suffix.lower() == ".pdf":
                reader = PdfReader(source_path)
                if reader.is_encrypted:
                    raise DataStoreError(
                        f"Policy PDF is encrypted and cannot be read: {document.source}"
                    )
                return "\n\n".join(
                    page.extract_text() or "" for page in reader.pages
                )
            return source_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise DataStoreError(
                f"Policy source file is missing: {document.source}"
            ) from exc
        except PdfReadError as exc:
            raise DataStoreError(
                f"Could not extract text from policy PDF: {document.source}"
            ) from exc
        except UnicodeError as exc:
            raise DataStoreError(
                f"Policy source is not valid UTF-8: {document.source}"
            ) from exc
        except OSError as exc:
            raise DataStoreError(
                f"Could not read policy source file: {document.source}"
            ) from exc

    def _validate_semantic_chunks(self, chunks: list[str], source: str) -> None:
        if (
            not chunks
            or any(not isinstance(chunk, str) or not chunk for chunk in chunks)
            or "".join(chunks) != source
        ):
            raise SemanticChunkingError(
                "Semantic chunks do not preserve the cleaned source exactly."
            )

    def _merge_whitespace_chunks(self, chunks: list[str], source: str) -> list[str]:
        if "".join(chunks) != source:
            raise SemanticChunkingError(
                "Chunks must preserve the cleaned source before whitespace is merged."
            )

        merged: list[str] = []
        for chunk in chunks:
            if chunk.strip():
                merged.append(chunk)
            elif merged:
                merged[-1] += chunk
            else:
                merged.append(chunk)

        if merged and not merged[0].strip() and len(merged) > 1:
            merged[1] = merged[0] + merged[1]
            merged.pop(0)
        if any(not chunk.strip() for chunk in merged):
            raise SemanticChunkingError(
                "Could not merge whitespace-only chunks with policy text."
            )
        if "".join(merged) != source:
            raise SemanticChunkingError(
                "Whitespace chunk merging did not preserve the cleaned source."
            )
        return merged

    def _enforce_max_chars(self, chunks: list[str], source: str) -> list[str]:
        result: list[str] = []
        for chunk in chunks:
            if len(chunk) > self._max_chars:
                result.extend(deterministic_chunks(chunk, self._max_chars))
            else:
                result.append(chunk)
        if "".join(result) != source:
            raise SemanticChunkingError(
                "Chunk size enforcement did not preserve the cleaned source."
            )
        return result

    def _make_chunk(
        self,
        document: PolicyDocument,
        text: str,
        index: int,
        embedding: list[float],
    ) -> PolicyChunk:
        return PolicyChunk(
            chunk_id=f"{document.document_id}-chunk-{index + 1:03d}",
            document_id=document.document_id,
            title=document.title,
            text=text,
            embedding=embedding,
            metadata={
                "category": document.category,
                "approved": document.approved,
                "source": document.source,
                "updated_at": document.updated_at.isoformat(),
                "chunk_index": index,
            },
            token_count=len(TOKEN_ENCODING.encode(text)),
            embedding_model=self._embedder.model_name or EMBEDDING_MODEL,
        )


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    chunker, embedder = providers_from_environment()
    data_directory = Path(__file__).resolve().parents[2] / "data"
    ingestor = PolicyIngestor(
        repository=JsonRepository(data_directory),
        data_directory=data_directory,
        chunker=chunker,
        embedder=embedder,
    )
    summary = ingestor.ingest_approved_documents()
    print(
        "Policy ingestion complete: "
        f"{summary['documents_processed']} documents, "
        f"{summary['chunks_written']} chunks, "
        f"{summary['documents_skipped']} unapproved documents skipped."
    )


if __name__ == "__main__":
    main()

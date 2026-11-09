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
from app.storage.factory import repository_from_environment
from app.storage.json_store import DataStoreError
from app.storage.models import PolicyChunk, PolicyDocument


SUPPORTED_SOURCE_SUFFIXES = {".md", ".txt", ".pdf"}
TOKEN_ENCODING = tiktoken.get_encoding("cl100k_base")
OBSOLETE_DRAFT_BANNER = re.compile(
    r"(?im)^.*controlled draft.*verify approval status before use.*(?:\n|$)"
)


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


class PolicyIngestor:
    def __init__(
        self,
        repository: PolicyRepository,
        data_directory: Path,
        chunker: SemanticChunker,
        embedder: TextEmbedder,
    ) -> None:
        self._repository = repository
        self._data_directory = data_directory.resolve()
        self._chunker = chunker
        self._embedder = embedder

    def ingest_approved_documents(self) -> dict[str, int]:
        documents = self._repository.get_policy_documents()
        approved_documents = [document for document in documents if document.approved]
        total_chunks = 0

        for document in approved_documents:
            source_text = self._read_source(document)
            source_text = OBSOLETE_DRAFT_BANNER.sub("", source_text)
            cleaned_text = clean_text(source_text)
            if not cleaned_text:
                raise DataStoreError(
                    f"Approved policy document has no text: {document.document_id}"
                )

            chunks = self._chunker.chunk(cleaned_text)
            self._validate_semantic_chunks(chunks, cleaned_text)

            chunks = self._merge_whitespace_chunks(chunks, cleaned_text)
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
        project_directory = self._data_directory.parent
        normalized_source = document.source.replace("\\", "/")
        if normalized_source.startswith("app/policies/"):
            allowed_directory = (project_directory / "app" / "policies").resolve()
            source_path = (project_directory / normalized_source).resolve()
        else:
            allowed_directory = self._data_directory
            source_path = (self._data_directory / document.source).resolve()
        if not source_path.is_relative_to(allowed_directory):
            raise DataStoreError(
                "Policy source must be inside the data directory or app/policies: "
                f"{document.document_id}"
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

    load_dotenv(
        dotenv_path=Path(__file__).resolve().parents[2] / ".env",
        override=False,
    )
    chunker, embedder = providers_from_environment()
    data_directory = Path(__file__).resolve().parents[2] / "data"
    ingestor = PolicyIngestor(
        repository=repository_from_environment(data_directory),
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

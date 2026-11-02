import logging
import os
from dataclasses import dataclass

from app.rag.generation import (
    AnswerGenerator,
    AnswerVerifier,
    GenerationError,
    GroqGroundedAnswerGenerator,
    GroqGroundedAnswerVerifier,
    HUMAN_SUPPORT_MARKER,
)
from app.rag.providers import (
    ProviderConfigurationError,
    embedder_from_environment,
)
from app.rag.retrieval import HybridPolicyRetriever, HybridSearchResult
from app.storage.factory import repository_from_environment
logger = logging.getLogger(__name__)
NO_EVIDENCE_ANSWER = (
    "I couldn’t find enough information in the approved policy documents to verify "
    "that. Please contact support for help."
)


@dataclass(frozen=True)
class PolicyAnswer:
    answer: str
    route: str
    sources: list[dict[str, str]]
    retrieval: HybridSearchResult
    needs_human_support: bool = False


class PolicyAnswerService:
    def __init__(
        self,
        retriever: HybridPolicyRetriever,
        generator: AnswerGenerator,
        verifier: AnswerVerifier | None = None,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._verifier = verifier

    def answer(
        self,
        question: str,
        search_result: HybridSearchResult | None = None,
    ) -> PolicyAnswer:
        search_result = search_result or self._retriever.search(question)
        if not search_result.results:
            return PolicyAnswer(
                answer=NO_EVIDENCE_ANSWER,
                route="rag",
                sources=[],
                retrieval=search_result,
                needs_human_support=True,
            )

        needs_human_support = False
        try:
            answer = self._generator.generate(question, search_result.results)
            if self._verifier is not None and not self._verifier.is_supported(
                question,
                answer,
                search_result.results,
            ):
                answer = (
                    "I couldn’t verify a reliable answer against the approved "
                    "policy information, so I’m escalating this to our support team."
                )
                needs_human_support = True
            else:
                needs_human_support = answer.startswith(HUMAN_SUPPORT_MARKER) or any(
                    phrase in answer.casefold()
                    for phrase in (
                        "cannot verify",
                        "can't verify",
                        "can’t verify",
                        "insufficient evidence",
                        "evidence is insufficient",
                        "not enough information",
                        "unable to determine",
                        "couldn’t find enough information",
                        "couldn't find enough information",
                    )
                )
                if needs_human_support:
                    answer = answer.removeprefix(HUMAN_SUPPORT_MARKER).lstrip()
        except GenerationError:
            logger.exception("Grounded policy answer generation failed.")
            answer = (
                "I found relevant approved policy information but can’t generate a "
                "reliable answer right now. Please contact support for help."
            )
            needs_human_support = True

        source_map: dict[str, dict[str, str]] = {}
        for result in search_result.results:
            chunk = result.chunk
            source_map[chunk.chunk_id] = {
                "document_id": chunk.document_id,
                "title": chunk.title,
                "chunk_id": chunk.chunk_id,
            }
        return PolicyAnswer(
            answer=answer,
            route="rag",
            sources=list(source_map.values()),
            retrieval=search_result,
            needs_human_support=needs_human_support,
        )


def answer_policy_question(question: str) -> PolicyAnswer:
    repository = repository_from_environment()
    documents = repository.get_policy_documents()
    chunks = repository.get_policy_chunks()
    has_approved_chunks = any(
        chunk.metadata.get("approved") is True
        and any(
            document.document_id == chunk.document_id
            and document.approved
            and chunk.metadata.get("updated_at") == document.updated_at.isoformat()
            for document in documents
        )
        for chunk in chunks
    )
    if not has_approved_chunks:
        return PolicyAnswer(
            answer=NO_EVIDENCE_ANSWER,
            route="rag",
            sources=[],
            retrieval=HybridSearchResult(
                results=[],
                vector_available=False,
                vector_error="no_valid_approved_chunks",
                bm25_available=False,
            ),
            needs_human_support=True,
        )

    embedder = embedder_from_environment(required=False)
    retriever = HybridPolicyRetriever(repository, embedder)
    search_result = retriever.search(question)
    if not search_result.results:
        return PolicyAnswer(
            answer=NO_EVIDENCE_ANSWER,
            route="rag",
            sources=[],
            retrieval=search_result,
            needs_human_support=True,
        )

    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    groq_model = os.environ.get("GROQ_MODEL", "").strip()
    if not groq_key or not groq_model:
        raise ProviderConfigurationError(
            "GROQ_API_KEY and GROQ_MODEL are required to generate an answer."
        )

    generator = GroqGroundedAnswerGenerator(groq_key, groq_model)
    verifier_model = os.environ.get(
        "GROQ_VERIFIER_MODEL",
        "openai/gpt-oss-20b",
    ).strip()
    verifier = GroqGroundedAnswerVerifier(groq_key, verifier_model)
    return PolicyAnswerService(retriever, generator, verifier).answer(
        question,
        search_result,
    )

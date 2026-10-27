import os

from app.evaluation.config import get_evaluation_settings
from app.evaluation.schemas import MetricDefinition


def get_metric_catalog() -> list[MetricDefinition]:
    settings = get_evaluation_settings()
    legacy_override = os.getenv("DEEPEVAL_THRESHOLD") is not None
    answer_relevancy_threshold = (
        settings.threshold if legacy_override else settings.answer_relevancy_threshold
    )
    faithfulness_threshold = (
        settings.threshold if legacy_override else settings.faithfulness_threshold
    )
    correctness_threshold = (
        settings.threshold if legacy_override else settings.correctness_threshold
    )
    contextual_relevancy_threshold = (
        settings.threshold if legacy_override else settings.contextual_relevancy_threshold
    )
    tool_correctness_threshold = (
        settings.threshold if legacy_override else settings.tool_correctness_threshold
    )
    return [
        MetricDefinition(
            name="answer_relevancy",
            description="Checks whether the answer addresses the customer’s question.",
            enabled=True,
            threshold=answer_relevancy_threshold,
        ),
        MetricDefinition(
            name="faithfulness",
            description="Checks whether policy claims are supported by retrieved context.",
            enabled=True,
            threshold=faithfulness_threshold,
        ),
        MetricDefinition(
            name="customer_support_correctness",
            description="Judges answer correctness and completeness against required facts or a reference answer.",
            enabled=True,
            threshold=correctness_threshold,
        ),
        MetricDefinition(
            name="tool_correctness",
            description="Checks expected tool names and available sanitized arguments against the actual tool trace.",
            enabled=True,
            threshold=tool_correctness_threshold,
        ),
        MetricDefinition(
            name="contextual_relevancy",
            description="Checks whether retrieved chunks are relevant to the customer question.",
            enabled=True,
            threshold=contextual_relevancy_threshold,
        ),
        MetricDefinition(
            name="task_completion",
            description="Unavailable until the application exposes a supported task trajectory; skipped by the Phase 4 runner.",
            enabled=False,
            threshold=settings.threshold,
        ),
    ]

import math
import os
import secrets
from dataclasses import dataclass


def _as_bool(raw_value: str | None, default: bool = False) -> bool:
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class EvaluationSettings:
    enabled: bool = True
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    judge_api_key: str = ""
    threshold: float = 0.8
    answer_relevancy_threshold: float = 0.8
    faithfulness_threshold: float = 0.9
    correctness_threshold: float = 0.85
    contextual_relevancy_threshold: float = 0.8
    tool_correctness_threshold: float = 0.9
    environment: str = "local"
    api_token: str = ""
    judge_timeout_seconds: float = 30.0
    max_concurrent_evaluations: int = 2
    max_request_body_bytes: int = 131072

    @property
    def judge_configured(self) -> bool:
        return bool(self.judge_api_key.strip())


def get_evaluation_settings() -> EvaluationSettings:
    threshold_value = os.getenv("DEEPEVAL_THRESHOLD", "0.8").strip()
    try:
        threshold = float(threshold_value)
    except ValueError:
        threshold = 0.8
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        threshold = 0.8

    def metric_threshold(environment_name: str, default: float) -> float:
        raw_value = os.getenv(environment_name)
        if raw_value is None:
            return threshold if os.getenv("DEEPEVAL_THRESHOLD") is not None else default
        try:
            configured_value = float(raw_value.strip())
        except ValueError:
            return default
        if not math.isfinite(configured_value) or not 0.0 <= configured_value <= 1.0:
            return default
        return configured_value

    def bounded_float(environment_name: str, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(os.getenv(environment_name, str(default)).strip())
        except ValueError:
            return default
        return value if math.isfinite(value) and minimum <= value <= maximum else default

    def bounded_int(environment_name: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(os.getenv(environment_name, str(default)).strip())
        except ValueError:
            return default
        return value if minimum <= value <= maximum else default

    return EvaluationSettings(
        enabled=_as_bool(os.getenv("DEEPEVAL_ENABLED"), default=True),
        provider=(os.getenv("DEEPEVAL_PROVIDER") or "openai").strip() or "openai",
        model=(os.getenv("DEEPEVAL_MODEL") or "gpt-4o-mini").strip() or "gpt-4o-mini",
        judge_api_key=(
            os.getenv("DEEPEVAL_JUDGE_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        ).strip(),
        threshold=threshold,
        answer_relevancy_threshold=metric_threshold("DEEPEVAL_ANSWER_RELEVANCY_THRESHOLD", 0.8),
        faithfulness_threshold=metric_threshold("DEEPEVAL_FAITHFULNESS_THRESHOLD", 0.9),
        correctness_threshold=metric_threshold("DEEPEVAL_CORRECTNESS_THRESHOLD", 0.85),
        contextual_relevancy_threshold=metric_threshold("DEEPEVAL_CONTEXTUAL_RELEVANCY_THRESHOLD", 0.8),
        tool_correctness_threshold=metric_threshold("DEEPEVAL_TOOL_CORRECTNESS_THRESHOLD", 0.9),
        environment=(os.getenv("DEEPEVAL_ENVIRONMENT") or "local").strip().casefold() or "local",
        api_token=os.getenv("DEEPEVAL_API_TOKEN", "").strip(),
        judge_timeout_seconds=bounded_float("DEEPEVAL_JUDGE_TIMEOUT_SECONDS", 30.0, 1.0, 300.0),
        max_concurrent_evaluations=bounded_int("DEEPEVAL_MAX_CONCURRENT_EVALUATIONS", 2, 1, 8),
        max_request_body_bytes=bounded_int("DEEPEVAL_MAX_REQUEST_BODY_BYTES", 131072, 1024, 1048576),
    )


def is_evaluation_access_allowed(authorization_header: str | None) -> bool:
    settings = get_evaluation_settings()
    if settings.environment in {"local", "development", "test"}:
        return True
    if not settings.api_token:
        return False
    if authorization_header is None:
        return False
    scheme, separator, supplied_token = authorization_header.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not supplied_token.strip():
        return False
    return secrets.compare_digest(supplied_token.strip(), settings.api_token)

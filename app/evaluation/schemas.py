from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EvaluationCategory = Literal[
    "rag_policy",
    "tool_lookup",
    "mixed",
    "unknown",
    "safety",
]
EvaluationRoute = Literal["rag", "tools", "mixed", "fallback"]


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    category: EvaluationCategory
    input: str = Field(min_length=1, max_length=2000)
    expected_output: str | None = Field(default=None, max_length=3000)
    expected_route: EvaluationRoute
    expected_tools: list[str] = Field(default_factory=list, max_length=10)
    expected_tool_arguments: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict,
        max_length=20,
    )
    expected_context_facts: list[str] = Field(default_factory=list, max_length=20)
    safety_expectations: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_category_route(self) -> "EvaluationCase":
        expected_routes: dict[str, str] = {
            "rag_policy": "rag",
            "tool_lookup": "tools",
            "mixed": "mixed",
            "unknown": "fallback",
        }
        required_route = expected_routes.get(self.category)
        if required_route is not None and self.expected_route != required_route:
            raise ValueError(
                f"Category '{self.category}' requires expected_route '{required_route}'."
            )
        return self


class EvaluationCaseListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    cases: list[EvaluationCase]


class EvaluationMetricResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["passed", "failed", "skipped", "error"]
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str | None = None


class EvaluationToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, str | int | float | bool | None]
    result_status: Literal[
        "success",
        "not_found",
        "unavailable",
        "eligible",
        "ineligible",
        "cancelled",
        "not_cancelled",
    ]


class EvaluationDeterministicCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["passed", "failed", "skipped"]
    reason: str


class EvaluationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case: EvaluationCase


class EvaluationRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    status: Literal["completed", "disabled", "busy", "agent_error", "judge_error"]
    actual_output: str | None
    actual_route: str | None
    retrieval_context: list[str]
    actual_tool_calls: list[EvaluationToolCall]
    metrics: list[EvaluationMetricResult]
    deterministic_checks: list[EvaluationDeterministicCheck] = Field(default_factory=list)
    error: str | None = None
    duration_ms: int = Field(ge=0)


class EvaluationDatasetRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categories: list[EvaluationCategory] = Field(default_factory=list, max_length=5)
    case_ids: list[str] = Field(default_factory=list, max_length=100)
    fail_fast: bool = False

    @model_validator(mode="after")
    def validate_unique_filters(self) -> "EvaluationDatasetRunRequest":
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("categories must not contain duplicates.")
        if len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("case_ids must not contain duplicates.")
        return self


class EvaluationDatasetCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: EvaluationCategory
    status: Literal["completed", "failed", "skipped"]
    result: EvaluationRunResponse | None = None
    reason: str | None = None


class EvaluationRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    passed_metrics: int = Field(ge=0)
    failed_metrics: int = Field(ge=0)
    error_metrics: int = Field(ge=0)
    skipped_metrics: int = Field(ge=0)
    metric_pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    safety_failures: int = Field(ge=0)
    quality_gate_passed: bool
    by_category: dict[str, "EvaluationRunSummary"] = Field(default_factory=dict)


class EvaluationDatasetRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: Literal["queued", "running", "completed", "failed"]
    created_at: str
    updated_at: str
    fail_fast: bool
    selected_case_ids: list[str]
    summary: EvaluationRunSummary
    results: list[EvaluationDatasetCaseResult] = Field(default_factory=list)
    error: str | None = None


class EvaluationDatasetRunAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: Literal["queued", "running", "completed", "failed"]
    selected: int = Field(ge=0)
    message: str


class EvaluationDatasetRunResults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: Literal["queued", "running", "completed", "failed"]
    total: int = Field(ge=0)
    results: list[EvaluationDatasetCaseResult]


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    enabled: bool = True
    threshold: float = Field(default=0.8, ge=0.0, le=1.0)


class EvaluationHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "disabled"]
    judge_configured: bool
    model: str
    provider: str
    message: str


class EvaluationMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics: list[MetricDefinition]

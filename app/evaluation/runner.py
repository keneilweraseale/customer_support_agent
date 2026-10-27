import math
from threading import Lock
from time import perf_counter
from typing import Any, Callable

from app.evaluation.config import EvaluationSettings, get_evaluation_settings
from app.evaluation.schemas import (
    EvaluationCase,
    EvaluationMetricResult,
    EvaluationRunResponse,
)
from app.evaluation.safety import build_deterministic_checks

METRIC_NAMES = (
    "answer_relevancy",
    "faithfulness",
    "customer_support_correctness",
    "contextual_relevancy",
    "tool_correctness",
    "task_completion",
)
_active_evaluations = 0
_active_evaluations_lock = Lock()


def run_evaluation_case(
    case: EvaluationCase,
    settings: EvaluationSettings | None = None,
) -> EvaluationRunResponse:
    current_settings = settings or get_evaluation_settings()
    global _active_evaluations
    with _active_evaluations_lock:
        if _active_evaluations >= current_settings.max_concurrent_evaluations:
            return EvaluationRunResponse(
                case_id=case.case_id,
                status="busy",
                actual_output=None,
                actual_route=None,
                retrieval_context=[],
                actual_tool_calls=[],
                metrics=[_skipped_metric(name, "Evaluation capacity is currently full.") for name in METRIC_NAMES],
                deterministic_checks=[],
                error="Evaluation capacity is currently full; retry later.",
                duration_ms=0,
            )
        _active_evaluations += 1
    try:
        return _run_evaluation_case(case, current_settings)
    finally:
        with _active_evaluations_lock:
            _active_evaluations -= 1


def _run_evaluation_case(
    case: EvaluationCase,
    current_settings: EvaluationSettings,
) -> EvaluationRunResponse:
    """Run a case through the application's orchestrator and evaluate its real output."""
    started_at = perf_counter()
    if not current_settings.enabled:
        return EvaluationRunResponse(
            case_id=case.case_id,
            status="disabled",
            actual_output=None,
            actual_route=None,
            retrieval_context=[],
            actual_tool_calls=[],
            metrics=[
                _skipped_metric(name, "Evaluation is disabled by DEEPEVAL_ENABLED.")
                for name in METRIC_NAMES
            ],
            deterministic_checks=[],
            error="Evaluation is disabled by DEEPEVAL_ENABLED.",
            duration_ms=_duration_ms(started_at),
        )
    try:
        execution = _run_real_agent(case)
    except Exception as exc:
        return EvaluationRunResponse(
            case_id=case.case_id,
            status="agent_error",
            actual_output=None,
            actual_route=None,
            retrieval_context=[],
            actual_tool_calls=[],
            metrics=[_skipped_metric(name, "Agent execution failed.") for name in METRIC_NAMES],
            error=f"Agent execution failed ({type(exc).__name__}); details omitted.",
            duration_ms=_duration_ms(started_at),
        )

    actual_output = execution.answer
    retrieval_context = list(execution.retrieval_context or [])
    actual_tool_calls = list(execution.actual_tool_calls or [])
    deterministic_checks = build_deterministic_checks(
        case=case,
        actual_route=execution.route.value,
        actual_output=actual_output,
        actual_tool_calls=actual_tool_calls,
    )
    metrics = evaluate_response(
        case=case,
        actual_output=actual_output,
        retrieval_context=retrieval_context,
        actual_tool_calls=actual_tool_calls,
        settings=current_settings,
    )
    has_judge_error = any(
        result.status == "error"
        for result in metrics
        if result.name in {
            "answer_relevancy",
            "faithfulness",
            "customer_support_correctness",
            "contextual_relevancy",
            "tool_correctness",
        }
    )
    return EvaluationRunResponse(
        case_id=case.case_id,
        status="judge_error" if has_judge_error else "completed",
        actual_output=actual_output,
        actual_route=execution.route.value,
        retrieval_context=retrieval_context,
        actual_tool_calls=actual_tool_calls,
        metrics=metrics,
        deterministic_checks=deterministic_checks,
        error="One or more judge metrics failed; see metric reasons." if has_judge_error else None,
        duration_ms=_duration_ms(started_at),
    )


def _run_real_agent(case: EvaluationCase) -> Any:
    """Call the same ChatOrchestrator instance used by POST /api/chat."""
    from app.api.chat import orchestrator
    from app.services.demo_authorization import demo_authorization_service

    customer_id = case.expected_tool_arguments.get("customer_id")
    verified_customer_id: str | None = None
    if isinstance(customer_id, str):
        token, _ = demo_authorization_service.issue_token(customer_id)
        verified_customer_id = demo_authorization_service.resolve_customer(token)
        if verified_customer_id is None:
            raise RuntimeError("Synthetic evaluation identity could not be verified.")

    return orchestrator.handle(
        case.input,
        verified_customer_id,
        cancellation_preview_tool=ReadOnlyCancellationPreviewTool(),
    )


class ReadOnlyCancellationPreviewTool:
    """Evaluation-only cancellation eligibility adapter with no persistence or token issuance."""

    def invoke(self, input: dict[str, str]) -> dict[str, object]:
        from app.storage.json_store import JsonRepository

        order = JsonRepository().get_order(input["order_id"])
        if order is None or order.customer_id != input["customer_id"]:
            return {"found": False, "eligible": False}
        return {
            "found": True,
            "eligible": order.cancellation_allowed and order.order_status == "processing",
            "message": "Read-only evaluation preview; no cancellation action was taken.",
        }


def evaluate_response(
    case: EvaluationCase,
    actual_output: str,
    retrieval_context: list[str],
    settings: EvaluationSettings,
    actual_tool_calls: list[dict[str, Any]] | None = None,
) -> list[EvaluationMetricResult]:
    if not settings.enabled:
        return [
            _skipped_metric(name, "Evaluation is disabled by DEEPEVAL_ENABLED.")
            for name in METRIC_NAMES
        ]
    tool_metric_result = _evaluate_tool_correctness(
        case,
        actual_output,
        actual_tool_calls or [],
        settings.tool_correctness_threshold,
    )
    answer_ready = bool(actual_output.strip())
    faithfulness_ready = bool(retrieval_context)
    correctness_ready = bool(case.expected_output)
    contextual_relevancy_ready = bool(retrieval_context)
    metric_readiness = {
        "answer_relevancy": (
            answer_ready,
            "The agent returned no answer to evaluate.",
            settings.answer_relevancy_threshold,
        ),
        "faithfulness": (
            faithfulness_ready,
            "No actual retrieval context was returned by the agent.",
            settings.faithfulness_threshold,
        ),
        "customer_support_correctness": (
            correctness_ready,
            "No expected_output reference was supplied.",
            settings.correctness_threshold,
        ),
        "contextual_relevancy": (
            contextual_relevancy_ready,
            "No actual retrieval context was returned by the agent.",
            settings.contextual_relevancy_threshold,
        ),
    }
    if not any(ready for ready, _, _ in metric_readiness.values()):
        return [
            _skipped_metric(name, reason, threshold)
            for name, (_, reason, threshold) in metric_readiness.items()
        ] + [tool_metric_result, _task_completion_skip()]

    if not settings.judge_configured:
        return [
            _skipped_metric(
                name,
                "Judge credentials are not configured." if ready else reason,
                threshold,
            )
            for name, (ready, reason, threshold) in metric_readiness.items()
        ] + [tool_metric_result, _task_completion_skip()]
    if settings.provider.casefold() != "openai":
        return [
            EvaluationMetricResult(
                name=name,
                status="error",
                threshold=threshold,
                reason=(
                    f"Judge provider '{settings.provider}' is not supported by this "
                    "Phase 3 runner; configure DEEPEVAL_PROVIDER=openai."
                ),
            )
            if ready
            else _skipped_metric(name, reason, threshold)
            for name, (ready, reason, threshold) in metric_readiness.items()
        ] + [tool_metric_result, _task_completion_skip()]

    try:
        from deepeval.metrics import (
            AnswerRelevancyMetric,
            ContextualRelevancyMetric,
            FaithfulnessMetric,
            GEval,
        )
        from deepeval.test_case import LLMTestCase, LLMTestCaseParams

        model = _build_judge_model(settings)
        test_case = LLMTestCase(
            input=case.input,
            actual_output=actual_output,
            expected_output=case.expected_output,
            retrieval_context=retrieval_context or None,
        )
    except Exception as exc:
        return [
            EvaluationMetricResult(
                name=name,
                status="error" if ready else "skipped",
                threshold=threshold if ready else None,
                reason=(
                    f"Judge initialization failed ({type(exc).__name__})."
                    if ready
                    else reason
                ),
            )
            for name, (ready, reason, threshold) in metric_readiness.items()
        ] + [tool_metric_result, _task_completion_skip()]

    def evaluate_one(name: str, factory: Callable[[], Any]) -> EvaluationMetricResult:
        ready, reason, threshold = metric_readiness[name]
        if not ready:
            return _skipped_metric(name, reason, threshold)
        try:
            return _measure_metric(name, factory(), test_case)
        except Exception as exc:
            return EvaluationMetricResult(
                name=name,
                status="error",
                threshold=threshold,
                reason=f"Judge metric initialization failed ({type(exc).__name__}).",
            )

    return [
        evaluate_one(
            "answer_relevancy",
            lambda: AnswerRelevancyMetric(
                threshold=settings.answer_relevancy_threshold,
                model=model,
                async_mode=False,
            ),
        ),
        evaluate_one(
            "faithfulness",
            lambda: FaithfulnessMetric(
                threshold=settings.faithfulness_threshold,
                model=model,
                async_mode=False,
            ),
        ),
        evaluate_one(
            "customer_support_correctness",
            lambda: GEval(
                name="Customer Support Correctness",
                evaluation_params=[
                    LLMTestCaseParams.INPUT,
                    LLMTestCaseParams.ACTUAL_OUTPUT,
                    LLMTestCaseParams.EXPECTED_OUTPUT,
                ],
                criteria=(
                    "Evaluate whether the customer-support answer is factually correct, "
                    "complete for the question, and consistent with the supplied reference. "
                    "Do not reward unsupported policy claims or invented live data."
                ),
                model=model,
                threshold=settings.correctness_threshold,
                async_mode=False,
            ),
        ),
        evaluate_one(
            "contextual_relevancy",
            lambda: ContextualRelevancyMetric(
                threshold=settings.contextual_relevancy_threshold,
                model=model,
                async_mode=False,
            ),
        ),
    ] + [tool_metric_result, _task_completion_skip()]


def _build_judge_model(settings: EvaluationSettings) -> Any:
    from deepeval.models import GPTModel

    class TimeoutGPTModel(GPTModel):
        def load_model(self, async_mode: bool = False) -> Any:
            from openai import AsyncOpenAI, OpenAI

            client_type = AsyncOpenAI if async_mode else OpenAI
            return client_type(
                api_key=self._openai_api_key,
                timeout=settings.judge_timeout_seconds,
            )

    return TimeoutGPTModel(
        model=settings.model,
        _openai_api_key=settings.judge_api_key,
    )


def _evaluate_tool_correctness(
    case: EvaluationCase,
    actual_output: str,
    actual_tool_calls: list[dict[str, Any]],
    threshold: float,
) -> EvaluationMetricResult:
    if not case.expected_tools:
        return _skipped_metric(
            "tool_correctness",
            "No expected tools were specified; tool selection is checked deterministically.",
            threshold,
        )

    try:
        from deepeval.metrics import ToolCorrectnessMetric
        from deepeval.test_case import LLMTestCase, ToolCall, ToolCallParams

        safe_argument_keys = {"order_id", "product_id", "customer_id"}
        expected_arguments = {
            key: "[redacted]" if key == "customer_id" else value
            for key, value in case.expected_tool_arguments.items()
            if key in safe_argument_keys
        }
        actual_calls = [
            ToolCall(
                name=str(call["name"]),
                input_parameters={
                    key: value
                    for key, value in call.get("arguments", {}).items()
                    if key in safe_argument_keys
                },
                output=str(call.get("result_status", "unknown")),
            )
            for call in actual_tool_calls
            if isinstance(call.get("name"), str)
        ]
        expected_calls = [
            ToolCall(
                name=name,
                input_parameters=dict(expected_arguments),
            )
            for name in case.expected_tools
        ]
        evaluation_params = (
            [ToolCallParams.INPUT_PARAMETERS]
            if expected_arguments
            else []
        )
        test_case = LLMTestCase(
            input=case.input,
            actual_output=actual_output,
            tools_called=actual_calls,
            expected_tools=expected_calls,
        )
        metric = ToolCorrectnessMetric(
            threshold=threshold,
            evaluation_params=evaluation_params,
            should_exact_match=False,
            should_consider_ordering=False,
        )
        return _measure_metric("tool_correctness", metric, test_case)
    except Exception as exc:
        return EvaluationMetricResult(
            name="tool_correctness",
            status="error",
            threshold=threshold,
            reason=f"Tool-correctness metric failed ({type(exc).__name__}); details omitted.",
        )


def _task_completion_skip() -> EvaluationMetricResult:
    return _skipped_metric(
        "task_completion",
        "Skipped: this application exposes no supported agent trajectory or task-step trace for TaskCompletionMetric.",
    )


def _measure_metric(name: str, metric: Any, test_case: Any) -> EvaluationMetricResult:
    try:
        score = float(metric.measure(test_case))
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("Metric returned a score outside the valid range.")
        threshold = float(metric.threshold)
        reason = metric.reason
        return EvaluationMetricResult(
            name=name,
            status="passed" if score >= threshold else "failed",
            score=score,
            threshold=threshold,
            reason=str(reason) if reason else None,
        )
    except Exception as exc:
        return EvaluationMetricResult(
            name=name,
            status="error",
            threshold=float(getattr(metric, "threshold", 0.8)),
            reason=f"Judge metric failed ({type(exc).__name__}); details omitted.",
        )


def _skipped_metric(
    name: str,
    reason: str,
    threshold: float | None = None,
) -> EvaluationMetricResult:
    return EvaluationMetricResult(
        name=name,
        status="skipped",
        threshold=threshold,
        reason=reason,
    )


def _duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))

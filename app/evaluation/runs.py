import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import ValidationError

from app.evaluation.runner import run_evaluation_case
from app.evaluation.schemas import (
    EvaluationCase,
    EvaluationDatasetCaseResult,
    EvaluationDatasetRunRecord,
    EvaluationRunResponse,
    EvaluationRunSummary,
)


class EvaluationRunStoreError(RuntimeError):
    """Raised when a persisted evaluation run cannot be read or updated."""


class EvaluationRunNotFoundError(EvaluationRunStoreError):
    """Raised when a requested evaluation run ID does not exist."""


class EvaluationRunStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(__file__).resolve().parents[2] / "data" / "evaluation_runs.json"
        self._lock = RLock()

    def create(self, selected_cases: list[EvaluationCase], fail_fast: bool) -> EvaluationDatasetRunRecord:
        now = _now()
        record = EvaluationDatasetRunRecord(
            run_id=str(uuid4()),
            status="queued",
            created_at=now,
            updated_at=now,
            fail_fast=fail_fast,
            selected_case_ids=[case.case_id for case in selected_cases],
            summary=_empty_summary(len(selected_cases)),
            results=[],
        )
        with self._lock:
            records = self._read_all()
            records.append(record)
            self._write_all(records)
        return record

    def get(self, run_id: str) -> EvaluationDatasetRunRecord:
        with self._lock:
            record = next((item for item in self._read_all() if item.run_id == run_id), None)
        if record is None:
            raise EvaluationRunNotFoundError("Evaluation run was not found.")
        return record

    def update(self, record: EvaluationDatasetRunRecord) -> EvaluationDatasetRunRecord:
        with self._lock:
            records = self._read_all()
            index = next(
                (position for position, item in enumerate(records) if item.run_id == record.run_id),
                None,
            )
            if index is None:
                raise EvaluationRunNotFoundError("Evaluation run was not found.")
            records[index] = record.model_copy(update={"updated_at": _now()})
            self._write_all(records)
            return records[index]

    def _read_all(self) -> list[EvaluationDatasetRunRecord]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvaluationRunStoreError("Evaluation run storage could not be read.") from exc
        if not isinstance(payload, list):
            raise EvaluationRunStoreError("Evaluation run storage must be a JSON array.")
        try:
            records = [EvaluationDatasetRunRecord.model_validate(item) for item in payload]
        except (ValidationError, TypeError) as exc:
            raise EvaluationRunStoreError("Evaluation run storage contains invalid records.") from exc
        return records

    def _write_all(self, records: list[EvaluationDatasetRunRecord]) -> None:
        temporary_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(
                    [record.model_dump(mode="json") for record in records],
                    temporary_file,
                    ensure_ascii=False,
                    indent=2,
                )
                temporary_file.write("\n")
            os.replace(temporary_path, self.path)
        except OSError as exc:
            raise EvaluationRunStoreError("Evaluation run storage could not be updated.") from exc
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def execute_dataset_run(
    run_id: str,
    selected_cases: list[EvaluationCase],
    fail_fast: bool,
    store: EvaluationRunStore,
) -> None:
    """Execute cases sequentially in a FastAPI background task and persist progress/results."""
    try:
        record = store.get(run_id)
        record = store.update(record.model_copy(update={"status": "running"}))
        stopped = False
        for case in selected_cases:
            if stopped:
                case_result = EvaluationDatasetCaseResult(
                    case_id=case.case_id,
                    category=case.category,
                    status="skipped",
                    reason="Skipped because fail_fast stopped this run after an earlier failed case.",
                )
            else:
                try:
                    evaluation = run_evaluation_case(case)
                    case_result = _case_result(case, evaluation)
                except Exception as exc:
                    case_result = EvaluationDatasetCaseResult(
                        case_id=case.case_id,
                        category=case.category,
                        status="failed",
                        reason=f"Case execution failed ({type(exc).__name__}); details omitted.",
                    )
                if fail_fast and case_result.status == "failed":
                    stopped = True
            record = record.model_copy(
                update={"results": [*record.results, case_result]}
            )
            record = record.model_copy(update={"summary": summarize_results(record.results, len(selected_cases))})
            record = store.update(record)

        final_status = "failed" if record.summary.failed else "completed"
        store.update(record.model_copy(update={"status": final_status}))
    except Exception:
        try:
            record = store.get(run_id)
            store.update(
                record.model_copy(
                    update={
                        "status": "failed",
                        "error": "Dataset evaluation could not be completed; inspect persisted case results.",
                    }
                )
            )
        except EvaluationRunStoreError:
            return


def summarize_results(
    results: list[EvaluationDatasetCaseResult],
    total: int | None = None,
) -> EvaluationRunSummary:
    return _summarize_scope(results, total if total is not None else len(results), include_categories=True)


def _summarize_scope(
    results: list[EvaluationDatasetCaseResult],
    total: int,
    include_categories: bool,
) -> EvaluationRunSummary:
    completed = sum(item.status == "completed" for item in results)
    failed = sum(item.status == "failed" for item in results)
    skipped = sum(item.status == "skipped" for item in results)
    metrics = [
        metric
        for item in results
        if item.result is not None
        for metric in item.result.metrics
    ]
    passed_metrics = sum(metric.status == "passed" for metric in metrics)
    failed_metrics = sum(metric.status == "failed" for metric in metrics)
    error_metrics = sum(metric.status == "error" for metric in metrics)
    skipped_metrics = sum(metric.status == "skipped" for metric in metrics)
    scored_metrics = passed_metrics + failed_metrics
    safety_failures = sum(
        check.status == "failed"
        for item in results
        if item.result is not None
        for check in item.result.deterministic_checks
        if check.name in {"no_cancellation_without_confirmation", "no_unauthorized_order_disclosure"}
    )
    categories: dict[str, EvaluationRunSummary] = {}
    if include_categories:
        for category in sorted({item.category for item in results}):
            category_results = [item for item in results if item.category == category]
            categories[category] = _summarize_scope(
                category_results,
                len(category_results),
                include_categories=False,
            )
    return EvaluationRunSummary(
        total=total,
        completed=completed,
        failed=failed,
        skipped=skipped,
        passed_metrics=passed_metrics,
        failed_metrics=failed_metrics,
        error_metrics=error_metrics,
        skipped_metrics=skipped_metrics,
        metric_pass_rate=passed_metrics / scored_metrics if scored_metrics else None,
        safety_failures=safety_failures,
        quality_gate_passed=(
            failed == 0
            and skipped == 0
            and failed_metrics == 0
            and error_metrics == 0
            and safety_failures == 0
            and scored_metrics > 0
        ),
        by_category=categories,
    )


def _case_result(
    case: EvaluationCase,
    evaluation: EvaluationRunResponse,
) -> EvaluationDatasetCaseResult:
    if evaluation.status == "disabled":
        return EvaluationDatasetCaseResult(
            case_id=case.case_id,
            category=case.category,
            status="skipped",
            result=evaluation,
            reason="Evaluation is disabled.",
        )
    if evaluation.status == "busy":
        return EvaluationDatasetCaseResult(
            case_id=case.case_id,
            category=case.category,
            status="skipped",
            result=evaluation,
            reason="Evaluation capacity is currently full; case was not executed.",
        )
    if evaluation.status in {"agent_error", "judge_error"}:
        return EvaluationDatasetCaseResult(
            case_id=case.case_id,
            category=case.category,
            status="failed",
            result=evaluation,
            reason=evaluation.error or evaluation.status,
        )
    failed_metric = any(metric.status in {"failed", "error"} for metric in evaluation.metrics)
    failed_safety_check = any(check.status == "failed" for check in evaluation.deterministic_checks)
    if failed_metric or failed_safety_check:
        return EvaluationDatasetCaseResult(
            case_id=case.case_id,
            category=case.category,
            status="failed",
            result=evaluation,
            reason="One or more evaluation metrics or deterministic checks failed.",
        )
    return EvaluationDatasetCaseResult(
        case_id=case.case_id,
        category=case.category,
        status="completed",
        result=evaluation,
    )


def _empty_summary(total: int) -> EvaluationRunSummary:
    return EvaluationRunSummary(
        total=total,
        completed=0,
        failed=0,
        skipped=0,
        passed_metrics=0,
        failed_metrics=0,
        error_metrics=0,
        skipped_metrics=0,
        metric_pass_rate=None,
        safety_failures=0,
        quality_gate_passed=False,
        by_category={},
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


evaluation_run_store = EvaluationRunStore()

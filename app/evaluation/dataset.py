import json
import os
import tempfile
from pathlib import Path
from threading import RLock

from pydantic import ValidationError

from app.evaluation.schemas import EvaluationCase, EvaluationCategory


class EvaluationDatasetError(RuntimeError):
    """Raised when the local evaluation dataset cannot be read or written safely."""


class DuplicateEvaluationCaseError(EvaluationDatasetError):
    """Raised when a case ID already exists in the evaluation dataset."""


class EvaluationDatasetStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(__file__).resolve().parents[2] / "data" / "evaluation_cases.json"
        self._lock = RLock()

    def list_cases(
        self,
        category: EvaluationCategory | None = None,
        limit: int | None = None,
    ) -> list[EvaluationCase]:
        with self._lock:
            cases = self._read_cases()
            if category is not None:
                cases = [case for case in cases if case.category == category]
            if limit is not None:
                cases = cases[:limit]
            return cases

    def add_case(self, case: EvaluationCase) -> EvaluationCase:
        with self._lock:
            cases = self._read_cases()
            if any(existing.case_id == case.case_id for existing in cases):
                raise DuplicateEvaluationCaseError(
                    f"Evaluation case '{case.case_id}' already exists."
                )
            cases.append(case)
            self._write_cases(cases)
            return case

    def _read_cases(self) -> list[EvaluationCase]:
        try:
            raw_cases = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise EvaluationDatasetError("The evaluation dataset file is missing.") from exc
        except json.JSONDecodeError as exc:
            raise EvaluationDatasetError("The evaluation dataset contains invalid JSON.") from exc
        except OSError as exc:
            raise EvaluationDatasetError("The evaluation dataset could not be read.") from exc

        if not isinstance(raw_cases, list):
            raise EvaluationDatasetError("The evaluation dataset must be a JSON array.")
        try:
            cases = [EvaluationCase.model_validate(item) for item in raw_cases]
        except (ValidationError, TypeError) as exc:
            raise EvaluationDatasetError("The evaluation dataset contains invalid cases.") from exc

        case_ids = [case.case_id for case in cases]
        if len(case_ids) != len(set(case_ids)):
            raise EvaluationDatasetError("The evaluation dataset contains duplicate case IDs.")
        return cases

    def _write_cases(self, cases: list[EvaluationCase]) -> None:
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
                    [case.model_dump(mode="json") for case in cases],
                    temporary_file,
                    ensure_ascii=False,
                    indent=2,
                )
                temporary_file.write("\n")
            os.replace(temporary_path, self.path)
        except OSError as exc:
            raise EvaluationDatasetError("The evaluation dataset could not be saved.") from exc
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

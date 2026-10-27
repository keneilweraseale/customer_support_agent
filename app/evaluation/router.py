from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from app.evaluation.config import get_evaluation_settings, is_evaluation_access_allowed
from app.evaluation.dataset import (
    DuplicateEvaluationCaseError,
    EvaluationDatasetError,
    EvaluationDatasetStore,
)
from app.evaluation.metrics import get_metric_catalog
from app.evaluation.schemas import (
    EvaluationCase,
    EvaluationCaseListResponse,
    EvaluationCategory,
    EvaluationDatasetRunAccepted,
    EvaluationDatasetRunRecord,
    EvaluationDatasetRunRequest,
    EvaluationDatasetRunResults,
    EvaluationHealthResponse,
    EvaluationMetricsResponse,
    EvaluationRunRequest,
    EvaluationRunResponse,
)
from app.evaluation.runner import run_evaluation_case
from app.evaluation.runs import (
    EvaluationRunNotFoundError,
    EvaluationRunStoreError,
    evaluation_run_store,
    execute_dataset_run,
)

async def require_evaluation_access(
    authorization: str | None = Header(default=None),
) -> None:
    settings = get_evaluation_settings()
    if settings.environment not in {"local", "development", "test"} and not settings.api_token:
        raise HTTPException(status_code=404, detail="Not Found")
    if not is_evaluation_access_allowed(authorization):
        raise HTTPException(
            status_code=401,
            detail="Evaluation API access is not authorized.",
            headers={"WWW-Authenticate": "Bearer"},
        )


router = APIRouter(
    prefix="/eval",
    tags=["evaluation"],
    dependencies=[Depends(require_evaluation_access)],
)
dataset_store = EvaluationDatasetStore()


@router.get("/health", response_model=EvaluationHealthResponse)
async def evaluation_health() -> EvaluationHealthResponse:
    settings = get_evaluation_settings()

    if not settings.enabled:
        return EvaluationHealthResponse(
            status="disabled",
            judge_configured=settings.judge_configured,
            model=settings.model,
            provider=settings.provider,
            message="DeepEval is disabled via DEEPEVAL_ENABLED.",
        )

    if settings.judge_configured:
        return EvaluationHealthResponse(
            status="ready",
            judge_configured=True,
            model=settings.model,
            provider=settings.provider,
            message="DeepEval is enabled and judge credentials are configured.",
        )

    return EvaluationHealthResponse(
        status="disabled",
        judge_configured=False,
        model=settings.model,
        provider=settings.provider,
        message="DeepEval is enabled but the judge credentials are missing. Configure DEEPEVAL_JUDGE_API_KEY or a provider API key before running LLM-based metrics.",
    )


@router.get("/metrics", response_model=EvaluationMetricsResponse)
async def evaluation_metrics() -> EvaluationMetricsResponse:
    return EvaluationMetricsResponse(metrics=get_metric_catalog())


@router.get("/cases", response_model=EvaluationCaseListResponse)
async def list_evaluation_cases(
    category: EvaluationCategory | None = None,
    limit: int | None = Query(default=None, ge=1, le=100),
) -> EvaluationCaseListResponse:
    try:
        matched_cases = await run_in_threadpool(dataset_store.list_cases, category)
    except EvaluationDatasetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    total = len(matched_cases)
    if limit is not None:
        matched_cases = matched_cases[:limit]
    return EvaluationCaseListResponse(total=total, cases=matched_cases)


@router.post(
    "/cases",
    response_model=EvaluationCase,
    status_code=status.HTTP_201_CREATED,
)
async def create_evaluation_case(case: EvaluationCase) -> EvaluationCase:
    try:
        return await run_in_threadpool(dataset_store.add_case, case)
    except DuplicateEvaluationCaseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EvaluationDatasetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/run", response_model=EvaluationRunResponse)
async def run_evaluation(request: EvaluationRunRequest) -> EvaluationRunResponse:
    return await run_in_threadpool(run_evaluation_case, request.case)


@router.post(
    "/dataset/run",
    response_model=EvaluationDatasetRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_evaluation_dataset(
    request: EvaluationDatasetRunRequest,
    background_tasks: BackgroundTasks,
) -> EvaluationDatasetRunAccepted:
    try:
        available_cases = await run_in_threadpool(dataset_store.list_cases, None)
    except EvaluationDatasetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    by_id = {case.case_id: case for case in available_cases}
    unknown_ids = sorted(set(request.case_ids).difference(by_id))
    if unknown_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown evaluation case IDs: {', '.join(unknown_ids)}",
        )

    categories = set(request.categories)
    selected_cases = [
        case
        for case in available_cases
        if (not request.case_ids or case.case_id in request.case_ids)
        and (not categories or case.category in categories)
    ]
    if not selected_cases:
        raise HTTPException(
            status_code=422,
            detail="The requested filters did not select any evaluation cases.",
        )

    try:
        run_record = await run_in_threadpool(
            evaluation_run_store.create,
            selected_cases,
            request.fail_fast,
        )
    except EvaluationRunStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    background_tasks.add_task(
        execute_dataset_run,
        run_record.run_id,
        selected_cases,
        request.fail_fast,
        evaluation_run_store,
    )
    return EvaluationDatasetRunAccepted(
        run_id=run_record.run_id,
        status="queued",
        selected=len(selected_cases),
        message="Evaluation run accepted and scheduled in the background.",
    )


@router.get("/runs/{run_id}", response_model=EvaluationDatasetRunRecord)
async def get_evaluation_run(run_id: str) -> EvaluationDatasetRunRecord:
    try:
        return await run_in_threadpool(evaluation_run_store.get, run_id)
    except EvaluationRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvaluationRunStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/runs/{run_id}/results", response_model=EvaluationDatasetRunResults)
async def get_evaluation_run_results(run_id: str) -> EvaluationDatasetRunResults:
    try:
        record = await run_in_threadpool(evaluation_run_store.get, run_id)
    except EvaluationRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvaluationRunStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return EvaluationDatasetRunResults(
        run_id=record.run_id,
        status=record.status,
        total=record.summary.total,
        results=record.results,
    )

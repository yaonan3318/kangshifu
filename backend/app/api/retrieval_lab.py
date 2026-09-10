"""检索诊断、评测集、配置版本与评测运行接口（RETRIEVAL_LAB_USE）。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.retrieval_lab import (
    CaseImportResult, ConfigVersionCreate, ConfigVersionListResponse, ConfigVersionResponse,
    ConfigVersionUpdate, DictionaryEntryCreate, DictionaryEntryResponse, DictionaryEntryUpdate,
    DictionaryListResponse, EvaluationSetCreate, EvaluationSetListResponse, EvaluationSetResponse,
    EvaluationSetUpdate, RetrievalInspectRequest, RetrievalInspectResponse, RunCompareResponse,
    RunCreate, TestCaseCreate, TestCaseListResponse, TestCaseResponse, TestCaseUpdate,
    TestRunListResponse, TestRunResponse,
)
from app.schemas.search import SearchRequest
from app.services.dictionaries import DictionaryService
from app.services.query_rewrite import QueryRewriteService
from app.services.rbac import require_permission
from app.services.retrieval_config import load_active_config
from app.services.retrieval_evaluation import RetrievalEvaluationService
from app.services.search import SearchService


router = APIRouter(prefix="/api/retrieval-lab", tags=["retrieval-lab"])

RETRIEVAL_LAB_USE = "RETRIEVAL_LAB_USE"


def get_service(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RetrievalEvaluationService:
    user = require_permission(current_user(request), RETRIEVAL_LAB_USE)
    return RetrievalEvaluationService(session, settings, user=user)


def _set_out(service: RetrievalEvaluationService, value) -> EvaluationSetResponse:
    return EvaluationSetResponse(**service.evaluation_set_payload(value))


@router.post("/inspect", response_model=RetrievalInspectResponse)
async def inspect(body: RetrievalInspectRequest, http_request: Request, session: Annotated[Session, Depends(get_session)], settings: Annotated[Settings, Depends(get_settings)]):
    user = require_permission(current_user(http_request), RETRIEVAL_LAB_USE)
    config = load_active_config(session, settings)
    rewriter = QueryRewriteService(settings, config)
    rewrite = await rewriter.rewrite(body.query, body.history)
    queries = await rewriter.multi_query(rewrite.retrieval_query)
    if rewrite.retrieval_query not in queries:
        queries.insert(0, rewrite.retrieval_query)
    outcome = SearchService(session, settings, user=user, config=config).search_with_diagnostics(
        SearchRequest(
            query=rewrite.retrieval_query, knowledge_base_id=body.knowledge_base_id,
            limit=body.limit, include_stages=True,
        ),
        extra_queries=queries[1:],
    )
    return RetrievalInspectResponse(
        items=outcome.items, diagnostics=outcome.diagnostics,
        query_rewrite=rewrite.to_info(), queries=queries,
    )


# ---------------------------------------------------------------- 评测集

@router.get("/evaluation-sets", response_model=EvaluationSetListResponse)
def list_evaluation_sets(service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    items = service.list_evaluation_sets()
    return EvaluationSetListResponse(items=[_set_out(service, item) for item in items], total=len(items))


@router.post("/evaluation-sets", response_model=EvaluationSetResponse, status_code=status.HTTP_201_CREATED)
def create_evaluation_set(body: EvaluationSetCreate, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    return _set_out(service, service.create_evaluation_set(body))


@router.get("/evaluation-sets/{set_id}", response_model=EvaluationSetResponse)
def get_evaluation_set(set_id: uuid.UUID, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    return _set_out(service, service.get_evaluation_set(set_id))


@router.patch("/evaluation-sets/{set_id}", response_model=EvaluationSetResponse)
def update_evaluation_set(set_id: uuid.UUID, body: EvaluationSetUpdate, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    return _set_out(service, service.update_evaluation_set(set_id, body))


@router.delete("/evaluation-sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evaluation_set(set_id: uuid.UUID, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    service.delete_evaluation_set(set_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- 标准问题

@router.get("/evaluation-sets/{set_id}/cases", response_model=TestCaseListResponse)
def list_set_cases(set_id: uuid.UUID, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    service.get_evaluation_set(set_id)
    items = service.list_cases(set_id)
    return TestCaseListResponse(items=[TestCaseResponse.model_validate(item) for item in items], total=len(items))


@router.post("/evaluation-sets/{set_id}/cases", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
def create_set_case(set_id: uuid.UUID, body: TestCaseCreate, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    return TestCaseResponse.model_validate(service.create_case(body, set_id=set_id))


@router.post("/evaluation-sets/{set_id}/import", response_model=CaseImportResult)
async def import_set_cases(
    set_id: uuid.UUID,
    service: Annotated[RetrievalEvaluationService, Depends(get_service)],
    file: Annotated[UploadFile, File()],
):
    content = await file.read()
    result = service.import_cases(set_id, file.filename or "", content)
    return CaseImportResult(**result)


@router.patch("/cases/{case_id}", response_model=TestCaseResponse)
def update_case(case_id: uuid.UUID, body: TestCaseUpdate, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    return TestCaseResponse.model_validate(service.update_case(case_id, body))


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_case(case_id: uuid.UUID, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    service.delete_case(case_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- 配置版本

@router.get("/config-versions", response_model=ConfigVersionListResponse)
def list_config_versions(service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    items = service.list_config_versions()
    return ConfigVersionListResponse(items=[ConfigVersionResponse.model_validate(item) for item in items], total=len(items))


@router.post("/config-versions", response_model=ConfigVersionResponse, status_code=status.HTTP_201_CREATED)
def create_config_version(body: ConfigVersionCreate, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    return ConfigVersionResponse.model_validate(service.create_config_version(body))


@router.get("/config-versions/compare")
def compare_config_versions(
    service: Annotated[RetrievalEvaluationService, Depends(get_service)],
    left: uuid.UUID = Query(), right: uuid.UUID = Query(),
):
    return {"differences": service.config_diff(left, right)}


@router.get("/config-versions/{config_id}", response_model=ConfigVersionResponse)
def get_config_version(config_id: uuid.UUID, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    return ConfigVersionResponse.model_validate(service.get_config_version(config_id))


@router.patch("/config-versions/{config_id}", response_model=ConfigVersionResponse)
def update_config_version(config_id: uuid.UUID, body: ConfigVersionUpdate, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    return ConfigVersionResponse.model_validate(service.update_config_version(config_id, body))


@router.delete("/config-versions/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_config_version(config_id: uuid.UUID, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    service.delete_config_version(config_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- 运行与对比

@router.post("/runs", response_model=TestRunResponse, status_code=status.HTTP_201_CREATED)
async def run_evaluation(body: RunCreate, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    return TestRunResponse.model_validate(await service.run_evaluation(body))


@router.get("/runs", response_model=TestRunListResponse)
def list_runs(
    service: Annotated[RetrievalEvaluationService, Depends(get_service)],
    evaluation_set_id: uuid.UUID | None = None,
):
    items = service.list_runs(evaluation_set_id)
    return TestRunListResponse(items=[TestRunResponse.model_validate(item) for item in items], total=len(items))


@router.get("/runs/compare", response_model=RunCompareResponse)
def compare_runs(
    service: Annotated[RetrievalEvaluationService, Depends(get_service)],
    left: uuid.UUID = Query(), right: uuid.UUID = Query(),
):
    result = service.compare_runs(left, right)
    return RunCompareResponse(
        left=TestRunResponse.model_validate(result["left"]),
        right=TestRunResponse.model_validate(result["right"]),
        metric_deltas=result["metric_deltas"],
        config_differences=result["config_differences"],
        case_changes=result["case_changes"],
    )


@router.get("/runs/{run_id}", response_model=TestRunResponse)
def get_run(run_id: uuid.UUID, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    return TestRunResponse.model_validate(service.get_run(run_id))


# ---------------------------------------------------------------- 检索词典

def get_dictionary_service(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> DictionaryService:
    require_permission(current_user(request), RETRIEVAL_LAB_USE)
    return DictionaryService(session)


@router.get("/dictionaries", response_model=DictionaryListResponse)
def list_dictionaries(
    service: Annotated[DictionaryService, Depends(get_dictionary_service)],
    category: str | None = None,
    enabled: bool | None = None,
):
    """列出同义词/缩写/专有名词词典词条。"""
    items = service.list(category=category, enabled=enabled)
    return DictionaryListResponse(
        items=[DictionaryEntryResponse.model_validate(item) for item in items], total=len(items),
    )


@router.post("/dictionaries", response_model=DictionaryEntryResponse, status_code=status.HTTP_201_CREATED)
def create_dictionary_entry(
    body: DictionaryEntryCreate,
    service: Annotated[DictionaryService, Depends(get_dictionary_service)],
):
    return DictionaryEntryResponse.model_validate(
        service.create(body.category, body.term, body.expansions, body.enabled)
    )


@router.patch("/dictionaries/{entry_id}", response_model=DictionaryEntryResponse)
def update_dictionary_entry(
    entry_id: uuid.UUID,
    body: DictionaryEntryUpdate,
    service: Annotated[DictionaryService, Depends(get_dictionary_service)],
):
    return DictionaryEntryResponse.model_validate(
        service.update(entry_id, term=body.term, expansions=body.expansions, enabled=body.enabled)
    )


@router.delete("/dictionaries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dictionary_entry(
    entry_id: uuid.UUID,
    service: Annotated[DictionaryService, Depends(get_dictionary_service)],
):
    service.delete(entry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

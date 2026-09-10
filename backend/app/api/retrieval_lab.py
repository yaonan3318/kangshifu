"""检索诊断、标准问题和评测运行接口（仅管理员）。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.retrieval_lab import RetrievalInspectRequest, RetrievalInspectResponse, TestCaseCreate, TestCaseListResponse, TestCaseResponse, TestCaseUpdate, TestRunListResponse, TestRunResponse
from app.schemas.search import SearchRequest
from app.services.permissions import require_admin
from app.services.retrieval_evaluation import RetrievalEvaluationService
from app.services.search import SearchService


router = APIRouter(prefix="/api/retrieval-lab", tags=["retrieval-lab"])


def get_service(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RetrievalEvaluationService:
    require_admin(current_user(request))
    return RetrievalEvaluationService(session, settings, user=current_user(request))


@router.post("/inspect", response_model=RetrievalInspectResponse)
def inspect(body: RetrievalInspectRequest, http_request: Request, session: Annotated[Session, Depends(get_session)], settings: Annotated[Settings, Depends(get_settings)]):
    user = require_admin(current_user(http_request))
    outcome = SearchService(session, settings, user=user).search_with_diagnostics(SearchRequest(
        query=body.query, knowledge_base_id=body.knowledge_base_id, limit=body.limit, include_stages=True,
    ))
    return RetrievalInspectResponse(items=outcome.items, diagnostics=outcome.diagnostics)


@router.get("/cases", response_model=TestCaseListResponse)
def list_cases(service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    items = service.list_cases()
    return TestCaseListResponse(items=[TestCaseResponse.model_validate(item) for item in items], total=len(items))


@router.post("/cases", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
def create_case(body: TestCaseCreate, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    return TestCaseResponse.model_validate(service.create_case(body))


@router.patch("/cases/{case_id}", response_model=TestCaseResponse)
def update_case(case_id: uuid.UUID, body: TestCaseUpdate, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    return TestCaseResponse.model_validate(service.update_case(case_id, body))


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_case(case_id: uuid.UUID, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    service.delete_case(case_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/runs", response_model=TestRunResponse, status_code=status.HTTP_201_CREATED)
def run_cases(service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    return TestRunResponse.model_validate(service.run())


@router.get("/runs", response_model=TestRunListResponse)
def list_runs(service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    items = service.list_runs()
    return TestRunListResponse(items=[TestRunResponse.model_validate(item) for item in items], total=len(items))


@router.get("/runs/{run_id}", response_model=TestRunResponse)
def get_run(run_id: uuid.UUID, service: Annotated[RetrievalEvaluationService, Depends(get_service)]):
    return TestRunResponse.model_validate(service.get_run(run_id))

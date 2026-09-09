"""混合检索 HTTP 接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search import SearchService

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("", response_model=SearchResponse)
def search_documents(
    request: SearchRequest,
    http_request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchResponse:
    """按关键词与语义向量同时检索已完成索引的文档片段（仅返回当前用户可见资料）。"""
    user = getattr(http_request.state, "auth_user", None)
    outcome = SearchService(session, settings, user=user).search_with_diagnostics(request)
    return SearchResponse(query=request.query.strip(), items=outcome.items, total=len(outcome.items), diagnostics=outcome.diagnostics)

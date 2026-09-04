"""混合检索 HTTP 接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search import SearchService

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("", response_model=SearchResponse)
def search_documents(
    request: SearchRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchResponse:
    """按关键词与语义向量同时检索已完成索引的文档片段。"""
    items = SearchService(session, settings).search(request)
    return SearchResponse(query=request.query.strip(), items=items, total=len(items))

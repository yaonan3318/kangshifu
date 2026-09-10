"""混合检索 HTTP 接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.search import SearchRequest, SearchResponse
from app.services.query_rewrite import QueryRewriteService
from app.services.rbac import require_permission
from app.services.retrieval_config import load_active_config
from app.services.search import SearchService

router = APIRouter(prefix="/api/search", tags=["search"])

SEARCH_USE = "SEARCH_USE"


@router.post("", response_model=SearchResponse)
async def search_documents(
    request: SearchRequest,
    http_request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchResponse:
    """关键词 + 语义混合检索（仅返回当前用户可见资料）。

    默认检索配置版本开启 Query Rewrite / Multi-query 时，会先做上下文补全与查询改写，
    再分别召回并按 RRF 融合；关闭时行为与原先一致。
    """
    user = require_permission(getattr(http_request.state, "auth_user", None), SEARCH_USE)
    config = load_active_config(session, settings)
    rewriter = QueryRewriteService(settings, config)
    rewrite = await rewriter.rewrite(request.query)
    queries = await rewriter.multi_query(rewrite.retrieval_query)
    if rewrite.retrieval_query not in queries:
        queries.insert(0, rewrite.retrieval_query)
    search_request = request.model_copy(update={"query": rewrite.retrieval_query})
    outcome = SearchService(session, settings, user=user, config=config).search_with_diagnostics(
        search_request, extra_queries=queries[1:],
    )
    return SearchResponse(
        query=request.query.strip(), items=outcome.items,
        total=len(outcome.items), diagnostics=outcome.diagnostics,
    )

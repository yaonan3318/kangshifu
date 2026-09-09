"""将现有公司资料混合检索包装成 Harness 工具。"""

from pydantic import BaseModel, Field

from app.harness.types import ToolResult
from app.schemas.search import SearchRequest
from app.services.search import SearchService


class CompanySearchArguments(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    extension: str | None = Field(default=None, max_length=16)
    document_name: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=6, ge=1, le=10)


def company_search_handler(service: SearchService):
    async def handler(arguments: CompanySearchArguments) -> ToolResult:
        results = service.search(SearchRequest(**arguments.model_dump()))
        data = [{
            "citation": index, "document": item.document_name, "chunk_id": str(item.chunk_id),
            "sequence": item.sequence_number, "page": item.page_start, "slide": item.slide_number,
            "sheet": item.sheet_name, "content": item.content, "match_type": item.match_type,
            "score": round(item.final_score, 4),
        } for index, item in enumerate(results, start=1)]
        return ToolResult(summary=f"找到 {len(data)} 条公司资料片段", data=data)
    return handler

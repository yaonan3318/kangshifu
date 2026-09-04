"""服务健康检查接口。"""

from fastapi import APIRouter

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    """确认 FastAPI 进程可响应；不代表 OCR、模型等外部组件均可用。"""
    return {"status": "ok"}

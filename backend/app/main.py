"""FastAPI 应用入口：创建应用、注册中间件/异常处理器并挂载各业务路由。

如果从 PHP 项目理解，这个模块同时承担了 ``index.php`` 和框架启动配置的一部分职责；
区别是 Uvicorn 启动后会让应用常驻进程，而不是每个 HTTP 请求都重新执行本文件。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.search import router as search_router
from app.api.answer import router as answer_router
from app.config import Settings, get_settings
from app.errors import AppError

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """使用给定配置创建 FastAPI 实例；传入配置的能力也方便隔离测试环境。"""
    active_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        """应用启动时准备本地目录，关闭时预留统一清理入口。"""
        active_settings.ensure_directories()
        yield

    app = FastAPI(title="Company Search", version="0.1.0", lifespan=lifespan)
    app.state.settings = active_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in active_settings.cors_origins.split(",") if origin.strip()],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        """把可预期的业务异常统一转换成前端可识别的 JSON 结构。"""
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
        """兜底记录未知异常，同时避免把堆栈和敏感信息返回浏览器。"""
        logger.exception("Unhandled application error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "系统内部错误", "details": None}},
        )

    app.include_router(health_router)
    app.include_router(documents_router)
    app.include_router(search_router)
    app.include_router(answer_router)
    return app


# Uvicorn 使用 ``app.main:app`` 导入这个全局对象并开始监听请求。
app = create_app()

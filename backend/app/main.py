"""FastAPI 应用入口：创建应用、注册中间件/异常处理器并挂载各业务路由。

如果从 PHP 项目理解，这个模块同时承担了 ``index.php`` 和框架启动配置的一部分职责；
区别是 Uvicorn 启动后会让应用常驻进程，而不是每个 HTTP 请求都重新执行本文件。
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.assistants import router as assistants_router
from app.api.auth import COOKIE, current_user, router as auth_router, user_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.search import router as search_router
from app.api.answer import router as answer_router
from app.api.harness import router as harness_router
from app.api.batches import router as batches_router
from app.api.knowledge_bases import router as knowledge_bases_router
from app.api.chunks import router as chunks_router
from app.api.retrieval_lab import router as retrieval_lab_router
from app.api.chat import router as chat_router
from app.api.audit import router as audit_router
from app.api.feedback import router as feedback_router
from app.api.stats import router as stats_router
from app.config import Settings, get_settings
from app.db import SessionLocal, get_session
from app.errors import AppError
from app.llm.ollama import OllamaClient
from app.models import User
from app.services.auth import bootstrap, find_by_token

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """使用给定配置创建 FastAPI 实例；传入配置的能力也方便隔离测试环境。"""
    active_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        """应用启动时准备本地目录、引导管理员账号，并可选预热 Ollama 模型。"""
        active_settings.ensure_directories()
        try:
            with SessionLocal() as session:
                bootstrap(session, active_settings.admin_username, active_settings.admin_password)
        except Exception:
            logger.exception("Admin bootstrap failed (migrations may not be applied yet)")

        if active_settings.ollama_warmup_enabled:
            async def warmup_after_start():
                await asyncio.sleep(0.6)
                try:
                    if await OllamaClient(active_settings).warmup():
                        logger.info("Local model warmup finished")
                except Exception:
                    logger.info("Local model warmup skipped (Ollama not ready)")

            task = asyncio.create_task(warmup_after_start())
            yield
            task.cancel()
        else:
            yield

    app = FastAPI(title="Company Search", version="0.1.0", lifespan=lifespan)
    app.state.settings = active_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in active_settings.cors_origins.split(",") if origin.strip()],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    @app.middleware("http")
    async def auth_gate(request: Request, call_next):
        """统一登录鉴权：除登录/健康等公开端点外，/api/* 都必须携带有效会话 Cookie。"""
        path = request.url.path
        public = (
            request.method == "OPTIONS"
            or path in ("/api/auth/login", "/api/auth/me", "/api/auth/logout", "/api/health")
            or path.startswith(("/docs", "/redoc", "/openapi.json"))
            or not path.startswith("/api")
        )
        if not public:
            token = request.cookies.get(COOKIE)
            user = None
            if token:
                try:
                    with SessionLocal() as session:
                        auth_session = find_by_token(session, token)
                        if auth_session is not None:
                            user = session.scalar(
                                select(User).where(User.id == auth_session.user_id)
                                .options(selectinload(User.roles), selectinload(User.department))
                            )
                except Exception:
                    user = None
            if user is None or not user.enabled:
                return JSONResponse(
                    status_code=401,
                    content={"error": {"code": "AUTH_REQUIRED", "message": "请先登录", "details": None}},
                )
            request.state.auth_user = user
        return await call_next(request)

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
    app.include_router(harness_router)
    app.include_router(batches_router)
    app.include_router(knowledge_bases_router)
    app.include_router(chunks_router)
    app.include_router(retrieval_lab_router)
    app.include_router(chat_router)
    app.include_router(assistants_router)
    app.include_router(auth_router)
    app.include_router(user_router)
    app.include_router(audit_router)
    app.include_router(feedback_router)
    app.include_router(stats_router)
    return app


# Uvicorn 使用 ``app.main:app`` 导入这个全局对象并开始监听请求。
app = create_app()

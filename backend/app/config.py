"""集中定义应用配置，并把 ``COMPANY_SEARCH_`` 环境变量映射为 Python 属性。"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行配置；默认值适合单机 Mac，可由 backend/.env 或环境变量覆盖。"""
    model_config = SettingsConfigDict(env_prefix="COMPANY_SEARCH_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://company_search:company_search@127.0.0.1:54329/company_search"
    library_root: Path = Field(default_factory=lambda: Path.home() / "Library/Application Support/CompanySearch")
    max_upload_bytes: int = 209_715_200
    upload_chunk_bytes: int = 1_048_576
    batch_max_files: int = 1000
    batch_max_total_bytes: int = 10_737_418_240
    batch_min_free_bytes: int = 5_368_709_120
    worker_poll_seconds: float = 1.0
    worker_stale_minutes: int = 30
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024
    embedding_batch_size: int = 8
    search_candidate_limit: int = 30
    search_rrf_k: int = 60
    search_vector_min_similarity: float = 0.55
    search_min_evidence_score: float = 0.35
    search_per_document_limit: int = 3
    # 反馈排序：默认关闭；样本达到门槛后只对排序产生不超过 max_boost 的小幅调整。
    search_feedback_ranking_enabled: bool = False
    search_feedback_min_samples: int = 5
    search_feedback_max_boost: float = 0.05
    search_synonyms: str = "k8s|kubernetes|容器编排;气泡项目|气泡检测|bubble;日报|工作记录|周报"
    # P2-1 检索准确性：Query Rewrite / 上下文补全 / Multi-query / 中文词典 / 拼写纠正。
    # 默认关闭 LLM 改写与多查询，避免改变既有行为与延迟；管理员可在检索配置版本中开启。
    query_rewrite_enabled: bool = False
    query_rewrite_model: str = ""
    context_completion_enabled: bool = False
    context_history_turns: int = 3
    multi_query_enabled: bool = False
    multi_query_count: int = 3
    dictionary_enabled: bool = True
    spelling_correction_enabled: bool = True
    rerank_enabled: bool = False
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_candidate_limit: int = 20
    rerank_batch_size: int = 4
    rerank_max_chars: int = 4000
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    # 保活模式："5m" 为快速问答（回答结束后模型驻留 5 分钟）；"0" 为节省内存（回答后立即释放）。
    # 支持数值秒数或 Ollama 时间串（如 10m、1h）。
    ollama_keep_alive: str = "5m"
    ollama_timeout_seconds: float = 180.0
    # 应用启动后是否预热本地模型，减少首次提问的模型加载等待。
    ollama_warmup_enabled: bool = True
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_api_key: str = ""
    deepseek_timeout_seconds: float = 120.0
    rag_source_limit: int = 6
    rag_history_turns: int = 6
    rag_max_context_chars: int = 18_000
    # P2-5 推荐追问：默认用启发式生成，避免每次问答额外调用大模型；可开启 LLM 生成。
    follow_up_enabled: bool = True
    follow_up_llm_enabled: bool = False
    # 相同问题在资料版本与检索配置未变化时可命中内存回答缓存；关闭可节省内存。
    answer_cache_enabled: bool = True
    answer_cache_size: int = 48
    # 本地账号引导配置：首次启动自动创建管理员账号，请上线前修改默认密码。
    admin_username: str = "admin"
    admin_password: str = "admin123"
    auth_session_days: int = 7
    auth_login_rate_limit: int = 10
    auth_login_rate_window_seconds: int = 300
    k8s_allowed_contexts: str = ""
    harness_max_steps: int = 8
    harness_timeout_seconds: int = 300
    harness_read_timeout_seconds: int = 30
    harness_write_timeout_seconds: int = 300
    harness_approval_minutes: int = 10
    harness_audit_days: int = 30
    harness_max_tool_output_chars: int = 20_000
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    @property
    def originals_root(self) -> Path:
        return self.library_root / "files" / "originals"

    @property
    def quarantine_root(self) -> Path:
        return self.library_root / "files" / "quarantine"

    @property
    def temp_root(self) -> Path:
        return self.library_root / "temp"

    @property
    def models_root(self) -> Path:
        return self.library_root / "models"

    @property
    def allowed_k8s_contexts(self) -> list[str]:
        """返回管理员明确授权给 Harness 使用的 Kubernetes context。"""
        return list(dict.fromkeys(item.strip() for item in self.k8s_allowed_contexts.split(",") if item.strip()))

    def ensure_directories(self) -> None:
        for path in (
            self.originals_root, self.quarantine_root, self.temp_root,
            self.models_root, self.library_root / "logs", self.library_root / "backups",
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """返回进程内复用的配置对象，避免每次依赖注入都重新读取环境变量。"""
    return Settings()

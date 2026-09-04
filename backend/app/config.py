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
    worker_poll_seconds: float = 1.0
    worker_stale_minutes: int = 30
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024
    embedding_batch_size: int = 8
    search_candidate_limit: int = 30
    search_rrf_k: int = 60
    search_vector_min_similarity: float = 0.55
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    ollama_keep_alive: int = 0
    ollama_timeout_seconds: float = 180.0
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_api_key: str = ""
    deepseek_timeout_seconds: float = 120.0
    rag_source_limit: int = 6
    rag_history_turns: int = 6
    rag_max_context_chars: int = 18_000
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

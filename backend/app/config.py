from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COMPANY_SEARCH_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://company_search:company_search@127.0.0.1:54329/company_search"
    library_root: Path = Field(default_factory=lambda: Path.home() / "Library/Application Support/CompanySearch")
    max_upload_bytes: int = 209_715_200
    upload_chunk_bytes: int = 1_048_576
    worker_poll_seconds: float = 1.0
    worker_stale_minutes: int = 30
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

    def ensure_directories(self) -> None:
        for path in (
            self.originals_root, self.quarantine_root, self.temp_root,
            self.library_root / "models", self.library_root / "logs", self.library_root / "backups",
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""批量导入 API 请求与响应结构。"""
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.models import BatchProcessingStatus, BatchStatus, BatchUploadStatus

class BatchFileManifest(BaseModel):
    relative_path: str = Field(min_length=1, max_length=2048)
    original_name: str = Field(min_length=1, max_length=1024)
    size_bytes: int = Field(ge=1)

class BatchCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=128)
    tags: list[str] = Field(default_factory=list, max_length=30)
    note: str | None = Field(default=None, max_length=2000)
    knowledge_base_id: uuid.UUID | None = None
    files: list[BatchFileManifest] = Field(min_length=1)

class BatchFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID; document_id: uuid.UUID | None; relative_path: str; original_name: str
    size_bytes: int; sha256: str | None; upload_status: BatchUploadStatus
    processing_status: BatchProcessingStatus; retry_count: int; error_stage: str | None
    error_code: str | None; error_message: str | None; created_at: datetime; updated_at: datetime

class BatchResponse(BaseModel):
    id: uuid.UUID; name: str; category: str | None; tags: list[str]; note: str | None; knowledge_base_id: uuid.UUID; status: BatchStatus
    total_count: int; indexed_count: int; processing_count: int; duplicate_count: int; failed_count: int; pending_count: int
    created_at: datetime; updated_at: datetime; completed_at: datetime | None

class BatchDetailResponse(BatchResponse):
    files: list[BatchFileResponse]

class BatchListResponse(BaseModel):
    items: list[BatchResponse]; total: int

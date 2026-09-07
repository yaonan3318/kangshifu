"""Harness 状态、任务、工具步骤和审批接口契约。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.harness import ApprovalStatus, HarnessStepStatus, HarnessTaskStatus


class HarnessStatusResponse(BaseModel):
    enabled: bool
    kubectl_available: bool
    contexts: list[str]
    max_steps: int
    timeout_seconds: int


class HarnessApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    task_id: uuid.UUID
    status: ApprovalStatus
    tool_name: str
    context: str
    namespace: str
    target: str
    arguments: dict[str, Any]
    yaml_content: str | None
    yaml_sha256: str | None
    dry_run_output: str | None
    diff_output: str | None
    expires_at: datetime
    actor: str | None
    execution_result: dict[str, Any] | None


class HarnessStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    sequence_number: int
    status: HarnessStepStatus
    tool_name: str | None
    reason: str | None
    arguments: dict[str, Any]
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    duration_ms: int | None


class HarnessTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    question: str
    context: str
    namespace: str
    status: HarnessTaskStatus
    current_step: int
    max_steps: int
    final_answer: str | None
    error_code: str | None
    error_message: str | None
    deadline_at: datetime
    steps: list[HarnessStepResponse]
    approvals: list[HarnessApprovalResponse]


class ApprovalConfirmRequest(BaseModel):
    confirmation_context: str = Field(min_length=1, max_length=255)


class ApprovalRejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)

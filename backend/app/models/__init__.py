"""集中导出 SQLAlchemy ORM 模型，便于业务层和 Alembic 加载。"""

from app.models.document import Document, DocumentStatus
from app.models.identity import (
    AclPermission, AuthSession, Department, DocumentAcl, DocumentVisibility,
    Role, SubjectType, User, user_roles,
)
from app.models.permission import Permission, role_permissions
from app.models.audit import AuditLog
from app.models.document_chunk import DocumentChunk
from app.models.processing_job import JobStatus, JobType, ProcessingJob
from app.models.harness import ApprovalStatus, HarnessApproval, HarnessStep, HarnessStepStatus, HarnessTask, HarnessTaskStatus
from app.models.upload_batch import BatchFile, BatchProcessingStatus, BatchStatus, BatchUploadStatus, UploadBatch
from app.models.knowledge_base import DEFAULT_KNOWLEDGE_BASE_ID, KnowledgeBase
from app.models.tag import Tag, document_tags
from app.models.retrieval_evaluation import (
    EvaluationSet, RetrievalConfigVersion, RetrievalTestCase, RetrievalTestRun,
)
from app.models.dictionary import DictionaryCategory, RetrievalDictionaryEntry
from app.models.chatflow import Chatflow, ChatflowVersion
from app.models.knowledge_gap import KnowledgeGap, KnowledgeGapReason, KnowledgeGapStatus
from app.models.chat import ChatMessage, ChatMessageRole, ChatMessageSource, ChatMessageStatus, ChatProvider, ChatSession
from app.models.assistant import DEFAULT_ASSISTANT_ID, Assistant, assistant_knowledge_bases
from app.models.feedback import (
    AnswerFeedback, AnswerFeedbackDocument, DocumentFeedbackStats,
    FeedbackAggregate, FeedbackCase, FeedbackCaseEvent, FeedbackCaseStatus,
    FeedbackHistory, FeedbackPriority, FeedbackRating, FeedbackRetrievalSnapshot,
    FeedbackType, FeedbackVerificationRun, VerificationStatus,
)
from app.models.answer_job import AnswerJob, AnswerJobStatus, TERMINAL_STATUSES

__all__ = [
    "ApprovalStatus", "Document", "DocumentStatus", "DocumentChunk", "HarnessApproval", "HarnessStep",
    "HarnessStepStatus", "HarnessTask", "HarnessTaskStatus", "ProcessingJob", "JobStatus", "JobType",
    "BatchFile", "BatchProcessingStatus", "BatchStatus", "BatchUploadStatus", "UploadBatch",
    "DEFAULT_KNOWLEDGE_BASE_ID", "KnowledgeBase", "Tag", "document_tags",
    "EvaluationSet", "RetrievalConfigVersion", "RetrievalTestCase", "RetrievalTestRun",
    "DictionaryCategory", "RetrievalDictionaryEntry", "Chatflow", "ChatflowVersion",
    "KnowledgeGap", "KnowledgeGapReason", "KnowledgeGapStatus",
    "ChatMessage", "ChatMessageRole", "ChatMessageSource", "ChatMessageStatus", "ChatProvider", "ChatSession",
    "DEFAULT_ASSISTANT_ID", "Assistant", "assistant_knowledge_bases",
    "AclPermission", "AuthSession", "Department", "DocumentAcl", "DocumentVisibility",
    "Role", "SubjectType", "User", "user_roles", "AuditLog", "AnswerFeedback", "FeedbackRating",
    "DocumentFeedbackStats", "AnswerFeedbackDocument", "Permission", "role_permissions",
    "FeedbackType", "FeedbackCase", "FeedbackCaseStatus", "FeedbackPriority",
    "FeedbackCaseEvent", "FeedbackHistory", "FeedbackRetrievalSnapshot",
    "FeedbackAggregate", "FeedbackVerificationRun", "VerificationStatus",
    "AnswerJob", "AnswerJobStatus", "TERMINAL_STATUSES",
]

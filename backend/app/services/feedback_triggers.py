"""文档/片段/检索配置变更后触发历史负反馈复验的轻量入口。

触发失败只记录日志，不影响核心写操作；只处理与变更对象相关的历史负反馈，
不会把全部反馈统一改为等待复验。
"""

import logging
import uuid

from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.feedback import FeedbackService

logger = logging.getLogger(__name__)


def trigger_reverify(
    session: Session, *, document_ids: list[uuid.UUID] | None = None,
    chunk_ids: list[uuid.UUID] | None = None, config_version_id: uuid.UUID | None = None,
    reason: str = "content_changed",
) -> int:
    try:
        changed = FeedbackService(session, get_settings()).mark_wait_verify_for_documents(
            list(document_ids or []), chunk_ids=list(chunk_ids or []),
            config_version_id=config_version_id, reason=reason,
        )
        if changed:
            logger.info("Feedback re-verification triggered for %s case(s): %s", changed, reason)
        return changed
    except Exception:  # pragma: no cover - 触发失败不能影响核心写操作
        logger.exception("Failed to trigger feedback re-verification")
        try:
            session.rollback()
        except Exception:
            logger.exception("Rollback after re-verification trigger failure failed")
        return 0

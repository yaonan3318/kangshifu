"""运营统计：从聊天、反馈与处理任务中汇总问答质量与检索指标。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    AnswerFeedback, ChatMessage, ChatMessageRole, ChatMessageSource, ChatMessageStatus,
    ChatSession, Document, DocumentStatus, FeedbackRating, ProcessingJob, JobStatus,
)

NO_INTERNAL_ANSWER = "公司资料库中没有找到能够回答这个问题的内部资料。"


def _cutoff(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def compute_overview(session: Session, user, days: int = 7) -> dict:
    if user is None or not user.is_super_admin:
        raise AppError("ADMIN_REQUIRED", "需要管理员权限", 403)
    since = _cutoff(days)
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    user_questions = session.scalars(select(ChatMessage).where(
        ChatMessage.role == ChatMessageRole.USER, ChatMessage.created_at >= since,
    )).all()
    questions_today = sum(1 for item in user_questions if item.created_at >= today_start)
    active_users = session.scalar(
        select(func.count(func.distinct(ChatSession.user_id))).where(
            ChatSession.last_message_at >= since, ChatSession.user_id.is_not(None)
        )
    ) or 0

    answers = session.scalars(select(ChatMessage).where(
        ChatMessage.role == ChatMessageRole.ASSISTANT,
        ChatMessage.status == ChatMessageStatus.COMPLETED,
        ChatMessage.created_at >= since,
    )).all()

    first_tokens: list[float] = []
    totals: list[float] = []
    retrievals: list[float] = []
    local_ok = 0
    local_total = 0
    deepseek_ok = 0
    deepseek_total = 0
    no_answer_samples: list[dict] = []
    provider_counts = {"LOCAL": 0, "DEEPSEEK": 0, "HARNESS": 0}
    cache_hits = 0
    for answer in answers:
        metrics = answer.metrics or {}
        provider = metrics.get("provider") or "LOCAL"
        if provider in provider_counts:
            provider_counts[provider] += 1
        if metrics.get("llm_first_token_ms") is not None:
            first_tokens.append(float(metrics["llm_first_token_ms"]))
        if metrics.get("total_ms") is not None:
            totals.append(float(metrics["total_ms"]))
        if metrics.get("retrieval_ms") is not None:
            retrievals.append(float(metrics["retrieval_ms"]))
        if metrics.get("cache_hit"):
            cache_hits += 1
        if metrics.get("provider") == "DEEPSEEK":
            deepseek_total += 1
            if metrics.get("completion_tokens") is not None:
                deepseek_ok += 1
        if provider == "LOCAL" and metrics.get("completion_tokens") is not None:
            local_total += 1
            local_ok += 1
        if answer.content == NO_INTERNAL_ANSWER:
            no_answer_samples.append({
                "message_id": str(answer.id), "question": "",
                "created_at": answer.created_at.isoformat(),
            })

    def avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 1) if values else None

    questions_by_text: dict[str, int] = {}
    for item in user_questions:
        text = " ".join(item.content.split())[:200]
        questions_by_text[text] = questions_by_text.get(text, 0) + 1
    top_queries = sorted(
        ({"question": question, "count": count} for question, count in questions_by_text.items()),
        key=lambda item: item["count"], reverse=True,
    )[:10]

    citation_rows = session.execute(
        select(ChatMessageSource.document_id, ChatMessageSource.document_name, func.count(ChatMessageSource.id))
        .where(ChatMessageSource.id.in_(
            select(ChatMessageSource.id).join(ChatMessage, ChatMessageSource.message_id == ChatMessage.id)
            .where(ChatMessage.created_at >= since)
        ))
        .group_by(ChatMessageSource.document_id, ChatMessageSource.document_name)
        .order_by(func.count(ChatMessageSource.id).desc()).limit(10)
    ).all()
    top_documents = [
        {"document_id": str(row[0]), "document_name": row[1], "count": row[2]}
        for row in citation_rows
    ]

    feedback_rows = session.execute(
        select(AnswerFeedback.rating, func.count(AnswerFeedback.id))
        .where(AnswerFeedback.created_at >= since)
        .group_by(AnswerFeedback.rating)
    ).all()
    feedback_counts = {rating.value: count for rating, count in feedback_rows}
    total_feedback = sum(feedback_counts.values())

    failures = {
        "parse_failed": session.scalar(select(func.count()).select_from(Document).where(Document.status.in_([DocumentStatus.PARSE_FAILED, DocumentStatus.OCR_FAILED]))) or 0,
        "index_failed": session.scalar(select(func.count()).select_from(Document).where(Document.status == DocumentStatus.INDEX_FAILED)) or 0,
    }
    backlog = session.scalar(
        select(func.count()).select_from(ProcessingJob).where(ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
    ) or 0

    return {
        "days": days,
        "questions": len(user_questions),
        "questions_today": questions_today,
        "active_users": active_users,
        "answers": len(answers),
        "avg_first_token_ms": avg(first_tokens),
        "avg_answer_ms": avg(totals),
        "avg_retrieval_ms": avg(retrievals),
        "cache_hits": cache_hits,
        "provider_counts": provider_counts,
        "local_success_rate": round(local_ok / local_total, 3) if local_total else None,
        "deepseek_success_rate": round(deepseek_ok / deepseek_total, 3) if deepseek_total else None,
        "no_answer_count": len(no_answer_samples),
        "no_answer_samples": no_answer_samples[:10],
        "feedback": {"total": total_feedback, "up": feedback_counts.get("UP", 0), "down": feedback_counts.get("DOWN", 0)},
        "top_queries": top_queries,
        "top_documents": top_documents,
        "failures": failures,
        "backlog": backlog,
    }

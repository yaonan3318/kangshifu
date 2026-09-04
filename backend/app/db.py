"""SQLAlchemy 数据库基础设施：连接池、ORM 基类和请求级 Session。"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型的共同基类，Alembic 也从这里读取表结构元数据。"""
    pass


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI 依赖：每个请求取得独立 Session，请求结束后自动关闭。"""
    with SessionLocal() as session:
        yield session

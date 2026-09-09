"""本地账号认证：bcrypt 密码哈希、会话 Cookie、限流与首次启动引导。"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AuthSession, Department, Role, User

ADMIN_ROLE_NAME = "管理员"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def find_by_token(session: Session, raw_token: str) -> AuthSession | None:
    row = session.scalar(select(AuthSession).where(
        AuthSession.token_hash == hash_token(raw_token),
        AuthSession.expires_at > datetime.now(UTC),
    ))
    return row


def bootstrap(session: Session, username: str, password: str) -> User:
    """首次启动时创建根部门、管理员角色与超级管理员账号；幂等可重复调用。"""
    company = session.scalar(select(Department).where(Department.name == "公司"))
    if company is None:
        company = Department(name="公司", enabled=True)
        session.add(company)
        session.flush()
    admin_role = session.scalar(select(Role).where(Role.name == ADMIN_ROLE_NAME))
    if admin_role is None:
        admin_role = Role(name=ADMIN_ROLE_NAME, description="系统管理员")
        session.add(admin_role)
        session.flush()

    admin = session.scalar(select(User).where(User.username == username))
    if admin is None:
        admin = User(
            id=uuid.uuid4(), username=username, display_name="管理员",
            password_hash=hash_password(password), department_id=company.id,
            enabled=True, is_super_admin=True,
        )
        admin.roles.append(admin_role)
        session.add(admin)
        session.commit()
        session.refresh(admin)
    return admin


def create_session_token(session: Session, user: User, ip_address: str | None = None, days: int = 7) -> str:
    token = secrets.token_urlsafe(32)
    row = AuthSession(
        user_id=user.id, token_hash=hash_token(token),
        expires_at=datetime.now(UTC) + timedelta(days=days),
        ip_address=ip_address,
    )
    session.add(row)
    session.commit()
    return token


def revoke_session(session: Session, raw_token: str) -> None:
    if not raw_token:
        return
    session.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(raw_token)))
    session.commit()


def authenticate(session: Session, username: str, password: str) -> User:
    user = session.scalar(select(User).where(User.username == username.strip()))
    if user is None or not user.enabled or not verify_password(password, user.password_hash):
        raise AppError("LOGIN_FAILED", "用户名或密码不正确", 401)
    user.last_login_at = datetime.now(UTC)
    session.commit()
    return user


class LoginRateLimiter:
    """极简进程内登录限流：按 IP 计数并在固定窗口后复位。"""

    def __init__(self, limit: int = 10, window_seconds: int = 300):
        self.limit = limit
        self.window = window_seconds
        self._attempts: dict[str, list[datetime]] = {}

    def check(self, ip: str | None) -> None:
        key = ip or "unknown"
        now = datetime.now(UTC)
        recent = [item for item in self._attempts.get(key, []) if now - item < timedelta(seconds=self.window)]
        self._attempts[key] = recent
        if len(recent) >= self.limit:
            raise AppError("LOGIN_RATE_LIMITED", "登录尝试过于频繁，请稍后再试", 429)
        self._attempts[key].append(now)

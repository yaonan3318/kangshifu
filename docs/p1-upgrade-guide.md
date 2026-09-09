# P1 升级说明（康师傅公司知识助手）

P1 在既有 P0（上传、解析、OCR、切片、混合检索、多知识库、回收站、检索实验室）之上补齐
“会话持久化、问答页面改版、性能优化、助手角色、本地账号与文档权限、答案反馈、运营统计、审计与外发控制”。
所有数据都在原 PostgreSQL 中增量新增，不会清空历史资料。

## 数据库迁移

新增迁移（按顺序执行，均从 0006 之后的编号开始）：

| 迁移 | 内容 |
| --- | --- |
| `0007_chat_sessions` | chat_sessions / chat_messages / chat_message_sources，历史引用快照 |
| `0008_answer_metrics` | chat_messages.metrics JSONB（阶段耗时、token 数） |
| `0009_assistants` | assistants / assistant_knowledge_bases，自动创建默认助手并绑定历史会话 |
| `0010_identity_permissions` | users / departments / roles / user_roles / document_acl / auth_sessions；documents.visibility、owner_user_id |
| `0011_audit_external_control` | audit_logs；documents.sensitivity_level、external_llm_allowed |
| `0012_answer_feedback` | answer_feedback |

启动或升级：执行 `./scripts/setup.sh`（内部会 `alembic upgrade head`）后 `./scripts/start.sh`。

回滚：单批可用 `alembic downgrade -1`（从 0012 往回逐级回滚，例如
`alembic downgrade 0011_audit_external_control`）。

## 首次登录与管理员

- 首次启动自动创建管理员账号：`admin` / `admin123`（通过
  `COMPANY_SEARCH_ADMIN_PASSWORD` 可修改；上线前请务必修改）。
- 登录使用本地账号 + HttpOnly 会话 Cookie；密码以 bcrypt 存储。

## 主要新配置（backend/.env）

```env
# 快速问答模式（默认，回答后模型驻留 5 分钟）；改为 0 即节省内存模式（回答后立即释放）
COMPANY_SEARCH_OLLAMA_KEEP_ALIVE=5m
# 相同问题 + 资料版本 + 检索配置命中内存回答缓存
COMPANY_SEARCH_ANSWER_CACHE_ENABLED=true
# 首次启动引导管理员账号
COMPANY_SEARCH_ADMIN_PASSWORD=admin123
```

## 权限模型（SQL 层过滤）

- 文档支持 `PRIVATE / COMPANY / DEPARTMENT / ROLE / USER`；旧资料默认 COMPANY，升级不影响检索。
- 检索（资料检索、知识问答、检索实验室）统一在 SQL 层按当前用户过滤可见文档，
  共享 `retrieval_policy` / `PermissionResolver`，不是只隐藏按钮。
- 写操作（删除/恢复/永久删除/重处理/停用/编辑 ACL）要求：上传人、管理员或被授予 MANAGE。
- 敏感级别 `CONFIDENTIAL / RESTRICTED` 或 `external_llm_allowed=false` 的资料命中后，
  禁止发送 DeepSeek，页面提示“资料策略禁止使用外部模型”。
- 所有外发请求与关键操作写入 audit_logs（登录/上传/下载/删除/恢复/权限变更/DeepSeek 调用…）。
- Harness 在权限闭环前仅限管理员使用。

## 验收建议

1. 登录 admin 后进入“知识问答”，提问，切到“资料库”再返回——问题和答案仍在。
2. 正在生成时切页再返回，生成继续；刷新后左侧会话可恢复历史。
3. 连续提问第二次明显更快；回答卡片显示首字与总耗时；停用资料后相同问题不再命中缓存。
4. “助手管理”可新建/编辑助手、绑定知识库与系统提示词，聊天顶部可切换助手。
5. “资料库-详情”可看到 visibility；上传人/管理员可在文档上设置可见范围。
6. 对回答点赞/点踩后，管理员在“反馈管理”可查看并标记处理。
7. “运营统计”展示近期问答量、首字/回答/检索耗时、成功率、无答案与热点资料。
8. 回答使用 DeepSeek 时“审计日志”记录 external_llm_call。

## 说明

- 所有批次已分别提交：P1-1/2（会话+页面）、P1-3（性能）、P1-4（助手）、P1-5（账号权限）、
  P1-8（审计/外发控制）、P1-6（反馈）、P1-7（统计）。

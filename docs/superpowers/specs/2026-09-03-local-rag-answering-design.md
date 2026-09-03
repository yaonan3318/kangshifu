# 第四期：本地与 DeepSeek 增强 RAG 问答设计

## 1. 目标

在第三期混合检索之上增加带来源引用的问答能力。系统默认使用 Mac 本机的 Ollama `qwen3:8b` 生成答案；用户主动打开 DeepSeek 增强开关后，DeepSeek 根据相同的内部资料和本地初稿生成最终合并答案。

第四期必须保证：关闭开关时不访问 DeepSeek；缺少 DeepSeek 配置时安全降级到本地答案；没有内部资料时不伪造公司结论或引用。

## 2. 范围

### 包含

- 基于现有关键词与 BGE-M3 向量检索选取问答上下文。
- Ollama `qwen3:8b` 本地答案生成。
- DeepSeek OpenAI 兼容 API 增强。
- 当前浏览器页面内的多轮问答。
- 流式展示处理阶段和答案正文。
- 文档引用、来源展开和知识范围标记。
- 本地模型、DeepSeek 配置及服务状态检查。

### 不包含

- 永久保存聊天记录。
- 实时互联网搜索。
- 用户登录、部门权限和审计。
- 微调或训练 Qwen、BGE-M3、DeepSeek。
- 将 Ollama 模型文件纳入项目仓库。

## 3. 总体数据流

### DeepSeek 开关关闭

1. 浏览器提交问题和当前页面内最近的对话。
2. 后端根据当前问题和有限的对话上下文构造检索查询。
3. 复用混合检索取得最多 6 个可靠片段。
4. 有内部依据时，将带编号的片段交给 `qwen3:8b`；没有依据时直接返回资料库无答案提示，不调用生成模型编造公司结论。
5. 返回本地答案、引用和证据范围。

### DeepSeek 开关打开

1. 先完成与关闭开关相同的检索和本地答案生成。
2. 如果 API Key 已配置，把问题、引用片段和本地初稿一次性发送给 DeepSeek，由 DeepSeek 校正、补充并生成统一答案。
3. 如果 API Key 未配置，不发出 DeepSeek 请求，保留本地答案并返回 `DEEPSEEK_NOT_CONFIGURED` 警告；页面显示“尚未配置 DeepSeek API Key，本次使用本地模型回答”。
4. 如果 DeepSeek 超时、余额不足、限流或服务异常，保留本地答案并返回相应警告。

## 4. 内部资料不足时的行为

系统将响应标记为以下知识范围之一：

- `INTERNAL`：内部片段足以支持回答，答案必须引用对应资料。
- `INTERNAL_LIMITED`：只找到有限依据，只陈述片段可以支持的部分，并提示依据不足。
- `GENERAL`：没有可用内部依据，且用户打开了 DeepSeek；DeepSeek 可以根据通用知识回答，但答案必须明确标记“不来自公司资料库”。
- `NONE`：没有内部依据且 DeepSeek 关闭或不可用；明确提示公司资料库中未找到答案。

通用知识不得伪造内部文档引用。DeepSeek API 不作为实时联网搜索使用。

## 5. 模型适配层

### Ollama

- 默认地址：`http://127.0.0.1:11434`。
- 默认模型：`qwen3:8b`。
- 通过 Ollama Chat API 调用，不向 Python 环境安装或加载 Qwen 权重。
- 每次生成请求设置 `keep_alive: 0`，回答完成后卸载模型以释放统一内存。
- 提示词要求使用中文、基于证据回答、保留引用编号、不输出隐藏推理过程。

### DeepSeek

- 默认地址：`https://api.deepseek.com`。
- 默认模型：`deepseek-chat`，模型名可通过环境变量修改。
- 使用 OpenAI 兼容 Chat Completions 协议。
- API Key 只从后端环境变量读取，不通过 API 返回前端、不写日志、不提交 Git。
- 只在用户当次请求明确设置 `use_deepseek=true` 且 API Key 非空时调用。

适配器具有统一输入输出边界，后续可替换本地模型或其他 OpenAI 兼容云端服务，而不修改 RAG 编排流程。

## 6. API 设计

### 状态接口

`GET /api/answer/status`

返回：

- Ollama 服务是否可达。
- 配置的本地模型名称及是否已经安装。
- DeepSeek 是否已配置，只返回布尔值，不返回 Key。

### 问答接口

`POST /api/answer/stream`

请求字段：

- `question`：当前问题，不能为空。
- `use_deepseek`：用户是否主动打开增强开关。
- `history`：当前页面最近最多 6 轮问答。
- 可选的文件类型、文件名和日期过滤条件。

响应采用 Server-Sent Events，事件包括：

- `stage`：`retrieving`、`local_generating`、`deepseek_enhancing`。
- `sources`：本次使用的内部片段及稳定编号。
- `delta`：答案增量文本。
- `warning`：未配置、超时、限流或降级信息。
- `done`：最终 provider、knowledge scope 和完成状态。
- `error`：无法生成任何答案时的错误。

## 7. 引用与上下文

- 最多向生成模型提供 6 个检索片段，避免无关上下文和过高延迟。
- 每个片段分配 `[1]` 至 `[6]` 的稳定引用编号。
- 来源包含文档 ID、文件名、片段 ID、页码、幻灯片、工作表/行号、章节路径和 OCR 置信度。
- 本地答案和 DeepSeek 合并答案都使用相同引用编号。
- 后端只接受实际提供过的引用编号；前端只为真实来源生成可展开卡片。
- 最近最多 6 轮历史仅用于理解追问，不能替代本轮重新检索。

## 8. 页面设计

在现有顶部导航增加“知识问答”，与“资料检索”“资料库”并列。

问答页包含：

- 对话消息列表。
- 问题输入框和发送按钮。
- “使用 DeepSeek 增强”开关，默认关闭。
- 打开开关时的资料外发提示。
- 未配置 API Key 时的显式警告和本地降级说明。
- 正在检索、千问生成中、DeepSeek 增强中的阶段提示。
- 答案的“本地”“DeepSeek 增强”“通用知识”标签。
- 答案下方可展开的来源卡片。
- 清空当前会话按钮；刷新页面后会话自然清空。

## 9. 配置

```env
COMPANY_SEARCH_OLLAMA_BASE_URL=http://127.0.0.1:11434
COMPANY_SEARCH_OLLAMA_MODEL=qwen3:8b
COMPANY_SEARCH_OLLAMA_KEEP_ALIVE=0
COMPANY_SEARCH_DEEPSEEK_BASE_URL=https://api.deepseek.com
COMPANY_SEARCH_DEEPSEEK_MODEL=deepseek-chat
COMPANY_SEARCH_DEEPSEEK_API_KEY=
COMPANY_SEARCH_RAG_SOURCE_LIMIT=6
COMPANY_SEARCH_RAG_HISTORY_TURNS=6
```

## 10. 错误处理与隐私

- Ollama 未启动或本地模型未安装：页面显示具体启动或拉取命令，不静默改用 DeepSeek。
- DeepSeek 未配置或调用失败：不影响已经生成的本地答案。
- 检索失败：不调用任何生成模型，返回检索错误。
- 浏览器取消请求：后端停止继续生成，能取消时取消上游 HTTP 流。
- 日志记录 provider、阶段、耗时和错误码，但不记录 API Key、完整提示词或内部片段正文。
- DeepSeek 开关状态只影响本次请求，不自动永久开启。

## 11. 验收标准

1. 关闭 DeepSeek 时，网络请求不访问 DeepSeek，只返回带内部引用的 Qwen 答案。
2. 打开 DeepSeek 且配置有效时，返回 DeepSeek 合并答案并保留真实引用。
3. 打开 DeepSeek但没有 API Key 时，返回本地答案和明确的未配置提示。
4. DeepSeek 请求异常时，本地答案仍可用并显示降级原因。
5. 无内部依据且关闭 DeepSeek 时不生成公司结论。
6. 无内部依据且打开 DeepSeek 时，可以显示明确标记的通用知识答案且没有内部引用。
7. 当前页面可以连续追问，每一轮重新检索，刷新后不保留历史。
8. 一次问答结束后，`ollama ps` 不再显示 `qwen3:8b` 持续占用运行内存。
9. API Key 不出现在前端响应、浏览器源码或应用日志中。

## 12. 本地验证约束

按照项目既有约定，服务器只生成代码并执行语法与静态检查，不运行数据库、前端、Ollama 或 DeepSeek 集成测试。完整安装、流式交互、模型内存释放和 DeepSeek 账户验证由 M3 Pro Mac 完成。

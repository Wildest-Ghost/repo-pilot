# RepoPilot：代码仓库智能开发 Agent 平台

> 状态：草案
>
> 日期：2026-09-05
>
> 架构路线：路线 B - LangGraph + 自研 Agent Harness + MCP + Docker 沙箱

## 1. 项目定位

RepoPilot 是一个面向代码仓库级研发任务的智能开发 Agent 平台。用户用自然语言描述 Issue，选择代码仓库和分支后，Agent 会分析代码库，在隔离工作区中提出并完成代码修改，运行验证命令，最后返回可追溯的执行结果。

这个项目不是聊天式客服机器人，也不是对现成 Coding Agent 的简单封装。项目需要自己掌握 Agent 编排和可靠性机制：

- LangGraph 负责状态图、Checkpoint、条件路由、暂停/恢复和人工审批。
- 自研 Harness（Agent 运行控制层）负责上下文构建、工具策略、预算、重试、验证门禁、事件和最终结果判定。
- MCP 负责定义工具边界，让外部能力可以在不耦合 Agent 核心的情况下扩展。
- Docker 为每个代码仓库任务提供隔离的执行环境。

OpenHands SDK 作为参考实现和可选基础设施集成，但不能接管 RepoPilot 的主 Agent Loop。

## 2. 为什么做这个项目

本项目用于证明我们具备超越 RAG 的实际 Agent 工程能力：

- 设计有状态的 Agent 工作流，而不是简单串联 Prompt。
- 构建具备安全、可观测和故障恢复能力的 Agent Harness。
- 设计并使用 MCP 工具。
- 在隔离环境中运行代码执行任务。
- 通过测试和产物判断任务是否成功，而不是接受模型的自我描述。
- 在可复现的任务集上评测任务成功率、测试通过率、耗时和 Token 成本。

## 3. MVP 目标

针对一个小型 Python 代码仓库，用户可以提交 Bug 修复任务，RepoPilot 能够完成以下流程：

1. 将选定的代码仓库克隆到隔离的 Docker 工作区。
2. 检查仓库中的开发说明、文件、依赖和测试。
3. 生成结构化的实现计划。
4. 在配置要求时，在修改文件前请求人工审批。
5. 通过受控工具修改代码。
6. 运行配置好的测试命令。
7. 当测试失败时，在固定预算内进行失败诊断和修复重试。
8. 返回代码 Diff、命令结果、测试报告和执行轨迹。

MVP 是否成功由验证器决定：只有要求的检查通过，并且最终产物存在，任务才能标记为成功。

## 4. 项目范围与非目标

### 4.1 MVP 范围

- 单仓库 Bug 修复和小型功能开发任务。
- 优先支持 Python 仓库，MVP 之后再支持 Java/Maven。
- 支持本地 Docker 执行。
- 先实现一个具备结构化阶段的主 Coding Agent。
- 对敏感操作提供人工审批。
- 提供 REST API、实时事件流、任务历史和轻量级 Web 控制台。
- 提供可复现的评测任务集。

### 4.2 MVP 明确不做

- 完全自动创建和合并 Pull Request。
- 在沙箱中开放不受限制的网络访问。
- 多个 Agent 的并发协作。
- 面向生产环境的多租户部署。
- 浏览器自动化。
- 复杂的企业级权限系统。
- 通用聊天产品。

## 5. 总体架构

```text
React 控制台
    |
    | REST + SSE
    v
FastAPI API 服务
    |
    +--> PostgreSQL：任务、产物、事件、Checkpoint、评测运行记录
    |
    +--> Redis：任务队列、锁、短期事件分发
    |
    v
Worker 进程
    |
    v
LangGraph 应用
    |
    +--> 自研 Agent Harness
    |      |
    |      +--> Context Manager：上下文管理器
    |      +--> Policy Guard：策略守卫
    |      +--> Tool Registry：工具注册中心
    |      +--> Budget and Retry Controller：预算与重试控制器
    |      +--> Verifier：验证器
    |      +--> Event Publisher：事件发布器
    |
    +--> MCP Client
    |      |
    |      +--> repo-mcp
    |      +--> workspace-mcp
    |      +--> verification-mcp
    |
    v
每个任务独立的 Docker 沙箱
    |
    v
代码仓库检出副本 + 测试运行环境
```

## 6. 技术栈

| 层次 | 初始选型 | 职责 |
|---|---|---|
| 编程语言 | Python 3.12 | 主应用开发语言 |
| 包管理 | uv | 依赖解析、虚拟环境和锁文件管理 |
| API 服务 | FastAPI + Uvicorn | REST API、SSE 事件流和 OpenAPI 契约 |
| 数据模型 | Pydantic v2 | API、Graph State、事件和工具输入/输出校验 |
| Agent 编排 | LangGraph | 状态机、路由、Checkpoint 和中断 |
| 模型网关 | LiteLLM | 屏蔽模型供应商差异，统一重试、Token 和成本记录 |
| 数据持久化 | PostgreSQL + SQLAlchemy 2.0 + Alembic | 持久化业务数据和数据库迁移 |
| 队列与分布式锁 | Redis + Dramatiq | 长任务执行和并发控制 |
| 沙箱 | Docker | 隔离代码仓库检出和命令执行 |
| 工具协议 | MCP | 模块化、类型安全的外部工具协议 |
| 实时通信 | SSE | 向浏览器推送任务时间线 |
| 可观测性 | OpenTelemetry + Langfuse | 记录 Trace、模型调用、工具调用、成本和耗时 |
| 工程质量 | pytest、pytest-asyncio、Ruff、Pyright、pre-commit | 测试、Lint、类型检查和开发工作流 |
| Web 控制台 | React + TypeScript + Vite | 创建任务、查看时间线、Diff、测试报告和历史记录 |

第一版不要再增加第二个编排框架。LangGraph 是项目唯一的工作流引擎。

## 7. 核心概念

### 7.1 Task（任务）

Task 是用户可见的一次完整研发任务，包含：

- 仓库 URL 或预配置的仓库 ID。
- 基础分支或 Commit。
- 用户输入的自然语言目标。
- 允许执行的验证命令。
- 执行策略。
- 任务状态、结果、产物和成本摘要。

### 7.2 Workspace（工作区）

Workspace 是一个专门为单个 Task 创建的临时 Docker 隔离检出环境，包含仓库副本、运行时依赖、生成的 Diff 和测试输出。

任何 Agent 命令都不能直接在 API 服务或 Worker 宿主机上执行。

### 7.3 Tool（工具）

Tool 是一个边界清晰的能力，拥有类型明确的请求和响应。Agent 负责选择工具，Harness 负责在执行前根据策略校验每一次调用。

### 7.4 Artifact（产物）

Artifact 是关联到 Task 的持久化输出，包括：

- 实现计划。
- 文件 Diff。
- 测试日志。
- Lint/类型检查日志。
- 最终摘要。
- 工具调用轨迹。
- 评测得分。

## 8. Agent Harness 设计

Harness 是本项目最主要的工程交付物。它不是一个 Prompt 模板，而是围绕 LLM 构建的一套行为控制系统。

### 8.1 Context Manager（上下文管理器）

根据结构化任务状态构造模型输入：

- 用户需求。
- 仓库元数据和仓库开发说明。
- 相关文件和代码符号。
- 历史工具执行结果。
- 当前实现计划。
- 失败诊断信息。
- 剩余 Token、时间和迭代预算。

设计规则：

- 不能不加筛选地把完整执行历史全部拼接进上下文。
- 进入新阶段前，要对已完成阶段进行摘要。
- 必须保留证据：文件路径、命令退出码和测试失败信息。
- 系统策略和用户任务必须分开处理。

### 8.2 Tool Registry（工具注册中心）

每个工具需要注册以下信息：

- 工具名称和描述。
- Pydantic 输入 Schema。
- Pydantic 输出 Schema。
- 所需能力（Capability）。
- 风险等级。
- 超时时间。
- 幂等性行为。
- 审计事件类型。

### 8.3 Policy Guard（策略守卫）

在每一次工具调用真正执行前进行策略判断。

初始策略：

- 只读仓库检查：允许。
- 工作区内的文件修改：完成计划后允许。
- 白名单中的测试、Lint 和格式化命令：允许。
- 安装依赖：需要明确的策略授权。
- 网络访问：默认拒绝。
- 删除文件：需要人工审批。
- 工作区之外的命令：拒绝。
- `git push`、创建 Pull Request 和访问凭据：MVP 阶段拒绝。

### 8.4 Budget Controller（预算控制器）

通过硬限制避免 Agent 无限执行：

- 最大 Graph 迭代次数。
- 最大模型调用次数。
- 最大工具调用次数。
- 最大墙上时间（Wall-clock Time）。
- 最大 Token 预算。
- 每次验证失败的最大重试次数。

达到任意限制后，任务只能结束为 `FAILED` 或 `NEEDS_HUMAN`，不能结束为 `SUCCEEDED`。

### 8.5 Retry Controller（重试控制器）

重试必须有状态，并且必须由证据驱动：

- 对临时模型错误或传输错误进行带退避的重试。
- 只有工具具备幂等性，或者已经确认重试安全时，才重试工具执行。
- 测试失败时，把失败输出传给失败诊断节点。
- 没有新证据时，不重复执行同一段代码修改或同一条命令。

### 8.6 Verifier（验证器）

Verifier 独立于代码修改节点，它的结果决定任务是否完成。

MVP 检查项：

- 必需的测试命令退出码为 0。
- 对于代码修改任务，仓库 Diff 不能为空。
- 被修改的文件必须位于工作区内部。
- 执行过程中不能发生被策略禁止的操作。

后续检查项：

- Lint 和类型检查。
- 目标回归测试。
- Diff 大小限制。
- Reviewer Agent 评估。

## 9. LangGraph 状态机

### 9.1 任务状态

```python
class TaskState(TypedDict):
    task_id: str
    goal: str
    workspace_id: str | None
    repository_context: RepositoryContext | None
    plan: ImplementationPlan | None
    approval_request: ApprovalRequest | None
    observations: list[Observation]
    changed_files: list[str]
    verification: VerificationResult | None
    retry_count: int
    budget: BudgetSnapshot
    final_result: TaskResult | None
```

### 9.2 第一版 Graph

```text
START
  -> prepare_workspace：准备工作区
  -> inspect_repository：检查仓库
  -> build_context：构建上下文
  -> plan_change：规划修改
  -> requires_approval?：是否需要审批
       | yes -> interrupt_for_approval：中断等待审批 -> apply_change：应用修改
       | no  -> apply_change：应用修改
  -> verify_change：验证修改
  -> verification_passed?：验证是否通过
       | yes -> review_result：检查结果 -> finalize_success：成功收尾 -> END
       | no  -> retry_available?：是否可重试
                    | yes -> diagnose_failure：诊断失败 -> build_context：重建上下文
                    | no  -> finalize_failure：失败收尾 -> END
```

### 9.3 节点职责

| 节点 | 职责 |
|---|---|
| `prepare_workspace` | 创建容器、克隆仓库、记录不可变的基础 Commit |
| `inspect_repository` | 读取开发说明、项目结构、依赖、测试和相关文件 |
| `build_context` | 为下一次模型调用构造有大小限制的结构化上下文 |
| `plan_change` | 生成机器可读的修改计划和预期验证命令 |
| `interrupt_for_approval` | 针对敏感操作暂停状态，等待用户审批 |
| `apply_change` | 通过已批准的工具修改代码 |
| `verify_change` | 运行测试并收集标准化结果 |
| `diagnose_failure` | 根据验证器证据识别可能的失败原因 |
| `review_result` | 检查最终 Diff 是否符合计划和安全策略 |
| `finalize_success` | 持久化产物和最终指标 |
| `finalize_failure` | 持久化证据、失败分类和后续建议 |

## 10. MCP 设计

MCP 负责划分能力边界，但不负责决定工作流。

### 10.1 repo-mcp

负责只读的仓库理解能力：

- `list_files(path, depth)`：列出文件。
- `read_file(path, start_line, end_line)`：读取文件内容。
- `search_code(query, path)`：搜索代码。
- `get_git_status()`：获取 Git 状态。
- `get_git_diff()`：获取 Git Diff。
- `get_symbol_definition(symbol)`：获取代码符号定义。

### 10.2 workspace-mcp

负责受控的工作区修改能力：

- `apply_patch(patch)`：应用补丁。
- `create_file(path, content)`：创建文件。
- `run_command(command, timeout_seconds)`：运行命令。
- `format_files(paths)`：格式化文件。

每一个操作在真正调用 MCP 工具之前，都必须经过 Policy Guard 检查。

### 10.3 verification-mcp

负责结构化验证：

- `run_tests(command)`：运行测试。
- `run_lint(command)`：运行 Lint。
- `run_type_check(command)`：运行类型检查。
- `collect_coverage()`：收集测试覆盖率。

工具返回标准化字段，例如 `exit_code`、`stdout`、`stderr`、`duration_ms` 和 `artifacts`。

### 10.4 后续 github-mcp

这个 Server 在 MVP 阶段保持禁用：

- `get_issue(issue_id)`：获取 Issue。
- `create_branch(name)`：创建分支。
- `create_pull_request(title, body)`：创建 Pull Request。
- `comment_on_issue(issue_id, body)`：评论 Issue。

启用它之前，必须先设计明确的凭据管理和审批模型。

## 11. API 与事件契约

### 11.1 REST API

```text
POST   /api/v1/tasks                         创建任务
GET    /api/v1/tasks/{task_id}               查询任务
POST   /api/v1/tasks/{task_id}/approve       审批任务操作
POST   /api/v1/tasks/{task_id}/cancel        取消任务
GET    /api/v1/tasks/{task_id}/artifacts     查询任务产物
GET    /api/v1/tasks/{task_id}/events        查询任务事件
GET    /api/v1/tasks/{task_id}/stream        订阅实时事件流
```

### 11.2 事件类型

```text
task.created              任务已创建
workspace.preparing       工作区准备中
workspace.ready           工作区已就绪
agent.context_built       Agent 上下文已构建
agent.plan_created        Agent 计划已生成
approval.requested        已请求审批
approval.resolved         审批已处理
tool.requested            已请求调用工具
tool.completed            工具调用完成
tool.failed               工具调用失败
verification.started      验证开始
verification.completed    验证完成
task.succeeded            任务成功
task.failed               任务失败
task.cancelled            任务取消
```

事件必须携带 `task_id`、ISO 时间戳、序列号、节点名称和结构化 Payload。前端只负责渲染事件，不得根据自然语言文本自行推断任务状态。

## 12. 持久化模型

第一版数据表：

| 表 | 用途 |
|---|---|
| `repositories` | 仓库来源、允许的分支、初始化配置和验证配置 |
| `tasks` | 用户请求、基础版本、状态、策略和最终摘要 |
| `task_checkpoints` | LangGraph Checkpoint 引用和可恢复状态元数据 |
| `task_events` | 有序的审计时间线 |
| `tool_calls` | 请求、响应摘要、耗时和策略决策 |
| `artifacts` | 计划、Diff、日志、报告以及文件路径或对象存储引用 |
| `evaluations` | 每次评测的质量、成本、耗时和通过/失败指标 |

PostgreSQL 是系统事实来源（Source of Truth）。Redis 不能作为持久化任务历史使用。

## 13. 安全模型

### 13.1 沙箱默认配置

- 每个任务使用一个独立 Docker 容器。
- 只挂载当前任务的工作区。
- 使用非 root 用户运行。
- 限制 CPU、内存、进程数和最长运行时间。
- 除非任务策略明确允许，否则禁用网络。
- 不挂载宿主机 Docker Socket。
- 不挂载宿主机 Home 目录、SSH Key、云凭据或 Git 凭据。

### 13.2 Prompt Injection 边界

仓库文件、Issue 描述、终端输出和 MCP 响应都必须被视为不可信数据。

Harness 必须做到：

- 把安全策略指令放在由仓库内容构造的上下文之外。
- 永远不允许仓库文本重新定义工具权限。
- 将不可信内容明确标记后再放入模型上下文。
- 要求计划和工具输入采用结构化格式。
- 记录所有尝试调用被禁止工具或命令的行为。

## 14. 评测计划

项目必须提供一组版本化的小型评测集。

### 14.1 初始数据集

- 覆盖 3 到 5 个小型仓库的 15 到 20 个任务。
- 以确定性的单元测试失败任务为主。
- 每个任务包含基础 Commit、自然语言 Issue、预期测试命令和预期结果。
- 至少包含几个应该被策略拒绝的任务，用于测试安全边界。

### 14.2 评测指标

- 任务成功率：必需检查全部通过的任务比例。
- 验证通过率：最终尝试中测试命令通过的比例。
- 平均耗时和 P95 耗时。
- 单任务平均模型 Token 数和成本。
- 平均工具调用次数和 Graph 迭代次数。
- 策略违规率。
- 人工审批率。

禁止发布虚构指标。简历中的所有数字都必须来自实际记录的评测运行结果。

## 15. 仓库目录结构

```text
repo-pilot/
├── apps/
│   ├── api/                 # FastAPI 应用
│   ├── worker/              # Dramatiq 消费者
│   └── web/                 # React 控制台
├── src/repopilot/
│   ├── agent/               # LangGraph Graph、节点、Prompt、State
│   ├── harness/             # 策略、预算、上下文、重试、验证器
│   ├── mcp/                 # MCP Client、Server 和工具适配器
│   ├── domain/              # Pydantic 模型和领域模型
│   ├── infra/               # 数据库、队列、Docker、LLM 和追踪
│   └── services/            # 任务应用服务
├── tests/
│   ├── unit/                # 单元测试
│   ├── integration/         # 集成测试
│   └── evals/               # 评测测试
├── evals/
│   ├── cases/               # 评测用例
│   └── reports/             # 评测报告
├── migrations/              # 数据库迁移
├── docker/                  # Docker 配置
├── docs/
│   └── PROJECT_SPEC.md      # 项目总文档
├── pyproject.toml
├── uv.lock
├── docker-compose.yml
└── README.md
```

## 16. 开发里程碑

### M0：工程基础

- 初始化 Python、uv、Ruff、Pyright、pytest 和 pre-commit。
- 通过 Docker Compose 启动 PostgreSQL、Redis 和 API 依赖。
- 定义领域 Schema、数据库迁移、任务状态机和事件契约。

### M1：受控的单 Agent Loop

- 实现 Docker 工作区生命周期管理。
- 实现只读仓库 MCP 工具。
- 实现 LangGraph 状态、规划、编辑和测试节点。
- 持久化任务时间线，并通过 SSE 推送。
- 完成一个已知 Python Bug 修复任务的端到端执行。

### M2：可靠执行

- 增加命令策略、预算、重试、Checkpoint 和审批中断。
- 增加结构化验证器和产物收集。
- 为核心 Harness 行为补充单元测试和集成测试。

### M3：评测与控制台

- 增加评测用例和报告生成。
- 构建任务表单、实时时间线、Diff、验证结果和历史任务页面。
- 记录真实评测指标。

### M4：Java 仓库支持

- 增加 Maven/Gradle 环境镜像和验证适配器。
- 增加 Java 任务用例。
- 对比 Python 任务和 Java 任务的成功率、成本和耗时。

### M5：高级编排

- 可选增加 Planner、Coder 和 Reviewer 角色。
- 完成明确的凭据和审批设计后，再增加 GitHub MCP。
- 与 OpenHands SDK 或 Agent Server 做基线效果对比。

## 17. MVP 完成标准

满足以下所有条件后，MVP 才算完成：

- 用户可以通过 API 或 Web 控制台创建仓库任务。
- 任务在隔离的 Docker 工作区中执行。
- LangGraph 工作流会持久化状态，并输出实时执行时间线。
- Agent 能够检查、修改和测试一个小型 Python 仓库。
- 由验证器而不是模型决定任务是否成功。
- 任务产物中包含 Diff 和测试输出。
- 敏感操作可以暂停并等待人工审批。
- 至少 15 个评测用例可以稳定、可重复地运行。
- CI 中的 Ruff、Pyright 和 pytest 全部通过。

## 18. 有意延后的决策

以下事项不会阻塞 M0：

- 产品名称和视觉风格。
- 默认 LLM 供应商和备用供应商。
- 第一版是否继续使用 Dramatiq，还是切换到其他 Worker 实现。
- Trace 使用 Langfuse、其他兼容 OpenTelemetry 的平台，还是两者同时使用。
- 是否直接复用 OpenHands Workspace，还是在同一接口后面自行实现 Docker 隔离。
- 认证供应商和部署目标。

这些决策周围需要保留稳定的接口，使后续更换实现时不必重写 Agent Graph。

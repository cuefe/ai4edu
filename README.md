# AI 中小学智教平台

面向学校和教培机构的 AI 教学平台：老师用 AI 备课、出题、批改、看学情；学生用 AI 学习、答疑、刷错题、背考点。

- 功能规划：[docs/功能规划.md](docs/功能规划.md)
- 技术方案：[docs/技术方案.md](docs/技术方案.md)

当前进度：**M0 基础骨架**。包括账号与登录、机构/班级/师生管理、Excel 批量导入学生、跨机构数据隔离、模型网关与用量统计。

## 目录

```
apps/web/          前端（React + Vite + Ant Design）：教师端、学生端、机构管理、平台运营
server/            后端（FastAPI + SQLAlchemy + Celery）
  app/core/        配置、数据库与租户隔离、认证
  app/modules/     业务模块：iam 账号、org 机构班级、ops 运营
  app/ai/gateway/  模型网关；models.yaml 配置技能 → 模型路由
  migrations/      数据库迁移（Alembic）
  tests/           后端测试
deploy/            Docker Compose、Nginx 配置
evals/             AI 技能评测集（M1 起）
docs/              规划与方案文档
```

## 本地开发

需要：Python 3.12、[uv](https://docs.astral.sh/uv/)、Node.js 22+、pnpm。**不需要安装 PostgreSQL 和 Redis**：本地数据库用 `pgserver` 包自带的 PostgreSQL + pgvector，Redis 用内存版。

```bash
# 后端
cd server
uv sync
uv run python -m app.cli db-start     # 启动本地数据库（端口 54329）
uv run python -m app.cli migrate
uv run python -m app.cli seed-demo    # 写入演示数据，会打印演示账号
uv run uvicorn app.main:app --reload --port 8000

# 前端（另开一个终端，在仓库根目录）
pnpm install
pnpm dev:web                          # http://localhost:5173
```

接口文档：http://localhost:8000/api/docs

### 演示账号（仅本地开发）

| 身份 | 登录方式 |
|---|---|
| 平台运营 | 手机号 13800000000，密码 admin1234 |
| 机构管理员 | 手机号 13800000001，密码 demo1234 |
| 老师 | 手机号 13800000002，密码 demo1234 |
| 学生 | 机构代码 demo，学号 s001～s005，密码 123456 |

验证码登录时，验证码打印在后端日志里。

### 常用命令

```bash
cd server && uv run pytest                 # 后端测试（自动起临时数据库）
cd server && uv run ruff check . && uv run ruff format .
pnpm typecheck                             # 前端类型检查
pnpm gen:api                               # 后端接口改动后，重新生成前端类型
cd server && uv run alembic revision --autogenerate -m "说明"   # 新建迁移
cd server && uv run python -m app.cli db-stop
```

### 接入大模型

复制 `server/.env.example` 为 `server/.env`，至少填一家的 API Key（火山方舟、DeepSeek、阿里云百炼），重启后端。在「平台运营 → AI 模型」页面可以看到每个技能实际会用哪个模型，并发送测试请求。不配置时开发环境使用 mock 模型（原样回显输入）。

模型路由和价格在 `server/app/ai/gateway/models.yaml` 里配置。

## 关键约定

- **租户隔离两层保护**：应用层查询必须带 `tenant_id`；数据库层所有带 `tenant_id` 的表开启了行级安全（RLS），应用使用非超级用户账号连接。新建带 `tenant_id` 的表时，在迁移里调用 `migrations/rls.py` 的 `enable_tenant_rls`。
- **调用大模型只走模型网关**：`get_gateway().chat(技能名, messages, ctx=...)`，不要直接用各家 SDK。新技能先在 `models.yaml` 的 `skills` 里登记。
- **个人信息**：手机号加密存储；发给模型前网关会去掉手机号、身份证号。
- **写操作显式提交**：路由里改完数据调用 `db.commit()`。

## 部署

`deploy/docker-compose.yml` 可一键起试点环境（数据库、Redis、API、Worker、Web）。生产环境数据库和 Redis 用云托管服务，`ENV=prod` 时后端会检查密钥是否已替换。

## 与技术方案的差异（M0）

- 平台运营页面暂时放在 `apps/web` 里，按角色隔离；上线前拆到单独部署。
- 前端用 TypeScript 5：生成接口类型的 openapi-typescript 还不支持 TypeScript 7。
- Langfuse 调用追踪还没接入；目前每次模型调用都记在 `ai_usage` 表里。

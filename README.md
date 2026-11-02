# AI 中小学智教平台

面向学校和教培机构的 AI 教学平台：老师用 AI 备课、出题、批改、看学情；学生用 AI 学习、答疑、刷错题、背考点。

- 功能规划：[docs/功能规划.md](docs/功能规划.md)
- 技术方案：[docs/技术方案.md](docs/技术方案.md)

当前进度：**M1 备课与题库**进行中。
- M0 已完成：账号与登录、机构/班级/师生管理、Excel 批量导入学生、跨机构数据隔离、模型网关与用量统计。
- M1 已完成 **AI 生成教案**：填课题流式生成，在线编辑（表格、公式），自动保存，导出 Word（公式是 Word 原生公式）。
- M1 待做：资料上传解析与检索（RAG）、讲义和背诵点生成、出题与校验。

## 目录

```
apps/web/          前端（React + Vite + Ant Design）：教师端、学生端、机构管理、平台运营
server/            后端（FastAPI + SQLAlchemy + Celery）
  app/core/        配置、数据库与租户隔离、认证
  app/modules/     业务模块：iam 账号、org 机构班级、content 教案等文档、ops 运营
  app/ai/gateway/  模型网关；models.yaml 配置技能 → 模型路由
  app/ai/skills/   AI 技能：每个技能一个目录（输入结构、prompt、输出检查）
  migrations/      数据库迁移（Alembic）
  tests/           后端测试
deploy/            Docker Compose、Nginx 配置
evals/             AI 技能评测集；lesson_plan/ 是教案生成的用例和运行脚本
docs/              规划与方案文档
refs/              竞品资料；refs/materials/ 是本地测试用的真实教学资料和试卷（有版权，不入库，来源见其中 README）
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

复制 `server/.env.example` 为 `server/.env`，填写 DeepSeek 和阿里云百炼（通义）的 API Key，重启后端。只填一家时，缺对应模型的技能在开发环境回退到 mock，在生产环境报错（比如没有通义就不能拍照批改）。在「平台运营 → AI 模型」页面可以看到每个技能实际会用哪个模型，并发送测试请求。不配置时开发环境使用 mock 模型（原样回显输入）。

模型路由和价格在 `server/app/ai/gateway/models.yaml` 里配置。

## 关键约定

- **租户隔离两层保护**：应用层查询必须带 `tenant_id`；数据库层所有带 `tenant_id` 的表开启了行级安全（RLS），应用使用非超级用户账号连接。新建带 `tenant_id` 的表时，在迁移里调用 `migrations/rls.py` 的 `enable_tenant_rls`。
- **调用大模型只走模型网关**：`get_gateway().chat(技能名, messages, ctx=...)`，不要直接用各家 SDK。新技能先在 `models.yaml` 的 `skills` 里登记，prompt 写在 `app/ai/skills/<技能>/`，改 prompt 时递增 `PROMPT_VERSION` 并跑 `evals/` 里的评测。
- **文档格式**：教案等文档存 TipTap JSON。模型输出的 Markdown 由 `content/markdown.py` 转换，Word 由 `content/docx_export.py` 导出；编辑器 `DocEditor.tsx` 新增节点类型时，这三处要一起改。
- **个人信息**：手机号加密存储；发给模型前网关会去掉手机号、身份证号。
- **写操作显式提交**：路由里改完数据调用 `db.commit()`。

## 部署

`deploy/docker-compose.yml` 可一键起试点环境（数据库、Redis、API、Worker、Web）。生产环境数据库和 Redis 用云托管服务，`ENV=prod` 时后端会检查密钥是否已替换。

## 与技术方案的差异

- 平台运营页面暂时放在 `apps/web` 里，按角色隔离；上线前拆到单独部署。
- 前端用 TypeScript 5：生成接口类型的 openapi-typescript 还不支持 TypeScript 7。
- Langfuse 调用追踪还没接入；目前每次模型调用都记在 `ai_usage` 表里。
- 教案生成在 API 进程的后台任务里跑，还没进 Celery：老师关掉页面不影响生成，但服务重启会中断正在生成的教案（显示为失败，可重新生成）。并发量上来后再改。
- 教案还不能引用上传的资料（资料解析和检索是 M1 的下一项），目前老师可以把教材原文粘贴到"参考资料"里。
- 文档没有历史版本表（`document_version`），只用版本号防止多个窗口互相覆盖。

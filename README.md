# AI 中小学智教平台

面向学校和教培机构的 AI 教学平台：老师用 AI 备课、出题、批改、看学情；学生用 AI 学习、答疑、刷错题、背考点。

- 技术方案：[docs/技术方案.md](docs/技术方案.md)
- 试点上线清单：[docs/试点上线清单.md](docs/试点上线清单.md)
- 压测记录：[docs/压测记录.md](docs/压测记录.md)

当前进度：**M3 收尾**已完成，MVP 的闭环（老师备课出题 → 布置 → 学生学习、背诵、做题、问一问 → 批改 → 错题本 → 作业报告）已跑通，运营后台、额度、安全加固和压测也做完了。**M4 课程内容**进行中：教材、章节、知识点、思维导图的公共内容层和生成流程已做好，人教版九上数学打样；下一步是铺量（初一至高三）和每周个性化试卷。
- M0：账号与登录、机构/班级/师生管理、Excel 批量导入学生、跨机构数据隔离、模型网关与用量统计。
- M1 **AI 生成教案**：填课题流式生成，在线编辑（表格、公式），自动保存，导出 Word（公式是 Word 原生公式）。
- M1 **资料库**：上传 PDF、Word、PPT、图片，自动解析（扫描件和图片用通义 OCR 识别），切片段、向量化；生成时按课题检索，正文标注引用并附出处；资料可共享给本机构老师。
- M1 **AI 讲义**：给学生的课堂讲义（学习目标、知识梳理并标出考点、例题、易错提醒、练习和答案）或复习讲义（按考点梳理）；和教案共用编辑器、Word 导出、资料库引用。
- M1 **背诵卡片**：从讲义、教案或粘贴的材料里抽取必背内容，做成问答卡和挖空卡，老师可修改，带自测预览。
- M1 **题库与 AI 出题**：按知识点、题型、难度出题；推理模型在看不到答案的情况下独立求解，和题目答案比对（规则、数值、模型三种比对），有分歧的标红并说明原因；老师审核后入库，入库的题本机构老师共享。也可以手动录题。
- M2 **作业**：老师从题库选题，加讲义阅读、背诵卡片，布置给班级；可定时发布、设截止时间、选择答案提交后公布还是截止后公布、开关“作业中问 AI”。学生在线作答，解答题可以拍照上传（最多 3 张）。
- M2 **批改**：提交时客观题马上判分（多选少选得一半，填空按空给分，数值等价的写法算对）；解答题和判断不了的填空由 AI 看文字或照片给分、列扣分点、写评语，老师按 AI 把握从低到高确认或改分，可一键全部确认。改分写审计日志。
- M2 **作业报告**：提交率、平均分、每题正确率、共性错题（错误率 40% 以上）、每个学生的作答；一键催交没交的学生。
- M2 **错题本**：判错的题自动收进来（答案公布后才出现），按学科、知识点筛选；订正时重做（客观题自动判对错，解答题对照答案自评），没思路可以看四步引导（题目解析 → 考点分析 → 逐步讲解 → 思路总结，一步一步展开）或问 AI。
- M2 **背诵**：老师布置的卡片按 FSRS 间隔重复安排复习，每天新学最多 20 张；自评“忘了 / 模糊 / 记得 / 很熟”。
- M2 **问一问**：学习、作业提示（只给提示，回复会再检查有没有泄露答案）、订正三种模式；可拍照提问，一键“讲简单点 / 举个例子 / 编个口诀”。闲聊和不当话题礼貌拉回学习。
- M2 **心理危机预警**：关键词和模型一起识别自伤、轻生、被欺负等信号（宁可多报），学生端立即显示安抚话术和求助电话（号码在配置里），对话不中断；同时生成预警工单，站内信通知任课老师和机构管理员，高风险再发短信；老师必须填写处理记录，超过 2 小时没处理标为超时。
- M2 **站内信**：新作业、催交、危机预警，顶栏铃铛显示未读。
- M3 **套餐与额度**：套餐模板（学生名额、老师名额、每月 AI 额度、服务期），开通、续费机构时选套餐自动带出，可以单独改。名额只算启用中的账号（导入学生时名额用完就停下）；到期、停用的机构不能登录；本月 AI 费用到了额度就拒绝调用（危机识别除外），每个老师每天最多发起 60 次 AI 生成、每个学生每天最多 200 条问一问。
- M3 **平台运营后台**：机构（名额、本月 AI 费用、到期提醒、停用）、套餐、AI 用量（合计、按机构、按天、明细）、AI 模型、内容安全（被拦下的消息、各机构危机预警处理情况）、审计日志。模型价格按官网原价填在 `models.yaml`。
- M3 **机构概况**：机构管理员看套餐、到期日、学生和老师名额、本月 AI 用量和用在了哪些功能；30 天内到期时每个页面顶上提醒续费。学生、老师可以停用、启用（毕业、离职的停用后不占名额）。
- M3 **安全加固**：登录、登录失败写审计日志（含 IP）；验证码每个手机号每天最多 10 条；没开通短信时（`SMS_PROVIDER=none`）只能密码登录、建老师账号必须设密码；Nginx 加 CSP 等安全响应头；密码哈希改用 OWASP 建议参数并限制并发（全班同时登录不会把内存用光），旧哈希登录时自动升级；生产模式启动时检查短信、Redis、CORS 配置。
- M3 **压测**：`app/devtools/loadtest.py` 模拟全校学生做作业、老师看报告。找到并修好了 300 人同时在线时服务卡死的问题（数据库连接池和线程池互相等待）；2 个 API 进程时 600 名学生同时做作业，各接口 p95 在 100 ms 以内，见[压测记录](docs/压测记录.md)。
- M3 **备份**：`deploy/backup.sh` 每天备份数据库和上传的文件，保留 14 天，注释里有恢复步骤。
- M4 **课程内容**：学生、老师按年级和学科看教材，每章每节有知识点（标出核心、重点和要背的）、思维导图（公式正常显示，可折叠）、课件，也能在线看课本 PDF（大文件分段加载）。内容是平台公共内容，所有机构共用；导入后默认是草稿，运营在「教材内容」里抽检后发布。学生首页加了课程和拍题入口。见下面的[生产课程内容](#生产课程内容)。

## 目录

```
apps/web/          前端（React + Vite + Ant Design）：教师端、学生端、机构管理、平台运营
server/            后端（FastAPI + SQLAlchemy + Celery）
  app/core/        配置、数据库与租户隔离、认证
  app/modules/     业务模块：iam 账号、org 机构班级、content 教案和讲义、recite 背诵卡片、qbank 题库、library 资料库、
                   assignment 作业和批改、learning 错题本和背诵复习、tutor 问一问、safety 内容安全和危机预警、
                   notify 站内信、ops 运营、curriculum 教材章节知识点（平台公共内容）
  app/ai/gateway/  模型网关；models.yaml 配置技能 → 模型路由
  app/ai/skills/   AI 技能：每个技能一个目录（输入结构、prompt、输出检查）
  app/ai/parsing/  资料解析：PDF、Word、PPT、图片 → 文本块 → 检索片段
  migrations/      数据库迁移（Alembic）
  tests/           后端测试
deploy/            Docker Compose、Nginx 配置（含安全响应头）、.env.example、备份脚本
evals/             AI 技能评测集；lesson_plan/ 是教案生成的用例和运行脚本
docs/              规划与方案文档
refs/              竞品资料；refs/materials/ 是本地测试用的真实教学资料和试卷（有版权，不入库，来源见其中 README）
```

## 本地开发

需要：Python 3.12、[uv](https://docs.astral.sh/uv/)、Node.js 22+、pnpm。**不需要安装 PostgreSQL 和 Redis**：本地数据库用 `pgserver` 包自带的 PostgreSQL + pgvector，Redis 用内存版。

在仓库根目录一条命令起停：

```bash
pnpm dev     # 起本地数据库、执行迁移、装依赖，在同一个终端里跑后端和前端（http://localhost:5173）；Ctrl+C 全部结束，包括数据库
pnpm stop    # 结束残留的后端、前端和数据库：窗口被直接关掉，或 pnpm dev 提示端口被占用时用
```

第一次启动后，另开一个终端写入演示数据：`cd server && uv run python -m app.cli seed-demo`。Windows PowerShell 默认不允许运行脚本，`pnpm` 会报"禁止运行脚本"，执行一次 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 即可。

分步启动：

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

### 生产课程内容

一册教材一个内容包（JSON），离线生成后用命令导入。大纲、资料和生成结果放在 `refs/` 下，不进仓库。

```bash
cd server
# 1. 按大纲生成：默认调本机 Codex（用登录的 ChatGPT 会员额度）；--engine gateway 走模型网关（默认 DeepSeek，按量计费）
#    --sources 指定资料目录，文件路径里带章名的算这一章的资料（支持 pptx、pdf、docx、txt、md）。已生成的章不会重做，--force 重做
uv run python -m app.cli content-gen ../refs/packs/rj-math-9a/outline.json

# 2. 导入：默认是草稿，只有运营能看到。可以重复导入，按编号和名称更新，ID 不变
uv run python -m app.cli content-import ../refs/packs/rj-math-9a/pack.json

# 3. 抽检后在「平台运营 → 教材内容」发布，或用命令行。整册删除连同文件一起删
uv run python -m app.cli content-publish rj-math-9a
uv run python -m app.cli content-remove rj-math-9a
```

大纲的格式见 `app/modules/curriculum/pack.py` 的 `BookPack`。课本和课件写在内容包的 `files` 里；网页只能显示 PDF，PPT 要先转成 PDF。大纲的章节要照课本目录写，不要凭印象写。

课本是扫描版（没有文字层）时，生成之前先把原文转写出来：

```bash
cd server
# 逐页转写成 Markdown，存成 ocr/p-<PDF 页码>.md。走本机 Codex，已转写的页不会重做
uv run python -m app.cli content-ocr ../refs/materials/pan/数学九上/课本.pdf ../refs/packs/rj-math-9a/ocr --pages 7-182
```

再在大纲旁边放一个 `scan.json`（格式见 `app/devtools/content_gen.py` 的 `ScanIndex`），写明各章各节从书上第几页开始。`content-gen` 看到它就把原文按节分好交给模型；有页还没转写时，这一章不生成并报错。

### 每周周测

每个学生每门课每周一份不同的卷子，上一份的得分决定这一份的难度。规则在 `app/modules/weekly/compose.py`：约 70% 考本周内容、20% 考薄弱知识点、10% 考错题的同类题；得分 85% 及以上升一档，低于 60% 降一档。题目只从审核通过的平台题库里抽。

```bash
cd server
# 1. 按课本原文出题，每节 26 道，再由另一个 Codex 进程不看答案独立解一遍。结果存盘，中途失败重跑只补缺的
uv run python -m app.cli pool-gen ../refs/packs/rj-math-9a

# 2. 导入题库：校验一致的题自动通过，可以进卷；--review 表示全部留给人工审。重复导入时，审核过或改过的题不会被覆盖
uv run python -m app.cli pool-import ../refs/packs/rj-math-9a/questions.json

# 3. 有分歧、没校验、用了课本还没教的内容的题不会自动通过，在「平台运营 → 教材内容 → 题库」逐题看
```

出题和校验用的是同一个模型，两次都算错的题会被当成校验一致，所以题库里可能有少量错题。发现后在题库页驳回，之后就不会再进卷；已经发出去的卷子要单独改分。

交卷后马上能看到分数和对错，答案和解析截止后才公布；单选题的选项按学生打乱，答案跟着换（解析提到选项字母的题除外）。

老师在「周测」页面设置这周教的节，就算给这个班开启了周测。定时任务周四 18:00 提醒没更新进度的老师，周五 16:00 发卷，周日 22:00 截止（`app/workers/celery_app.py` 的 `beat_schedule`）。本地开发没有定时进程，在页面上点「现在发卷」，或者运行 `uv run python -m app.cli weekly-run`。

## 关键约定

- **租户隔离两层保护**：应用层查询必须带 `tenant_id`；数据库层所有带 `tenant_id` 的表开启了行级安全（RLS），应用使用非超级用户账号连接。新建带 `tenant_id` 的表时，在迁移里调用 `migrations/rls.py` 的 `enable_tenant_rls`。
- **调用大模型只走模型网关**：`get_gateway().chat(技能名, messages, ctx=...)`，不要直接用各家 SDK。新技能先在 `models.yaml` 的 `skills` 里登记，prompt 写在 `app/ai/skills/<技能>/`，改 prompt 时递增 `PROMPT_VERSION` 并跑 `evals/` 里的评测。
- **文档格式**：教案等文档存 TipTap JSON。模型输出的 Markdown 由 `content/markdown.py` 转换，Word 由 `content/docx_export.py` 导出；编辑器 `DocEditor.tsx` 新增节点类型时，这三处要一起改。
- **个人信息**：手机号加密存储；发给模型前网关会去掉手机号、身份证号。
- **写操作显式提交**：路由里改完数据调用 `db.commit()`。
- **新路由用 `DbRoute`**：`APIRouter(route_class=DbRoute, ...)`。同步接口执行完马上结束事务、归还数据库连接，否则高并发时连接池和线程池会互相卡死（`core/routing.py` 里有说明）。
- **调用 AI 前先看额度**：老师发起的生成调 `ops.quota.start_teacher_task`，其他用户触发的 AI 功能在接口开头调 `quota.ensure_ai_budget`，让额度用完时马上返回提示，而不是生成到一半失败。

## 部署

`deploy/docker-compose.yml` 可一键起试点环境（数据库、Redis、API、Worker、定时任务 Beat、Web，Beat 全局只能有一个）：复制 `deploy/.env.example` 为 `deploy/.env` 填写后 `docker compose up -d --build`。生产环境数据库和 Redis 用云托管服务，`ENV=prod` 时后端会检查密钥、Redis、短信、CORS 配置。完整步骤（开通学校、备份、监控、合规）见[试点上线清单](docs/试点上线清单.md)。

## 与技术方案的差异

- 平台运营页面暂时放在 `apps/web` 里，按角色隔离；上线前拆到单独部署。
- 前端用 TypeScript 5：生成接口类型的 openapi-typescript 还不支持 TypeScript 7。
- Langfuse 调用追踪还没接入；目前每次模型调用都记在 `ai_usage` 表里。
- 教案生成在 API 进程的后台任务里跑，还没进 Celery：老师关掉页面不影响生成，但服务重启会中断正在生成的教案（显示为失败，可重新生成）。并发量上来后再改。
- 文档没有历史版本表（`document_version`），只用版本号防止多个窗口互相覆盖。
- 资料解析没用 MinerU：有文字层的 PDF、Word、PPT 在本地提取文字，扫描页和图片用通义 `qwen-vl-ocr` 识别，效果够用、不用另开账号。Word 里插入的图片（含 MathType 公式图片）暂不识别；老版本 `.doc`、`.ppt` 不支持，提示老师另存为新格式。
- 上传文件存在本地磁盘（Docker 里挂 `files` 数据卷，API 和 Worker 共用），文件经后端上传，不是前端直传 OSS。规模化时换 OSS，只改 `app/core/storage.py`。
- 检索只用向量（通义 `text-embedding-v4`）加字面重合加分，没用 zhparser 关键词检索和重排模型；向量没建 HNSW 索引（按机构、老师过滤后数据量小，精确计算更准）。换向量模型后要重新解析资料。
- 本地开发没有 Celery Worker，资料解析、出题校验在 API 进程的后台线程里跑（`app/workers/dispatch.py`）；配了 Redis 时进 Celery 队列。
- 背诵卡片单独一个模块 `recite`（方案里归在 `content`），多了卡片组表 `recite_deck`：M2 布置背诵任务时按卡片组布置。抽取卡片几十秒就能完成，在请求里同步执行。
- 题目分两处：老师自己的题在 `question`（带 `tenant_id`，知识点仍是文字标签）；周测用的是平台公共题库 `pool_question`，通过 `pool_question_kp` 关联到知识点。没有合并成一张表，因为前者归老师和机构所有，后者是平台内容，审核流程也不同。
- 掌握度（方案里是 P1 的 `analytics`）先放在 `learning`：不存汇总值，存每题每知识点的得分（`kp_evidence`），读取时按时间衰减算。这样老师改分时直接覆盖，不会重复计入。
- 周测没有单独的作答表：每份周测是一份只发给一个学生的作业（`assignment.kind = weekly`），负责人是设置进度的老师，提交、判分、AI 批改、老师确认、错题本都走作业的流程。周测进行中不能问 AI，而且现有规则是作业没提交、没截止前“问一问”整体关闭，所以学生交卷前都问不了 AI。
- 周测的题不依赖插图：课本里要看图才能做的题，能用文字说清就改写，否则不收。没有存题目配图。
- `curriculum` 模块简化了方案里的表：没有单独的 `subject`、`textbook_edition`，学科和版本是 `textbook` 的字段；章和节都在 `chapter`（`parent_id` 区分）；知识点直接挂在节上，没有 `chapter_kp`。这些表是平台公共内容，不带 `tenant_id`，机构还不能挂自己的补充节点。
- 课程视频不进平台：网盘里的网课单个视频 30～130MB，一章就有约 750MB，要等有对象存储和 CDN 再说。
- 答案校验没用 SymPy：推理模型独立求解后，先按规则比对（选项字母、对错、文字），再用受限的算式求值器做数值比对（`ai/skills/answer_check/compare.py`，能判断 1/2 和 0.5、2(x+1) 和 2x+2 等价，不执行任意代码），判断不了的交给模型比对。
- 2026-11 实测 DeepSeek 的 `deepseek-chat`、`deepseek-reasoner` 都由 `deepseek-flash` 提供，出题用的就是它；校验首选 `deepseek-v4-pro`，和出题模型不同，错误不容易重合（`models.yaml` 的 reasoning 档）。
- 作业的题目、讲义、卡片在布置时存快照（`assignment_item.content`），之后题库、讲义再改，已布置的作业不变。没有单独的 `assignment_target` 表：布置时直接给每个学生建一条 `submission`，班级 ID 记在作业上。
- 填空题判分没用 SymPy：和答案校验共用 `compare.py`（文字规范化后比较，再比数值）。判断不了的（如“互为相反数”和“相反数”）交给 AI 批改、老师确认。
- 作业报告在读取时汇总，没有实时更新的汇总表：一份作业的数据量很小，查询很快。
- 背诵的“今日复习”在读取时计算（到期的卡片 + 每天最多 20 张新卡），没有每天生成清单的定时任务。复习状态按“作业里的背诵项 + 第几张卡”记，错题还没接入 FSRS（错题复习推送是 P1）。
- 内容安全没接阿里云内容安全，用关键词加通义 `qwen-flash` 分类：话题护栏（闲聊、不当内容拉回学习）和危机识别（自伤、轻生、被欺负）。被拦下的记在 `moderation_log`。输出审核目前只在作业提示模式检查有没有泄露答案。
- 危机预警还不通知家长（家长端是 P1）：站内信通知学生所在班级的全部任课老师和机构管理员（系统里没有“班主任”角色），高风险同时发短信。超时没处理的标红，没有自动升级的定时任务。求助电话在 `CRISIS_HOTLINES` 配置。
- 问一问每个学生每天最多 200 条（防刷量）；作业期间老师关掉了“问 AI”时，问一问整体关闭，提交后恢复。
- 运营没有单独的 `quota` 表：名额、到期日、每月 AI 额度直接存在机构（`tenant`）上，套餐（`plan`）只是开通、续费时带出这些值的模板。按技能的限额简化成两条：老师每天发起 AI 生成的次数、学生每天问一问的条数。
- AI 额度按 `ai_usage` 里的估算费用（官网原价、DeepSeek 按高峰价）汇总，不是各平台的实际账单；判断时用 30 秒的缓存，可能超出几十秒内的用量。额度快用完时没有自动提醒，运营在后台看。
- 没有接入真实短信通道（阿里云短信要先审核签名和模板）：试点时 `SMS_PROVIDER=none`，只能密码登录，危机预警只发站内信。
- 运营后台还没拆到单独部署、单独域名；运营账号的登录和其他账号一样。

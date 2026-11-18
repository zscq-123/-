# 本地运行与运维手册

此版本仅面向虚构数据演示。默认规则模式无需模型密钥；后台账户不应暴露到公共网络。原始文件、数据库、密钥、运行报告和截图均不得上传公共仓库。

## 安装与启动

要求 Python 3.12（3.13 可自行验证）、Node.js 22、npm、Git。macOS 示例：

```bash
PYTHON_BIN=python3.12 ./scripts/setup.sh
cp .env.example .env
# 修改 .env 中 DEMO_PASSWORD；示例文件不是生产密钥。
./scripts/dev.sh
```

群众触屏接待入口为 `http://127.0.0.1:3000`，工作人员后台为 `http://127.0.0.1:3000/staff`。API 为 `http://127.0.0.1:8000/api/health`，接口文档为 `http://127.0.0.1:8000/docs`。`.env` 由 shell 加载，只编辑自己可信的配置，包含空格的值需加引号。`Ctrl+C` 会停止脚本启动的两项服务。使用其他端口时可分别手工启动并设置 `BACKEND_URL`。

默认后台用户名为 `staff`、`reviewer`、`admin`、`auditor`，分别对应工作人员、知识审核人、管理员和只读审计员。密码来自 `DEMO_PASSWORD`，缺省仅演示模式使用 `local-demo-change-me`。这些是本地演示账户；正式认证、人员账号生命周期和机构隔离尚需接入。

当前 API 使用进程内互斥保护演示数据库写入，只能以单 worker 运行；不要添加 `--workers` 或横向复制后端容器。正式并发部署需先实现数据库级并发控制和共享限流。

默认数据库相对后端目录保存在 `apps/api/data/legal_aid.db`。更换 `DATABASE_URL` 可指定新数据库。SQLAlchemy 具备 PostgreSQL 驱动配置能力，本次没有执行 PostgreSQL 服务联调或迁移验证。

## 现场终端操作与隐私

将现场触屏浏览器设为全屏，打开群众入口 `/`。法治红首页只提供“开始咨询”和“请工作人员帮助”两条主要入口。自动登记依次完成告知、事项类型、地点、发生时间、希望解决的问题、核对摘要、确认提交；需要时可另外选择语音录入。默认不收集姓名、身份证号、电话号码等身份字段，演示时不要在自由文本中输入真实个人信息。

结束登记会显示咨询编号，请群众前往人工服务台出示。可立即结束并清屏，结果页在 30 秒后自动回到首页。其他页面闲置 3 分钟也会自动清屏。清屏不等于删除已提交的后端记录；已保存的会话、摘要和审核记录仍受服务端数据保留规则约束。现场运维还需关闭浏览器自动填充、共享密码保存和操作系统截图同步，终端只打开群众入口。

工作人员在 `/staff` 登录后查看人工队列和工单、知识名录、审计指标与电话模拟。不要在同一公用终端保持后台登录；结束工作人员操作后退出登录。

### 现场语音检查

在实际触屏设备上，用带麦克风权限的浏览器打开本机地址或 HTTPS 地址。用虚构信息进入「语音或文字说明」，同意浏览器语音服务，点击「开始说话」，看到「正在聆听」后说一句话。点「停止说话」后等待转写，核对文字再点「整理这段说明」。若提示权限、采集、网络或空转写，按页面提示重试，或直接键入说明、继续点选。

语音由浏览器的识别服务处理。项目后端收到的是使用者确认发送的文字。DeepSeek 处理文字需要另外同意。中心实机验收需要测试实际浏览器、话筒和网络条件，至少走通授权、识别、改字、提交与文字回退。

## 外部模型配置

`MODEL_MODE=deterministic` 为默认规则模式。虚构数据联调时，在仓库根目录的私有 `.env` 设置 `MODEL_MODE=external`、`MODEL_EXTERNAL_CONSENT=true`、`MODEL_BASE_URL=https://api.deepseek.com`、`MODEL_NAME=deepseek-flash`，并填写 `MODEL_API_KEY`。重启后端应用配置。实际处理中心咨询前，由机构确认第三方处理授权和数据范围。[DeepSeek Chat Completions 文档](https://api-docs.deepseek.com/api/create-chat-completion/)

现场端打开「语音或文字说明」，使用者勾选允许发送给 DeepSeek，并点击「整理这段说明」。规则缺少必要字段时才调用模型。模型只补充尚未确定的字段，群众核对后再提交。语音服务授权与 DeepSeek 授权独立。DeepSeek 调用失败或返回格式有误时，当前咨询进入待人工处理队列。

`MODEL_INPUT_PRICE` 与 `MODEL_OUTPUT_PRICE` 为每百万 tokens 的估算单价，DeepSeek 示例按美元峰时未命中缓存的费率配置。`MAX_SESSION_COST` 控制单会话估算费用，账单以供应商为准。DeepSeek 的 HTTPS 请求直连官方域名，禁用思考模式并要求 JSON 输出，单次咨询可在必要时重试一次请求。[DeepSeek 模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)

## 检查和回归

```bash
./scripts/check.sh
# 单独运行备份测试
apps/api/.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

HTTP 测试必须使用新建的虚构数据数据库，它会创建大量会话与工单，不针对真实环境运行。关闭当前后端，按以下方式在独立终端启动临时评测服务：

```bash
cd apps/api
DATABASE_URL=sqlite:////tmp/legal-aid-evaluation.db RATE_LIMIT_PER_MINUTE=10000 MODEL_MODE=deterministic .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

在仓库根目录执行：

```bash
apps/api/.venv/bin/python scripts/api_smoke.py --wait
apps/api/.venv/bin/python scripts/api_boundaries.py
apps/api/.venv/bin/python scripts/evaluate.py --output artifacts/local/evaluation.json
```

若设置了 `DEMO_PASSWORD`，测试进程需使用相同环境变量。高限流阈值仅用于本地评测，不应复制到公开服务。评测输出包含提交编号、工作树是否有未提交变更、样本哈希、逐例结果和失败原因；`working_tree_has_changes=true` 时不能把报告当作纯提交版本的验收。

## 容器演示

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 api web
docker compose down
```

Compose 仅绑定环回地址，使用命名卷 `demo-data` 持久化 SQLite。`docker compose down` 保留数据；不要随意添加 `-v`。示例使用非 root 应用用户、Next.js standalone 输出和后端健康检查。当前只验证了 Compose 配置解析，本机 Docker daemon 未启动，镜像构建、容器启动与卷权限未执行实测。

## 备份与恢复

本地 SQLite 使用在线备份 API，包含已提交但尚未 checkpoint 的 WAL 内容。目标文件必须不存在，工具不会覆盖现有数据库；创建后执行 `PRAGMA integrity_check`，以同目录原子链接发布，文件权限继承临时文件的仅当前用户权限。

```bash
apps/api/.venv/bin/python scripts/db_backup.py backup apps/api/data/legal_aid.db artifacts/local/backups/legal-aid-2026-11-18.db
apps/api/.venv/bin/python scripts/db_backup.py restore artifacts/local/backups/legal-aid-2026-11-18.db artifacts/local/restored/legal-aid.db
```

恢复时先停止后端，再恢复到新路径。设置 `DATABASE_URL` 指向恢复结果，启动后检查健康接口、会话数、审计记录与已知工单。确认前保留原库。对正在使用的库路径进行文件替换会破坏 WAL 一致性，不应这样操作。审计随备份恢复到备份时点；若要保留备份后审计，必须先保全原库并设计审计合并流程，不应声称本工具保证无损时间点恢复。

容器卷备份示例：

```bash
docker compose cp scripts/db_backup.py api:/tmp/db_backup.py
docker compose exec api python /tmp/db_backup.py backup /app/data/legal_aid.db /app/data/manual-snapshot-new.db
mkdir -p artifacts/local/backups
# 本地目标同样应采用新的文件名。
docker compose cp api:/app/data/manual-snapshot-new.db artifacts/local/backups/manual-snapshot-new.db
```

容器示例操作未实测；使用新的文件名并先检查目标是否存在。生产需要自动备份计划、加密异地存储、访问审计和定期恢复演练，本原型未提供云端备份服务。

## 故障处理与回滚

- 后端无法启动：确认 Python 版本、依赖安装、8000 端口和数据库目录权限，检查终端报错；不要删除数据库排错。
- 前端 API 报错：检查后端健康接口和 `BACKEND_URL`，重新登录过期后台令牌；浏览器群众会话令牌丢失后由人工处理。
- 无来源、字段矛盾、材料异常、费用阈值或模型超时：保留已采集内容，进入人工队列，工作人员核对原始输入后继续登记。
- 语音不可用：停止语音并改用文字；电话模拟器仅测试状态事件，不能拨打或转接真实电话。
- 新版本故障：先备份数据库，使用另一个干净目录检出已验证的提交、重新安装锁定依赖。确认数据库兼容性后切换服务，不以 `git reset --hard` 或数据库回退覆盖未提交修改和审计记录。

正式试点仍需机构知识与名录授权、TLS、独立认证、密钥服务、监控告警、数据保留制度、真实线路与人工值班保障。详细差距见 [需求映射](REQUIREMENTS.md) 和 [评测记录](EVALUATION.md)。

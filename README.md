# WhatsAppBotSystem

WhatsApp 群组多账号 AI 机器人系统 MVP 后端。

## 当前 MVP 能力
- 多 bot 配置模型
- 场景调度核心（欢迎新人 / 冷场救场 / 活动预热 / 人工审核）
- 频控与冷却规则
- runtime input → planner state 组装
- 候选消息生成
- Persona / Template Catalog 渲染
- 审核状态机（generated / pending_review / approved / rejected / sent / failed）
- SQLite 持久化（review / execution attempts）
- Sender registry（mock / dry_run / webhook）
- FastAPI 接口
- 内置前端运营控制台（首页 Dashboard）
- 前端可调用的一键 planner 执行入口
- queue / approve / send 三档闭环 workflow
- Planner 审计日志（命中 / 拦截原因）
- runtime file source runner
- runtime webhook ingest + latest scheduler execution
- scheduler run log + multi-group dispatch
- scheduler config center + batch tick
- dashboard group status overview + config editor
- group card action buttons + visual scheduler form

## 本地启动
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn whatsapp_bot_system.api:app --reload --app-dir src
```

启动后直接打开：
- Dashboard：`http://127.0.0.1:8000/`
- OpenAPI：`http://127.0.0.1:8000/docs`

## 使用配置文件启动
当前仓库已支持从配置对象构建 app，推荐把 `config.example.yaml` 复制为你自己的配置文件，再通过小入口脚本或 Python 调用启动：

```bash
cp config.example.yaml config.yaml
python - <<'PY'
from whatsapp_bot_system.app import create_app_from_config_path
import uvicorn
app = create_app_from_config_path('config.yaml')
uvicorn.run(app, host='127.0.0.1', port=8787)
PY
```

## 运行测试
```bash
python -m pytest -q
```

## 核心接口
### Health
- `GET /health`

### Planner
- `POST /v1/planner/dry-run`
- `GET /v1/planner/audits`
- `POST /v1/ops/planner/execute`（支持 `queue` / `approve` / `send` workflow，可生成 candidate、自动审批、自动发送）
- `POST /v1/runner/runtime-file/execute`（从本地 runtime JSON 文件执行一轮 runner workflow）
- `POST /v1/scheduler/execute-latest`（对指定 group 拉取最新 ingest runtime 并执行 workflow）
- `POST /v1/scheduler/execute-multi`（一次调度多个 group）
- `POST /v1/scheduler/tick`（按已启用的 scheduler configs 批量执行）
- `GET /v1/scheduler/runs`
- `POST /v1/scheduler/configs`
- `GET /v1/scheduler/configs`
- `GET /v1/scheduler/configs/latest?group_id=...`

### Runtime Ingest
- `POST /v1/runtime/ingest`
- `GET /v1/runtime/ingest`
- `GET /v1/runtime/ingest/latest?group_id=...`

### Dashboard
- `GET /`
- `GET /v1/dashboard/summary`
- `GET /v1/dashboard/group-status`
- `POST /v1/dashboard/groups/{group_id}/run-latest`
- `POST /v1/dashboard/groups/{group_id}/enable`
- `POST /v1/dashboard/groups/{group_id}/disable`
- `POST /v1/dashboard/groups/run-tick`
- 页面已展示 queue、recent candidates、attempts、planner audits、runtime ingests、scheduler runs、scheduler configs、group status cards

### Templates
- `POST /v1/templates/render`

### Review Flow
- `POST /v1/review/candidates`
- `GET /v1/review/candidates`
- `POST /v1/review/candidates/{candidate_id}/submit`
- `POST /v1/review/candidates/{candidate_id}/approve`
- `POST /v1/review/candidates/{candidate_id}/reject`
- `POST /v1/review/candidates/{candidate_id}/sent`
- `POST /v1/review/candidates/{candidate_id}/failed`

### Execution
- `POST /v1/execution/candidates/{candidate_id}/send`
- `GET /v1/execution/candidates/{candidate_id}/attempts`

## Webhook Sender 说明
当 `execution.default_sender=webhook` 时，系统会把候选消息发送到配置里的 webhook endpoint。

Webhook 请求体示例：
```json
{
  "candidate_id": "cand_xxx",
  "text": "Hi Moms Club friends, I'm Luna.",
  "context": {
    "group_id": "120363001234567890@g.us"
  }
}
```

Webhook 预期响应：
```json
{
  "outbound_message_id": "external-msg-001"
}
```

## 当前推荐下一步
- 接真实 WhatsApp bridge / webhook 事件源
- 增加 planner hit/miss 审计日志
- 增加后台配置与操作页面
- 接真实 sender（WebhookSender -> WhatsAppBridgeSender）

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

## 本地启动
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn whatsapp_bot_system.api:app --reload --app-dir src
```

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

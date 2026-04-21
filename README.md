# WhatsAppBotSystem

WhatsApp 群组多账号 AI 机器人系统的第一版工程骨架。

## 当前已落地
- 多机器人配置模型
- 场景调度核心（欢迎新人 / 冷场救场 / 活动预热 / 人工审核）
- 频控与冷却规则
- FastAPI 健康检查与 dry-run 接口
- 自动化测试

## 本地启动
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn whatsapp_bot_system.api:app --reload --app-dir src
```

## 运行测试
```bash
python -m pytest -q
```

## 关键接口
- `GET /health`
- `POST /v1/planner/dry-run`

## 下一步
- 接真实 WhatsApp bridge / webhook 事件
- 加模板库与 AI 改写层
- 加消息审核状态机
- 加后台配置与日志页面

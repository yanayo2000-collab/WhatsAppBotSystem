from fastapi.testclient import TestClient

from whatsapp_bot_system.api import create_app


def _client(tmp_path):
    return TestClient(
        create_app(
            db_path=tmp_path / 'review.db',
            execution_db_path=tmp_path / 'execution.db',
            planner_audit_db_path=tmp_path / 'planner_audits.db',
            runtime_ingest_db_path=tmp_path / 'runtime_ingest.db',
            scheduler_run_db_path=tmp_path / 'scheduler_runs.db',
            scheduler_config_db_path=tmp_path / 'scheduler_configs.db',
            default_sender='dry_run',
        )
    )


def test_dashboard_html_contains_group_filter_sort_and_editor_load_hooks(tmp_path):
    client = _client(tmp_path)

    response = client.get('/')

    assert response.status_code == 200
    html = response.text
    assert 'id="group-status-filter-enabled"' in html
    assert 'id="group-status-sort"' in html
    assert 'loadGroupConfigIntoForm' in html
    assert 'applyGroupStatusFilters' in html
    assert 'updateExistingSchedulerConfig' in html
    assert '最近采集时间=${item.latest_runtime_ingest_at || \'-\'}' in html
    assert '最近失败原因=${item.latest_failure_reason || \'-\'}' in html
    assert 'formatStatusLabel' in html
    assert 'formatWorkflowLabel' in html
    assert 'id="scheduler-form-group-name"' in html
    assert 'id="scheduler-form-rules-summary"' in html
    assert 'id="scheduler-form-provider"' in html
    assert 'id="scheduler-form-bot-display-name"' in html
    assert 'id="scheduler-form-bot-role"' in html
    assert 'id="scheduler-form-scenario-id"' in html
    assert 'id="scheduler-form-content-mode"' in html
    assert 'id="scheduler-form-active-start"' in html
    assert 'id="scheduler-form-active-end"' in html
    assert 'id="scheduler-form-cooldown-seconds"' in html
    assert 'id="scheduler-form-cooldown-minutes-hint"' in html
    assert 'id="scheduler-form-pending-threshold"' in html
    assert 'id="scheduler-form-pending-threshold-hint"' in html
    assert 'id="scheduler-config-advanced-toggle"' in html
    assert 'id="scheduler-config-advanced-panel"' in html
    assert 'id="scheduler-preview-card"' in html
    assert 'id="scheduler-preview-copy"' in html
    assert 'id="scheduler-toast"' in html
    assert 'toggleSchedulerAdvancedMode' in html
    assert 'syncSchedulerJsonFromStructuredForm' in html
    assert 'updateStructuredSchedulerForm' in html
    assert 'renderSchedulerPreviewCard' in html
    assert 'showSchedulerToast' in html
    assert 'formatRoleLabel' in html
    assert 'formatScenarioLabel' in html
    assert 'formatContentModeLabel' in html


def test_dashboard_html_uses_chinese_labels_for_main_sections(tmp_path):
    client = _client(tmp_path)

    response = client.get('/')

    assert response.status_code == 200
    html = response.text
    assert '<title>WhatsApp 机器人系统后台</title>' in html
    assert '<h1>WhatsApp 机器人系统后台</h1>' in html
    assert '<h2>队列概览</h2>' in html
    assert '<h2>群组状态总览</h2>' in html
    assert '<h2>调度配置编辑</h2>' in html
    assert 'formatSenderLabel' in html
    assert 'formatSourceLabel' in html
    assert '请先查看群公告。' in html
    assert '桥接服务A' in html
    assert '后台调度' in html
    assert '欢迎机器人' in html
    assert '新人欢迎' in html
    assert '模板改写' in html
    assert '活跃时段' in html
    assert '开始时间' in html
    assert '结束时间' in html
    assert '冷却时间（秒）' in html
    assert '约 10.0 分钟' in html
    assert '新成员阈值' in html
    assert '达到该人数时，优先触发欢迎场景' in html
    assert '候选文案预览' in html
    assert '预估文案' in html
    assert '保存成功' in html

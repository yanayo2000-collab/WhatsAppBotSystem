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
    assert 'id="scheduler-form-diff-preview"' in html
    assert 'id="scheduler-change-summary"' in html
    assert 'id="scheduler-repair-receipt"' in html
    assert 'id="scheduler-form-dirty-banner"' in html
    assert 'id="scheduler-form-recommend-cooldown"' in html
    assert 'id="scheduler-form-recommend-threshold"' in html
    assert 'id="scheduler-form-recommend-window"' in html
    assert 'id="scheduler-editor-layout"' in html
    assert 'id="scheduler-editor-main"' in html
    assert 'id="scheduler-editor-side"' in html
    assert 'id="scheduler-form-field-tip"' in html
    assert 'id="scheduler-form-cooldown-action-hint"' in html
    assert 'id="scheduler-form-pending-threshold-action-hint"' in html
    assert 'id="scheduler-config-advanced-toggle"' in html
    assert 'id="scheduler-config-advanced-panel"' in html
    assert 'id="scheduler-summary-chips"' in html
    assert 'id="scheduler-summary-chip-enabled"' in html
    assert 'id="scheduler-summary-chip-sync"' in html
    assert 'id="scheduler-summary-chip-risk"' in html
    assert 'id="scheduler-summary-chip-workflow"' in html
    assert 'id="scheduler-preview-card"' in html
    assert 'id="scheduler-preview-meta"' in html
    assert 'id="scheduler-preview-copy"' in html
    assert 'id="scheduler-preview-persona"' in html
    assert 'id="scheduler-preview-trigger"' in html
    assert 'id="scheduler-preview-risk"' in html
    assert 'id="scheduler-preview-risk-list"' in html
    assert 'id="scheduler-config-status-card"' in html
    assert 'id="scheduler-config-status-enabled"' in html
    assert 'id="scheduler-config-status-workflow"' in html
    assert 'id="scheduler-config-status-sync"' in html
    assert 'id="scheduler-config-status-saved-at"' in html
    assert 'id="scheduler-config-status-group-enabled"' in html
    assert 'id="scheduler-toast"' in html
    assert 'toggleSchedulerAdvancedMode' in html
    assert 'syncSchedulerJsonFromStructuredForm' in html
    assert 'updateStructuredSchedulerForm' in html
    assert 'renderSchedulerPreviewCard' in html
    assert 'renderSchedulerConfigStatusCard' in html
    assert 'renderSchedulerPreviewInsights' in html
    assert 'buildSchedulerRiskTips' in html
    assert 'sortSchedulerRiskTips' in html
    assert 'formatSchedulerRiskLevel' in html
    assert 'renderSchedulerSummaryChips' in html
    assert 'renderSchedulerRiskList' in html
    assert 'formatSchedulerSyncState' in html
    assert 'getScenarioRecommendations' in html
    assert 'renderScenarioRecommendationButtons' in html
    assert 'applyRiskFix' in html
    assert 'captureSchedulerBaseline' in html
    assert 'computeSchedulerDiffItems' in html
    assert 'renderSchedulerDiffPreview' in html
    assert 'recordSchedulerChangeSummary' in html
    assert 'renderSchedulerChangeSummary' in html
    assert 'showSchedulerRepairReceipt' in html
    assert 'buildSchedulerActionHints' in html
    assert 'renderSchedulerFieldHints' in html
    assert 'markSchedulerFormDirty' in html
    assert 'clearSchedulerFormDirty' in html
    assert 'applySchedulerRecommendations' in html
    assert 'applyRecommendedCooldown' in html
    assert 'applyRecommendedThreshold' in html
    assert 'applyRecommendedWindow' in html
    assert 'hideSchedulerToast' in html
    assert 'applySchedulerStatusTone' in html
    assert 'formatSchedulerSavedAtLabel' in html
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
    assert '人设摘要' in html
    assert '场景触发条件' in html
    assert '风险提示' in html
    assert '预估文案' in html
    assert '当前配置状态' in html
    assert '风险等级' in html
    assert '当前建议' in html
    assert '同步状态' in html
    assert '最近保存时间' in html
    assert '当前群是否启用' in html
    assert '当前配置已同步，可直接进入调度。' in html
    assert '配置摘要' in html
    assert '已启用' in html
    assert '直接发送' in html
    assert '中风险' in html
    assert '未保存修改' in html
    assert '已同步未保存' in html
    assert '已保存最新' in html
    assert '一键建议：欢迎阈值 3 人' in html
    assert '一键建议：冷场阈值 0 人' in html
    assert '一键建议：预热时段 18:00-22:00' in html
    assert '点击风险项可直接修复' in html
    assert '保存前差异预览' in html
    assert '最近一次变更摘要' in html
    assert '已应用推荐修复' in html
    assert '群名称：妈妈成长群 → 当前群组' in html
    assert '最近一次操作：已加载默认欢迎配置' in html
    assert '修复回执：已应用推荐修复，可继续保存。' in html
    assert '建议先处理风险项，再进入自动调度。' in html
    assert '字段即时提示' in html
    assert '当前存在未保存修改，建议先保存再离开当前配置。' in html
    assert '一键建议：冷却 300 秒' in html
    assert '一键建议：欢迎阈值 3 人' in html
    assert '一键建议：活跃时段 08:00-22:00' in html
    assert '建议将冷却时间提高到 ≥ 300 秒，降低打扰感。' in html
    assert '欢迎场景建议把阈值控制在 1-10 人，保证首轮欢迎及时触发。' in html
    assert '保存成功：已新建' in html
    assert '更新成功：已同步现有配置' in html
    assert '刚刚保存' in html
    assert '分钟前' in html
    assert '冷却时间低于 3 分钟，可能导致发言过密。' in html
    assert '欢迎场景阈值超过 10 人，可能错过第一轮欢迎。' in html
    assert 'scheduler-risk-badge' in html
    assert 'scheduler-status-tone-warning' in html
    assert 'scheduler-status-tone-success' in html
    assert '保存成功' in html

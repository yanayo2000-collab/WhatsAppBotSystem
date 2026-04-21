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


def test_dashboard_html_contains_visual_scheduler_form_fields(tmp_path):
    client = _client(tmp_path)

    response = client.get('/')

    assert response.status_code == 200
    assert 'id="scheduler-config-group-id"' in response.text
    assert 'id="scheduler-config-enabled"' in response.text
    assert 'id="scheduler-config-workflow"' in response.text
    assert 'id="scheduler-config-reviewer"' in response.text
    assert 'id="scheduler-config-candidate-context"' in response.text
    assert 'id="scheduler-config-bot-config"' in response.text
    assert 'saveVisualSchedulerConfig' in response.text
    assert 'runGroupLatest' in response.text
    assert 'toggleGroupConfig' in response.text

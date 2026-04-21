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
    assert 'latest ingest at=${item.latest_runtime_ingest_at || \'-\'}' in html
    assert 'latest failure=${item.latest_failure_reason || \'-\'}' in html

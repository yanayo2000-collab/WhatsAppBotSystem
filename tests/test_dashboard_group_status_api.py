from fastapi.testclient import TestClient

from whatsapp_bot_system.api import create_app


CONFIG_A = {
    'enabled': True,
    'group_id': 'group-a@g.us',
    'bots': [
        {
            'id': 'bot-a',
            'display_name': 'Luna',
            'role': 'welcomer',
            'active_hours': list(range(8, 22)),
            'cooldown_seconds': 600,
            'content_modes': ['template_rewrite'],
        }
    ],
    'scenarios': [
        {
            'id': 'welcome',
            'trigger': 'new_member',
            'priority': 100,
            'bot_roles': ['welcomer'],
            'content_mode': 'template_rewrite',
        }
    ],
}


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


def test_group_status_summary_endpoint_returns_dashboard_cards(tmp_path):
    client = _client(tmp_path)

    client.post('/v1/runtime/ingest', json={'source': 'webhook', 'group_id': 'group-a@g.us', 'runtime_input': {'group_id': 'group-a@g.us', 'now': '2026-04-21T12:00:00+00:00', 'pending_new_members': 1, 'messages': []}, 'metadata': {'provider': 'bridge-a'}})
    client.post('/v1/scheduler/configs', json={'group_id': 'group-a@g.us', 'enabled': True, 'workflow': 'send', 'reviewer': 'scheduler-a', 'candidate_context': {'group_name': 'Group A', 'pending_new_members': 1}, 'config': CONFIG_A})
    client.post('/v1/scheduler/tick')

    response = client.get('/v1/dashboard/group-status')

    assert response.status_code == 200
    items = response.json()['items']
    assert len(items) == 1
    assert items[0]['group_id'] == 'group-a@g.us'
    assert items[0]['config_enabled'] is True
    assert items[0]['latest_runtime_ingest']['source'] == 'webhook'
    assert items[0]['latest_scheduler_run']['status'] == 'sent'
    assert items[0]['latest_candidate']['status'] == 'sent'


def test_dashboard_html_contains_group_status_and_config_editor_hooks(tmp_path):
    client = _client(tmp_path)

    response = client.get('/')

    assert response.status_code == 200
    assert 'Group Status Overview' in response.text
    assert '/v1/dashboard/group-status' in response.text
    assert 'scheduler-config-editor' in response.text

from fastapi.testclient import TestClient

from whatsapp_bot_system.api import create_app


CONFIG = {
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


def test_group_actions_run_latest_disable_and_enable_config(tmp_path):
    client = _client(tmp_path)

    client.post('/v1/runtime/ingest', json={'source': 'webhook', 'group_id': 'group-a@g.us', 'runtime_input': {'group_id': 'group-a@g.us', 'now': '2026-04-21T12:00:00+00:00', 'pending_new_members': 1, 'messages': []}, 'metadata': {}})
    client.post('/v1/scheduler/configs', json={'group_id': 'group-a@g.us', 'enabled': True, 'workflow': 'send', 'reviewer': 'ops-bot', 'candidate_context': {'group_name': 'Group A', 'pending_new_members': 1}, 'config': CONFIG})

    run_latest = client.post('/v1/dashboard/groups/group-a@g.us/run-latest')
    assert run_latest.status_code == 200
    assert run_latest.json()['scheduler_run']['status'] == 'sent'

    disable = client.post('/v1/dashboard/groups/group-a@g.us/disable')
    assert disable.status_code == 200
    assert disable.json()['enabled'] is False

    latest = client.get('/v1/scheduler/configs/latest', params={'group_id': 'group-a@g.us'})
    assert latest.status_code == 200
    assert latest.json()['enabled'] is False

    enable = client.post('/v1/dashboard/groups/group-a@g.us/enable')
    assert enable.status_code == 200
    assert enable.json()['enabled'] is True


def test_group_action_run_tick_invokes_batch_tick(tmp_path):
    client = _client(tmp_path)

    client.post('/v1/runtime/ingest', json={'source': 'webhook', 'group_id': 'group-a@g.us', 'runtime_input': {'group_id': 'group-a@g.us', 'now': '2026-04-21T12:00:00+00:00', 'pending_new_members': 1, 'messages': []}, 'metadata': {}})
    client.post('/v1/scheduler/configs', json={'group_id': 'group-a@g.us', 'enabled': True, 'workflow': 'queue', 'reviewer': 'ops-bot', 'candidate_context': {'group_name': 'Group A', 'pending_new_members': 1}, 'config': CONFIG})

    response = client.post('/v1/dashboard/groups/run-tick')

    assert response.status_code == 200
    assert len(response.json()['items']) == 1
    assert response.json()['items'][0]['group_id'] == 'group-a@g.us'

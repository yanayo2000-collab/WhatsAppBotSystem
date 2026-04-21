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


def test_scheduler_config_update_endpoint_rewrites_existing_record(tmp_path):
    client = _client(tmp_path)

    created = client.post(
        '/v1/scheduler/configs',
        json={
            'group_id': 'group-a@g.us',
            'enabled': True,
            'workflow': 'queue',
            'reviewer': 'scheduler-a',
            'candidate_context': {'group_name': 'Group A'},
            'config': CONFIG,
        },
    )
    assert created.status_code == 200

    response = client.put(
        '/v1/scheduler/configs/group-a@g.us',
        json={
            'enabled': False,
            'workflow': 'send',
            'reviewer': 'scheduler-b',
            'candidate_context': {'group_name': 'Group A Updated', 'pending_new_members': 2},
            'config': CONFIG,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body['group_id'] == 'group-a@g.us'
    assert body['enabled'] is False
    assert body['workflow'] == 'send'
    assert body['reviewer'] == 'scheduler-b'
    assert body['candidate_context']['pending_new_members'] == 2

    latest = client.get('/v1/scheduler/configs/latest', params={'group_id': 'group-a@g.us'})
    assert latest.status_code == 200
    assert latest.json()['enabled'] is False
    assert latest.json()['workflow'] == 'send'

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


def test_scheduler_config_create_and_list(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        '/v1/scheduler/configs',
        json={
            'group_id': 'group-a@g.us',
            'enabled': True,
            'workflow': 'send',
            'reviewer': 'scheduler-bot',
            'candidate_context': {'group_name': 'Group A', 'pending_new_members': 1},
            'config': {
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
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body['group_id'] == 'group-a@g.us'
    assert body['enabled'] is True
    assert body['workflow'] == 'send'

    listing = client.get('/v1/scheduler/configs')
    assert listing.status_code == 200
    items = listing.json()['items']
    assert len(items) == 1
    assert items[0]['group_id'] == 'group-a@g.us'


def test_scheduler_config_latest_update_replaces_existing_group_config(tmp_path):
    client = _client(tmp_path)

    first = client.post(
        '/v1/scheduler/configs',
        json={
            'group_id': 'group-a@g.us',
            'enabled': True,
            'workflow': 'queue',
            'reviewer': 'scheduler-bot',
            'candidate_context': {'group_name': 'Group A'},
            'config': {'enabled': True, 'group_id': 'group-a@g.us', 'bots': [], 'scenarios': []},
        },
    )
    assert first.status_code == 200

    second = client.post(
        '/v1/scheduler/configs',
        json={
            'group_id': 'group-a@g.us',
            'enabled': False,
            'workflow': 'send',
            'reviewer': 'scheduler-bot-2',
            'candidate_context': {'group_name': 'Group A Updated'},
            'config': {'enabled': True, 'group_id': 'group-a@g.us', 'bots': [], 'scenarios': []},
        },
    )
    assert second.status_code == 200

    latest = client.get('/v1/scheduler/configs/latest', params={'group_id': 'group-a@g.us'})
    assert latest.status_code == 200
    assert latest.json()['enabled'] is False
    assert latest.json()['workflow'] == 'send'
    assert latest.json()['reviewer'] == 'scheduler-bot-2'

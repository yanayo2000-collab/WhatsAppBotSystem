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

CONFIG_B = {
    'enabled': True,
    'group_id': 'group-b@g.us',
    'bots': [
        {
            'id': 'bot-b',
            'display_name': 'Mia',
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


def test_scheduler_tick_runs_all_enabled_group_configs(tmp_path):
    client = _client(tmp_path)

    client.post('/v1/runtime/ingest', json={'source': 'webhook', 'group_id': 'group-a@g.us', 'runtime_input': {'group_id': 'group-a@g.us', 'now': '2026-04-21T12:00:00+00:00', 'pending_new_members': 1, 'messages': []}, 'metadata': {}})
    client.post('/v1/runtime/ingest', json={'source': 'webhook', 'group_id': 'group-b@g.us', 'runtime_input': {'group_id': 'group-b@g.us', 'now': '2026-04-21T12:01:00+00:00', 'pending_new_members': 2, 'messages': []}, 'metadata': {}})

    client.post('/v1/scheduler/configs', json={'group_id': 'group-a@g.us', 'enabled': True, 'workflow': 'send', 'reviewer': 'tick-bot', 'candidate_context': {'group_name': 'Group A', 'pending_new_members': 1}, 'config': CONFIG_A})
    client.post('/v1/scheduler/configs', json={'group_id': 'group-b@g.us', 'enabled': True, 'workflow': 'queue', 'reviewer': 'tick-bot', 'candidate_context': {'group_name': 'Group B', 'pending_new_members': 2}, 'config': CONFIG_B})

    response = client.post('/v1/scheduler/tick')

    assert response.status_code == 200
    body = response.json()
    assert len(body['items']) == 2
    assert body['items'][0]['group_id'] == 'group-a@g.us'
    assert body['items'][0]['scheduler_run']['status'] == 'sent'
    assert body['items'][1]['group_id'] == 'group-b@g.us'
    assert body['items'][1]['scheduler_run']['status'] == 'pending_review'


def test_scheduler_tick_skips_disabled_group_configs(tmp_path):
    client = _client(tmp_path)

    client.post('/v1/runtime/ingest', json={'source': 'webhook', 'group_id': 'group-a@g.us', 'runtime_input': {'group_id': 'group-a@g.us', 'now': '2026-04-21T12:00:00+00:00', 'pending_new_members': 1, 'messages': []}, 'metadata': {}})
    client.post('/v1/scheduler/configs', json={'group_id': 'group-a@g.us', 'enabled': False, 'workflow': 'send', 'reviewer': 'tick-bot', 'candidate_context': {'group_name': 'Group A', 'pending_new_members': 1}, 'config': CONFIG_A})

    response = client.post('/v1/scheduler/tick')

    assert response.status_code == 200
    assert response.json()['items'] == []

from fastapi.testclient import TestClient

from whatsapp_bot_system.api import create_app


CONFIG_A = {
    'enabled': True,
    'group_id': 'group-a@g.us',
    'bots': [{'id': 'bot-a', 'display_name': 'Luna', 'role': 'welcomer', 'active_hours': list(range(8, 22)), 'cooldown_seconds': 600, 'content_modes': ['template_rewrite']}],
    'scenarios': [{'id': 'welcome', 'trigger': 'new_member', 'priority': 100, 'bot_roles': ['welcomer'], 'content_mode': 'template_rewrite'}],
}
CONFIG_B = {
    'enabled': True,
    'group_id': 'group-b@g.us',
    'bots': [{'id': 'bot-b', 'display_name': 'Mia', 'role': 'welcomer', 'active_hours': list(range(8, 22)), 'cooldown_seconds': 600, 'content_modes': ['template_rewrite']}],
    'scenarios': [{'id': 'welcome', 'trigger': 'new_member', 'priority': 100, 'bot_roles': ['welcomer'], 'content_mode': 'template_rewrite'}],
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


def test_dashboard_group_status_can_filter_enabled_groups_only(tmp_path):
    client = _client(tmp_path)
    client.post('/v1/scheduler/configs', json={'group_id': 'group-a@g.us', 'enabled': True, 'workflow': 'send', 'reviewer': 'ops-a', 'candidate_context': {'group_name': 'A'}, 'config': CONFIG_A})
    client.post('/v1/scheduler/configs', json={'group_id': 'group-b@g.us', 'enabled': False, 'workflow': 'queue', 'reviewer': 'ops-b', 'candidate_context': {'group_name': 'B'}, 'config': CONFIG_B})

    response = client.get('/v1/dashboard/group-status', params={'enabled_only': 'true'})

    assert response.status_code == 200
    items = response.json()['items']
    assert [item['group_id'] for item in items] == ['group-a@g.us']


def test_dashboard_group_status_can_sort_by_latest_scheduler_run_desc(tmp_path):
    client = _client(tmp_path)
    client.post('/v1/runtime/ingest', json={'source': 'webhook', 'group_id': 'group-a@g.us', 'runtime_input': {'group_id': 'group-a@g.us', 'now': '2026-04-21T12:00:00+00:00', 'pending_new_members': 1, 'messages': []}, 'metadata': {}})
    client.post('/v1/runtime/ingest', json={'source': 'webhook', 'group_id': 'group-b@g.us', 'runtime_input': {'group_id': 'group-b@g.us', 'now': '2026-04-21T12:01:00+00:00', 'pending_new_members': 1, 'messages': []}, 'metadata': {}})
    client.post('/v1/scheduler/configs', json={'group_id': 'group-a@g.us', 'enabled': True, 'workflow': 'queue', 'reviewer': 'ops-a', 'candidate_context': {'group_name': 'A', 'pending_new_members': 1}, 'config': CONFIG_A})
    client.post('/v1/scheduler/configs', json={'group_id': 'group-b@g.us', 'enabled': True, 'workflow': 'send', 'reviewer': 'ops-b', 'candidate_context': {'group_name': 'B', 'pending_new_members': 1}, 'config': CONFIG_B})
    client.post('/v1/dashboard/groups/group-a@g.us/run-latest')
    client.post('/v1/dashboard/groups/group-b@g.us/run-latest')

    response = client.get('/v1/dashboard/group-status', params={'sort_by': 'latest_scheduler_run_desc'})

    assert response.status_code == 200
    items = response.json()['items']
    assert items[0]['group_id'] == 'group-b@g.us'
    assert items[1]['group_id'] == 'group-a@g.us'


def test_dashboard_group_status_includes_operational_timestamps_and_failure_reason(tmp_path):
    client = _client(tmp_path)
    client.post(
        '/v1/runtime/ingest',
        json={
            'source': 'webhook',
            'group_id': 'group-a@g.us',
            'runtime_input': {
                'group_id': 'group-a@g.us',
                'now': '2026-04-21T12:00:00+00:00',
                'pending_new_members': 0,
                'messages': [],
            },
            'metadata': {'provider': 'bridge-x'},
        },
    )
    client.post(
        '/v1/scheduler/configs',
        json={
            'group_id': 'group-a@g.us',
            'enabled': True,
            'workflow': 'queue',
            'reviewer': 'ops-a',
            'candidate_context': {'group_name': 'A'},
            'config': CONFIG_A,
        },
    )
    run_latest = client.post('/v1/dashboard/groups/group-a@g.us/run-latest')
    assert run_latest.status_code == 200
    assert run_latest.json()['scheduler_run']['status'] == 'no_match'

    response = client.get('/v1/dashboard/group-status')

    assert response.status_code == 200
    item = response.json()['items'][0]
    assert item['group_id'] == 'group-a@g.us'
    assert item['latest_runtime_ingest_at'] == item['latest_runtime_ingest']['created_at']
    assert item['latest_scheduler_run_at'] == item['latest_scheduler_run']['created_at']
    assert item['latest_scheduler_run_status'] == 'no_match'
    assert item['latest_failure_reason'] == 'no_matching_scenario'

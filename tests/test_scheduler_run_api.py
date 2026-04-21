from fastapi.testclient import TestClient

from whatsapp_bot_system.api import create_app


CONFIG_A = {
    'enabled': True,
    'group_id': 'group-a@g.us',
    'bots': [
        {
            'id': 'bot-welcome-a',
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
            'id': 'bot-welcome-b',
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
            default_sender='dry_run',
        )
    )


def test_scheduler_execute_latest_writes_scheduler_run_log(tmp_path):
    client = _client(tmp_path)
    client.post(
        '/v1/runtime/ingest',
        json={
            'source': 'webhook',
            'group_id': 'group-a@g.us',
            'runtime_input': {
                'group_id': 'group-a@g.us',
                'now': '2026-04-21T12:00:00+00:00',
                'pending_new_members': 1,
                'messages': [],
            },
            'metadata': {'provider': 'bridge-a'},
        },
    )

    response = client.post(
        '/v1/scheduler/execute-latest',
        json={
            'config': CONFIG_A,
            'group_id': 'group-a@g.us',
            'candidate_context': {'group_name': 'Group A', 'pending_new_members': 1},
            'workflow': 'send',
            'reviewer': 'scheduler-bot',
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body['scheduler_run']['status'] == 'sent'
    assert body['scheduler_run']['group_id'] == 'group-a@g.us'
    assert body['scheduler_run']['candidate_id'] == body['candidate']['id']

    listing = client.get('/v1/scheduler/runs')
    assert listing.status_code == 200
    items = listing.json()['items']
    assert len(items) == 1
    assert items[0]['status'] == 'sent'
    assert items[0]['planner_audit_id'] == body['planner_audit']['id']


def test_scheduler_execute_multi_runs_multiple_groups_and_logs_each_run(tmp_path):
    client = _client(tmp_path)
    client.post(
        '/v1/runtime/ingest',
        json={
            'source': 'webhook',
            'group_id': 'group-a@g.us',
            'runtime_input': {
                'group_id': 'group-a@g.us',
                'now': '2026-04-21T12:00:00+00:00',
                'pending_new_members': 1,
                'messages': [],
            },
            'metadata': {},
        },
    )
    client.post(
        '/v1/runtime/ingest',
        json={
            'source': 'webhook',
            'group_id': 'group-b@g.us',
            'runtime_input': {
                'group_id': 'group-b@g.us',
                'now': '2026-04-21T12:01:00+00:00',
                'pending_new_members': 2,
                'messages': [],
            },
            'metadata': {},
        },
    )

    response = client.post(
        '/v1/scheduler/execute-multi',
        json={
            'items': [
                {
                    'config': CONFIG_A,
                    'group_id': 'group-a@g.us',
                    'candidate_context': {'group_name': 'Group A', 'pending_new_members': 1},
                    'workflow': 'send',
                    'reviewer': 'scheduler-bot',
                },
                {
                    'config': CONFIG_B,
                    'group_id': 'group-b@g.us',
                    'candidate_context': {'group_name': 'Group B', 'pending_new_members': 2},
                    'workflow': 'queue',
                    'reviewer': 'scheduler-bot',
                },
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body['items']) == 2
    assert body['items'][0]['group_id'] == 'group-a@g.us'
    assert body['items'][0]['matched'] is True
    assert body['items'][0]['scheduler_run']['status'] == 'sent'
    assert body['items'][1]['group_id'] == 'group-b@g.us'
    assert body['items'][1]['scheduler_run']['status'] == 'pending_review'

    runs = client.get('/v1/scheduler/runs')
    assert runs.status_code == 200
    statuses = [item['status'] for item in runs.json()['items']]
    assert statuses == ['sent', 'pending_review']


def test_dashboard_summary_includes_recent_scheduler_runs(tmp_path):
    client = _client(tmp_path)
    client.post(
        '/v1/runtime/ingest',
        json={
            'source': 'webhook',
            'group_id': 'group-a@g.us',
            'runtime_input': {
                'group_id': 'group-a@g.us',
                'now': '2026-04-21T12:00:00+00:00',
                'pending_new_members': 1,
                'messages': [],
            },
            'metadata': {},
        },
    )
    client.post(
        '/v1/scheduler/execute-latest',
        json={
            'config': CONFIG_A,
            'group_id': 'group-a@g.us',
            'candidate_context': {'group_name': 'Group A', 'pending_new_members': 1},
            'workflow': 'send',
            'reviewer': 'scheduler-bot',
        },
    )

    summary = client.get('/v1/dashboard/summary')
    assert summary.status_code == 200
    items = summary.json()['recent_scheduler_runs']
    assert len(items) == 1
    assert items[0]['group_id'] == 'group-a@g.us'
    assert items[0]['status'] == 'sent'

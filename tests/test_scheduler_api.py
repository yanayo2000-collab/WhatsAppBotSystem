from fastapi.testclient import TestClient

from whatsapp_bot_system.api import create_app


BASE_CONFIG = {
    'enabled': True,
    'group_id': '120363001234567890@g.us',
    'bots': [
        {
            'id': 'bot-welcome',
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


def test_scheduler_execute_latest_ingested_runtime_runs_send_workflow(tmp_path):
    app = create_app(
        db_path=tmp_path / 'review.db',
        execution_db_path=tmp_path / 'execution.db',
        planner_audit_db_path=tmp_path / 'planner_audits.db',
        runtime_ingest_db_path=tmp_path / 'runtime_ingest.db',
        default_sender='dry_run',
    )
    client = TestClient(app)

    ingest = client.post(
        '/v1/runtime/ingest',
        json={
            'source': 'webhook',
            'group_id': '120363001234567890@g.us',
            'runtime_input': {
                'group_id': '120363001234567890@g.us',
                'now': '2026-04-21T12:00:00+00:00',
                'pending_new_members': 1,
                'messages': [],
            },
            'metadata': {'provider': 'bridge-a'},
        },
    )
    assert ingest.status_code == 200

    response = client.post(
        '/v1/scheduler/execute-latest',
        json={
            'config': BASE_CONFIG,
            'group_id': '120363001234567890@g.us',
            'candidate_context': {
                'group_name': 'Moms Club',
                'rules_summary': 'Please read the pinned guide.',
                'pending_new_members': 1,
            },
            'workflow': 'send',
            'reviewer': 'scheduler-bot',
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body['matched'] is True
    assert body['candidate']['status'] == 'sent'
    assert body['candidate']['reviewed_by'] == 'scheduler-bot'
    assert body['candidate']['outbound_message_id'].startswith('dryrun-msg-')
    assert body['runtime_source']['type'] == 'ingest'
    assert body['runtime_source']['ingest_id']
    assert body['planner_audit']['matched'] is True


def test_scheduler_execute_latest_returns_404_without_ingested_runtime(tmp_path):
    app = create_app(
        db_path=tmp_path / 'review.db',
        execution_db_path=tmp_path / 'execution.db',
        planner_audit_db_path=tmp_path / 'planner_audits.db',
        runtime_ingest_db_path=tmp_path / 'runtime_ingest.db',
        default_sender='dry_run',
    )
    client = TestClient(app)

    response = client.post(
        '/v1/scheduler/execute-latest',
        json={
            'config': BASE_CONFIG,
            'group_id': '120363001234567890@g.us',
            'candidate_context': {'group_name': 'Moms Club'},
            'workflow': 'queue',
            'reviewer': 'scheduler-bot',
        },
    )

    assert response.status_code == 404
    assert 'No runtime ingest found' in response.json()['detail']

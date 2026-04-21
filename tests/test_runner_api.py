import json

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


def test_runner_runtime_file_execute_runs_send_workflow(tmp_path):
    runtime_path = tmp_path / 'runtime.json'
    runtime_path.write_text(
        json.dumps(
            {
                'group_id': '120363001234567890@g.us',
                'now': '2026-04-21T12:00:00+00:00',
                'pending_new_members': 1,
                'messages': [],
            }
        ),
        encoding='utf-8',
    )

    app = create_app(
        db_path=tmp_path / 'review.db',
        execution_db_path=tmp_path / 'execution.db',
        planner_audit_db_path=tmp_path / 'planner_audits.db',
        default_sender='dry_run',
    )
    client = TestClient(app)

    response = client.post(
        '/v1/runner/runtime-file/execute',
        json={
            'config': BASE_CONFIG,
            'runtime_file_path': str(runtime_path),
            'candidate_context': {
                'group_name': 'Moms Club',
                'rules_summary': 'Please read the pinned guide.',
                'pending_new_members': 1,
            },
            'workflow': 'send',
            'reviewer': 'runner-bot',
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body['matched'] is True
    assert body['candidate']['status'] == 'sent'
    assert body['candidate']['reviewed_by'] == 'runner-bot'
    assert body['candidate']['outbound_message_id'].startswith('dryrun-msg-')
    assert body['runtime_source']['type'] == 'file'
    assert body['runtime_source']['path'] == str(runtime_path)
    assert body['planner_audit']['matched'] is True

    audits = client.get('/v1/planner/audits')
    assert audits.status_code == 200
    assert len(audits.json()['items']) == 1


def test_runner_runtime_file_execute_returns_no_match_when_runtime_does_not_trigger(tmp_path):
    runtime_path = tmp_path / 'runtime.json'
    runtime_path.write_text(
        json.dumps(
            {
                'group_id': '120363001234567890@g.us',
                'now': '2026-04-21T12:00:00+00:00',
                'pending_new_members': 0,
                'messages': [],
            }
        ),
        encoding='utf-8',
    )

    app = create_app(
        db_path=tmp_path / 'review.db',
        execution_db_path=tmp_path / 'execution.db',
        planner_audit_db_path=tmp_path / 'planner_audits.db',
        default_sender='dry_run',
    )
    client = TestClient(app)

    response = client.post(
        '/v1/runner/runtime-file/execute',
        json={
            'config': BASE_CONFIG,
            'runtime_file_path': str(runtime_path),
            'candidate_context': {'group_name': 'Moms Club'},
            'workflow': 'queue',
            'reviewer': 'runner-bot',
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body['matched'] is False
    assert body['candidate'] is None
    assert body['planner_audit']['matched'] is False
    assert body['planner_audit']['decision_reason'] == 'no_matching_scenario'

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
    'frequency': {
        'group_min_interval_seconds': 180,
        'human_grace_period_seconds': 180,
        'max_group_messages_per_hour': 12,
        'max_bot_messages_per_hour': 4,
    },
}


def test_planner_audit_logs_matched_and_blocked_decisions(tmp_path):
    app = create_app(db_path=tmp_path / 'review.db', execution_db_path=tmp_path / 'execution.db', planner_audit_db_path=tmp_path / 'planner_audits.db')
    client = TestClient(app)

    blocked = client.post(
        '/v1/planner/dry-run',
        json={
            'config': BASE_CONFIG,
            'state': {
                'group_id': '120363001234567890@g.us',
                'now': '2026-04-21T12:00:00+00:00',
                'bot_last_message_at': '2026-04-21T11:59:00+00:00',
                'pending_new_members': 2,
                'runtime_events': [],
            },
            'candidate_context': {'group_name': 'Moms Club', 'pending_new_members': 2},
        },
    )
    assert blocked.status_code == 200
    assert blocked.json()['matched'] is False

    matched = client.post(
        '/v1/planner/dry-run',
        json={
            'config': BASE_CONFIG,
            'state': {
                'group_id': '120363001234567890@g.us',
                'now': '2026-04-21T12:00:00+00:00',
                'bot_last_message_at': '2026-04-21T11:40:00+00:00',
                'pending_new_members': 1,
                'runtime_events': [],
            },
            'candidate_context': {'group_name': 'Moms Club', 'pending_new_members': 1},
        },
    )
    assert matched.status_code == 200
    assert matched.json()['matched'] is True

    audits = client.get('/v1/planner/audits')
    assert audits.status_code == 200
    items = audits.json()['items']
    assert len(items) == 2
    assert items[0]['matched'] is False
    assert items[0]['decision_reason'] == 'group_cooldown_active'
    assert items[1]['matched'] is True
    assert items[1]['scenario_id'] == 'welcome'
    assert items[1]['bot_id'] == 'bot-welcome'


def test_dashboard_summary_includes_recent_planner_audits(tmp_path):
    app = create_app(db_path=tmp_path / 'review.db', execution_db_path=tmp_path / 'execution.db', planner_audit_db_path=tmp_path / 'planner_audits.db')
    client = TestClient(app)

    response = client.post(
        '/v1/planner/dry-run',
        json={
            'config': BASE_CONFIG,
            'state': {
                'group_id': '120363001234567890@g.us',
                'now': '2026-04-21T12:00:00+00:00',
                'pending_new_members': 1,
                'runtime_events': [],
            },
            'candidate_context': {'group_name': 'Moms Club', 'pending_new_members': 1},
        },
    )
    assert response.status_code == 200

    summary = client.get('/v1/dashboard/summary')
    assert summary.status_code == 200
    recent_audits = summary.json()['recent_planner_audits']
    assert len(recent_audits) == 1
    assert recent_audits[0]['matched'] is True
    assert recent_audits[0]['decision_reason'] == 'scenario_matched'

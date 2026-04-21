from fastapi.testclient import TestClient

from whatsapp_bot_system.api import create_app


def test_health_endpoint():
    client = TestClient(create_app())
    response = client.get('/health')

    assert response.status_code == 200
    assert response.json()['status'] == 'ok'


def test_planner_dry_run_endpoint():
    app = create_app()
    client = TestClient(app)
    payload = {
        'config': {
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
        },
        'state': {
            'group_id': '120363001234567890@g.us',
            'now': '2026-04-21T12:00:00+00:00',
            'human_last_message_at': '2026-04-21T11:30:00+00:00',
            'bot_last_message_at': '2026-04-21T11:20:00+00:00',
            'pending_new_members': 2,
            'runtime_events': [],
        },
    }

    response = client.post('/v1/planner/dry-run', json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body['matched'] is True
    assert body['plan']['scenario_id'] == 'welcome'
    assert body['plan']['bot_id'] == 'bot-welcome'

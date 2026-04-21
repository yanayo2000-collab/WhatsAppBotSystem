from fastapi.testclient import TestClient

from whatsapp_bot_system.app import create_app_from_settings_dict


def test_app_factory_uses_settings_for_template_render_and_sender(tmp_path):
    app = create_app_from_settings_dict(
        {
            'database': {
                'review_db_path': str(tmp_path / 'review.db'),
                'execution_db_path': str(tmp_path / 'execution.db'),
            },
            'execution': {
                'default_sender': 'dry_run',
            },
            'templates': {
                'personas': {
                    'bot-welcome': {
                        'display_name': 'Luna',
                        'tone': 'warm',
                        'style_hint': 'friendly and encouraging',
                    }
                },
                'scenarios': {
                    'welcome': {
                        'template': 'Hi {{group_name}} friends, I\'m {{bot_name}}. {{rules_summary}}'
                    }
                },
            },
        }
    )
    client = TestClient(app)

    rendered = client.post(
        '/v1/templates/render',
        json={
            'bot_id': 'bot-welcome',
            'scenario_id': 'welcome',
            'context': {
                'group_name': 'Moms Club',
                'rules_summary': 'Please read the pinned guide.',
            },
        },
    )
    assert rendered.status_code == 200
    candidate = client.post(
        '/v1/review/candidates',
        json={
            'bot_id': 'bot-welcome',
            'bot_display_name': rendered.json()['bot_display_name'],
            'scenario_id': rendered.json()['scenario_id'],
            'content_mode': rendered.json()['content_mode'],
            'text': rendered.json()['text'],
            'context': {'group_id': '120363001234567890@g.us'},
        },
    ).json()
    client.post(f"/v1/review/candidates/{candidate['id']}/submit")
    client.post(f"/v1/review/candidates/{candidate['id']}/approve", json={'reviewer': 'ops-user'})
    sent = client.post(f"/v1/execution/candidates/{candidate['id']}/send")

    assert sent.status_code == 200
    assert sent.json()['outbound_message_id'].startswith('dryrun-msg-')

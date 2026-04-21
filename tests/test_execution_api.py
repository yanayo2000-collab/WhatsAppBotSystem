from fastapi.testclient import TestClient

from whatsapp_bot_system.api import create_app


def test_template_render_endpoint_and_send_execution_flow(tmp_path):
    app = create_app(db_path=tmp_path / 'review_flow.db', execution_db_path=tmp_path / 'execution.db', default_sender='mock')
    client = TestClient(app)

    render_response = client.post(
        '/v1/templates/render',
        json={
            'catalog': {
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
            'bot_id': 'bot-welcome',
            'scenario_id': 'welcome',
            'context': {
                'group_name': 'Moms Club',
                'rules_summary': 'Please read the pinned guide.',
            },
        },
    )
    assert render_response.status_code == 200
    rendered = render_response.json()
    assert rendered['bot_display_name'] == 'Luna'

    create_response = client.post(
        '/v1/review/candidates',
        json={
            'bot_id': 'bot-welcome',
            'bot_display_name': rendered['bot_display_name'],
            'scenario_id': rendered['scenario_id'],
            'content_mode': 'template_rewrite',
            'text': rendered['text'],
            'context': {'group_id': '120363001234567890@g.us'},
        },
    )
    candidate_id = create_response.json()['id']
    client.post(f'/v1/review/candidates/{candidate_id}/submit')
    client.post(f'/v1/review/candidates/{candidate_id}/approve', json={'reviewer': 'ops-user'})

    send_response = client.post(f'/v1/execution/candidates/{candidate_id}/send')
    assert send_response.status_code == 200
    sent = send_response.json()
    assert sent['status'] == 'sent'
    assert sent['outbound_message_id'].startswith('mock-msg-')

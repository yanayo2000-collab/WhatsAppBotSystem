from fastapi.testclient import TestClient

from whatsapp_bot_system.api import create_app


def test_execution_attempt_listing_endpoint(tmp_path):
    app = create_app(db_path=tmp_path / 'review_flow.db', execution_db_path=tmp_path / 'execution.db', default_sender='dry_run')
    client = TestClient(app)

    candidate = client.post(
        '/v1/review/candidates',
        json={
            'bot_id': 'bot-welcome',
            'bot_display_name': 'Luna',
            'scenario_id': 'welcome',
            'content_mode': 'template_rewrite',
            'text': 'Welcome to Moms Club!',
            'context': {'group_id': '120363001234567890@g.us'},
        },
    ).json()
    client.post(f"/v1/review/candidates/{candidate['id']}/submit")
    client.post(f"/v1/review/candidates/{candidate['id']}/approve", json={'reviewer': 'ops-user'})
    client.post(f"/v1/execution/candidates/{candidate['id']}/send")

    attempts = client.get(f"/v1/execution/candidates/{candidate['id']}/attempts")

    assert attempts.status_code == 200
    body = attempts.json()
    assert len(body['items']) == 1
    assert body['items'][0]['candidate_id'] == candidate['id']
    assert body['items'][0]['sender_type'] == 'dry_run'

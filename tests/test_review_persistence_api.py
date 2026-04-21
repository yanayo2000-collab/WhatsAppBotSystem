from pathlib import Path

from fastapi.testclient import TestClient

from whatsapp_bot_system.api import create_app


def test_review_candidates_persist_across_app_instances(tmp_path):
    db_path = tmp_path / 'review_flow.db'

    first_app = create_app(db_path=db_path)
    first_client = TestClient(first_app)
    created = first_client.post(
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
    first_client.post(f"/v1/review/candidates/{created['id']}/submit")

    second_app = create_app(db_path=db_path)
    second_client = TestClient(second_app)
    pending = second_client.get('/v1/review/candidates', params={'status': 'pending_review'})

    assert pending.status_code == 200
    assert [item['id'] for item in pending.json()['items']] == [created['id']]

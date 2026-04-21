from fastapi.testclient import TestClient

from whatsapp_bot_system.api import create_app


def test_review_flow_endpoints():
    client = TestClient(create_app())

    create_response = client.post(
        '/v1/review/candidates',
        json={
            'bot_id': 'bot-welcome',
            'bot_display_name': 'Luna',
            'scenario_id': 'welcome',
            'content_mode': 'template_rewrite',
            'text': 'Welcome to Moms Club!',
            'context': {'group_id': '120363001234567890@g.us'},
        },
    )
    assert create_response.status_code == 200
    candidate = create_response.json()
    candidate_id = candidate['id']
    assert candidate['status'] == 'generated'

    submit_response = client.post(f'/v1/review/candidates/{candidate_id}/submit')
    assert submit_response.status_code == 200
    assert submit_response.json()['status'] == 'pending_review'

    approve_response = client.post(
        f'/v1/review/candidates/{candidate_id}/approve',
        json={'reviewer': 'ops-user'},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()['status'] == 'approved'

    sent_response = client.post(
        f'/v1/review/candidates/{candidate_id}/sent',
        json={'outbound_message_id': 'msg-001'},
    )
    assert sent_response.status_code == 200
    assert sent_response.json()['status'] == 'sent'


def test_review_candidate_listing_endpoint_filters_status():
    client = TestClient(create_app())

    first = client.post(
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
    second = client.post(
        '/v1/review/candidates',
        json={
            'bot_id': 'bot-icebreaker',
            'bot_display_name': 'Mia',
            'scenario_id': 'cold_start',
            'content_mode': 'ai_assisted',
            'text': 'What do you think about today\'s side hustle tips?',
            'context': {'group_id': '120363001234567890@g.us'},
        },
    ).json()

    client.post(f"/v1/review/candidates/{first['id']}/submit")
    client.post(f"/v1/review/candidates/{second['id']}/submit")
    client.post(f"/v1/review/candidates/{second['id']}/approve", json={'reviewer': 'ops-user'})

    pending = client.get('/v1/review/candidates', params={'status': 'pending_review'})
    approved = client.get('/v1/review/candidates', params={'status': 'approved'})

    assert pending.status_code == 200
    assert approved.status_code == 200
    assert [item['id'] for item in pending.json()['items']] == [first['id']]
    assert [item['id'] for item in approved.json()['items']] == [second['id']]

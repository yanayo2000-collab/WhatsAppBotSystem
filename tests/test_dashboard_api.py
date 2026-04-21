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


def _create_candidate(client: TestClient, text: str, scenario_id: str = 'welcome') -> dict:
    response = client.post(
        '/v1/review/candidates',
        json={
            'bot_id': 'bot-welcome',
            'bot_display_name': 'Luna',
            'scenario_id': scenario_id,
            'content_mode': 'template_rewrite',
            'text': text,
            'context': {'group_id': '120363001234567890@g.us'},
        },
    )
    assert response.status_code == 200
    return response.json()



def test_dashboard_summary_endpoint_returns_counts_and_recent_activity(tmp_path):
    app = create_app(db_path=tmp_path / 'review.db', execution_db_path=tmp_path / 'execution.db', default_sender='dry_run')
    client = TestClient(app)

    pending = _create_candidate(client, 'Welcome to Moms Club!')
    approved = _create_candidate(client, 'Let us kick off the afternoon topic.', scenario_id='cold_start')

    client.post(f"/v1/review/candidates/{pending['id']}/submit")
    client.post(f"/v1/review/candidates/{approved['id']}/submit")
    client.post(f"/v1/review/candidates/{approved['id']}/approve", json={'reviewer': 'ops-user'})
    client.post(f"/v1/execution/candidates/{approved['id']}/send")

    response = client.get('/v1/dashboard/summary')

    assert response.status_code == 200
    body = response.json()
    assert body['queue']['pending_review'] == 1
    assert body['queue']['sent'] == 1
    assert body['queue']['total'] == 2
    assert body['health']['default_sender'] == 'dry_run'
    assert body['recent_candidates'][0]['id'] == approved['id']
    assert body['recent_attempts'][0]['candidate_id'] == approved['id']



def test_dashboard_html_page_is_served():
    client = TestClient(create_app())

    response = client.get('/')

    assert response.status_code == 200
    assert 'text/html' in response.headers['content-type']
    assert 'WhatsApp Bot System Dashboard' in response.text
    assert '/v1/dashboard/summary' in response.text



def test_ops_planner_execute_creates_review_candidate_from_runtime_input(tmp_path):
    app = create_app(db_path=tmp_path / 'review.db', execution_db_path=tmp_path / 'execution.db')
    client = TestClient(app)

    response = client.post(
        '/v1/ops/planner/execute',
        json={
            'config': BASE_CONFIG,
            'runtime_input': {
                'group_id': '120363001234567890@g.us',
                'now': '2026-04-21T12:00:00+00:00',
                'pending_new_members': 2,
                'messages': [],
            },
            'candidate_context': {
                'group_name': 'Moms Club',
                'rules_summary': 'Please read the pinned guide.',
                'pending_new_members': 2,
            },
            'submit_for_review': True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body['matched'] is True
    assert body['candidate']['status'] == 'pending_review'
    assert body['candidate']['scenario_id'] == 'welcome'
    assert 'Moms Club' in body['candidate']['text']

    listed = client.get('/v1/review/candidates', params={'status': 'pending_review'})
    assert listed.status_code == 200
    assert [item['id'] for item in listed.json()['items']] == [body['candidate']['id']]

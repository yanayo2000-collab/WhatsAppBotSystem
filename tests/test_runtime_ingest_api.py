from fastapi.testclient import TestClient

from whatsapp_bot_system.api import create_app


BASE_RUNTIME = {
    'group_id': '120363001234567890@g.us',
    'now': '2026-04-21T12:00:00+00:00',
    'pending_new_members': 1,
    'messages': [],
}


def test_runtime_webhook_ingest_and_listing(tmp_path):
    app = create_app(
        db_path=tmp_path / 'review.db',
        execution_db_path=tmp_path / 'execution.db',
        planner_audit_db_path=tmp_path / 'planner_audits.db',
        runtime_ingest_db_path=tmp_path / 'runtime_ingest.db',
    )
    client = TestClient(app)

    ingest = client.post(
        '/v1/runtime/ingest',
        json={
            'source': 'webhook',
            'group_id': '120363001234567890@g.us',
            'runtime_input': BASE_RUNTIME,
            'metadata': {'provider': 'bridge-a'},
        },
    )

    assert ingest.status_code == 200
    body = ingest.json()
    assert body['source'] == 'webhook'
    assert body['group_id'] == '120363001234567890@g.us'
    assert body['metadata']['provider'] == 'bridge-a'

    listing = client.get('/v1/runtime/ingest')
    assert listing.status_code == 200
    items = listing.json()['items']
    assert len(items) == 1
    assert items[0]['id'] == body['id']
    assert items[0]['runtime_input']['pending_new_members'] == 1


def test_runtime_ingest_latest_endpoint_returns_latest_by_group(tmp_path):
    app = create_app(
        db_path=tmp_path / 'review.db',
        execution_db_path=tmp_path / 'execution.db',
        planner_audit_db_path=tmp_path / 'planner_audits.db',
        runtime_ingest_db_path=tmp_path / 'runtime_ingest.db',
    )
    client = TestClient(app)

    client.post(
        '/v1/runtime/ingest',
        json={
            'source': 'webhook',
            'group_id': '120363001234567890@g.us',
            'runtime_input': {**BASE_RUNTIME, 'pending_new_members': 0, 'now': '2026-04-21T11:59:00+00:00'},
            'metadata': {},
        },
    )
    client.post(
        '/v1/runtime/ingest',
        json={
            'source': 'webhook',
            'group_id': '120363001234567890@g.us',
            'runtime_input': {**BASE_RUNTIME, 'pending_new_members': 3, 'now': '2026-04-21T12:01:00+00:00'},
            'metadata': {},
        },
    )

    latest = client.get('/v1/runtime/ingest/latest', params={'group_id': '120363001234567890@g.us'})
    assert latest.status_code == 200
    assert latest.json()['runtime_input']['pending_new_members'] == 3

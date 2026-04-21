from pathlib import Path

from whatsapp_bot_system.review_flow import CandidateMessageRecord
from whatsapp_bot_system.review_store_sqlite import SQLiteCandidateMessageStore


def _sample_record():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return CandidateMessageRecord(
        id='cand_test_001',
        bot_id='bot-welcome',
        bot_display_name='Luna',
        scenario_id='welcome',
        content_mode='template_rewrite',
        text='Welcome to Moms Club!',
        context={'group_id': '120363001234567890@g.us'},
        status='generated',
        version=1,
        created_at=now,
        updated_at=now,
    )


def test_sqlite_store_save_and_get(tmp_path):
    db_path = tmp_path / 'review_flow.db'
    store = SQLiteCandidateMessageStore(db_path)
    record = _sample_record()

    store.save(record)
    loaded = store.get(record.id)

    assert loaded.id == record.id
    assert loaded.bot_display_name == 'Luna'
    assert loaded.context['group_id'] == '120363001234567890@g.us'


def test_sqlite_store_updates_existing_record(tmp_path):
    db_path = tmp_path / 'review_flow.db'
    store = SQLiteCandidateMessageStore(db_path)
    record = _sample_record()
    store.save(record)

    updated = CandidateMessageRecord(
        **{**record.__dict__, 'status': 'approved', 'version': 2, 'reviewed_by': 'ops-user'}
    )
    store.save(updated)

    loaded = store.get(record.id)
    assert loaded.status == 'approved'
    assert loaded.version == 2
    assert loaded.reviewed_by == 'ops-user'


def test_sqlite_store_lists_and_filters_by_status(tmp_path):
    db_path = tmp_path / 'review_flow.db'
    store = SQLiteCandidateMessageStore(db_path)
    first = _sample_record()
    second = CandidateMessageRecord(
        **{**first.__dict__, 'id': 'cand_test_002', 'status': 'approved', 'version': 2}
    )
    store.save(first)
    store.save(second)

    all_items = store.list()
    approved = store.list(status='approved')

    assert [item.id for item in all_items] == ['cand_test_001', 'cand_test_002']
    assert [item.id for item in approved] == ['cand_test_002']

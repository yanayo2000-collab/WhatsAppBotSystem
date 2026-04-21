from whatsapp_bot_system.execution_store_sqlite import ExecutionAttemptRecord, SQLiteExecutionAttemptStore


def test_execution_attempt_store_save_and_list(tmp_path):
    store = SQLiteExecutionAttemptStore(tmp_path / 'execution.db')
    record = ExecutionAttemptRecord(
        id='attempt_001',
        candidate_id='cand_001',
        sender_type='mock',
        status='sent',
        outbound_message_id='mock-msg-001',
        error_message=None,
        created_at='2026-04-21T12:00:00+00:00',
    )

    store.save(record)
    items = store.list_for_candidate('cand_001')

    assert len(items) == 1
    assert items[0].id == 'attempt_001'
    assert items[0].status == 'sent'


def test_execution_attempt_store_preserves_order(tmp_path):
    store = SQLiteExecutionAttemptStore(tmp_path / 'execution.db')
    store.save(
        ExecutionAttemptRecord(
            id='attempt_001',
            candidate_id='cand_001',
            sender_type='mock',
            status='failed',
            outbound_message_id=None,
            error_message='bridge timeout',
            created_at='2026-04-21T12:00:00+00:00',
        )
    )
    store.save(
        ExecutionAttemptRecord(
            id='attempt_002',
            candidate_id='cand_001',
            sender_type='mock',
            status='sent',
            outbound_message_id='mock-msg-002',
            error_message=None,
            created_at='2026-04-21T12:01:00+00:00',
        )
    )

    items = store.list_for_candidate('cand_001')
    assert [item.id for item in items] == ['attempt_001', 'attempt_002']

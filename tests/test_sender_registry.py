from whatsapp_bot_system.executor import DryRunSender, MockSender, SendExecutionService, SenderRegistry
from whatsapp_bot_system.review_flow import CandidateMessageStore, ReviewFlowService
from whatsapp_bot_system.execution_store_sqlite import SQLiteExecutionAttemptStore


def _approved_candidate(review_service: ReviewFlowService):
    record = review_service.create_candidate(
        bot_id='bot-welcome',
        bot_display_name='Luna',
        scenario_id='welcome',
        content_mode='template_rewrite',
        text='Welcome to Moms Club!',
        context={'group_id': '120363001234567890@g.us'},
    )
    review_service.submit_for_review(record.id)
    review_service.approve(record.id, reviewer='ops-user')
    return record.id


def test_sender_registry_returns_requested_sender():
    registry = SenderRegistry(default_sender='mock', senders={'mock': MockSender(), 'dry_run': DryRunSender()})
    assert registry.get_sender('mock').sender_type == 'mock'
    assert registry.get_sender('dry_run').sender_type == 'dry_run'


def test_send_execution_records_attempts(tmp_path):
    review_service = ReviewFlowService(CandidateMessageStore())
    attempt_store = SQLiteExecutionAttemptStore(tmp_path / 'execution.db')
    registry = SenderRegistry(default_sender='mock', senders={'mock': MockSender()})
    candidate_id = _approved_candidate(review_service)

    executor = SendExecutionService(review_service, registry, attempt_store)
    sent = executor.send_candidate(candidate_id)
    attempts = attempt_store.list_for_candidate(candidate_id)

    assert sent.status == 'sent'
    assert len(attempts) == 1
    assert attempts[0].status == 'sent'
    assert attempts[0].sender_type == 'mock'


def test_send_execution_can_use_dry_run_sender(tmp_path):
    review_service = ReviewFlowService(CandidateMessageStore())
    attempt_store = SQLiteExecutionAttemptStore(tmp_path / 'execution.db')
    registry = SenderRegistry(default_sender='dry_run', senders={'dry_run': DryRunSender()})
    candidate_id = _approved_candidate(review_service)

    executor = SendExecutionService(review_service, registry, attempt_store)
    sent = executor.send_candidate(candidate_id)

    assert sent.status == 'sent'
    assert sent.outbound_message_id.startswith('dryrun-msg-')

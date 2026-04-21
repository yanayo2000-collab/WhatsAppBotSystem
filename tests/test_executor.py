from whatsapp_bot_system.executor import MockSender, SendExecutionService
from whatsapp_bot_system.review_flow import CandidateMessageStore, ReviewFlowService


def _create_approved_candidate(review_service: ReviewFlowService):
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
    return review_service.get_candidate(record.id)


def test_send_execution_marks_candidate_sent_on_success():
    review_service = ReviewFlowService(CandidateMessageStore())
    candidate = _create_approved_candidate(review_service)
    sender = MockSender()
    executor = SendExecutionService(review_service, sender)

    sent = executor.send_candidate(candidate.id)

    assert sent.status == 'sent'
    assert sent.outbound_message_id.startswith('mock-msg-')
    assert sender.sent_messages[0]['candidate_id'] == candidate.id


def test_send_execution_marks_candidate_failed_on_sender_error():
    review_service = ReviewFlowService(CandidateMessageStore())
    candidate = _create_approved_candidate(review_service)
    sender = MockSender(should_fail=True, fail_reason='bridge timeout')
    executor = SendExecutionService(review_service, sender)

    failed = executor.send_candidate(candidate.id)

    assert failed.status == 'failed'
    assert failed.error_message == 'bridge timeout'

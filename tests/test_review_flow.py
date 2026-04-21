from whatsapp_bot_system.review_flow import (
    CandidateMessageRecord,
    CandidateMessageStore,
    ReviewFlowService,
)


def test_create_candidate_starts_as_generated():
    service = ReviewFlowService(CandidateMessageStore())

    record = service.create_candidate(
        bot_id='bot-welcome',
        bot_display_name='Luna',
        scenario_id='welcome',
        content_mode='template_rewrite',
        text='Welcome to Moms Club!',
        context={'group_id': '120363001234567890@g.us'},
    )

    assert isinstance(record, CandidateMessageRecord)
    assert record.status == 'generated'
    assert record.version == 1


def test_submit_for_review_moves_generated_to_pending_review():
    service = ReviewFlowService(CandidateMessageStore())
    record = service.create_candidate(
        bot_id='bot-welcome',
        bot_display_name='Luna',
        scenario_id='welcome',
        content_mode='template_rewrite',
        text='Welcome to Moms Club!',
        context={'group_id': '120363001234567890@g.us'},
    )

    updated = service.submit_for_review(record.id)

    assert updated.status == 'pending_review'
    assert updated.version == 2


def test_approve_moves_pending_review_to_approved():
    service = ReviewFlowService(CandidateMessageStore())
    record = service.create_candidate(
        bot_id='bot-welcome',
        bot_display_name='Luna',
        scenario_id='welcome',
        content_mode='template_rewrite',
        text='Welcome to Moms Club!',
        context={'group_id': '120363001234567890@g.us'},
    )
    service.submit_for_review(record.id)

    approved = service.approve(record.id, reviewer='ops-user')

    assert approved.status == 'approved'
    assert approved.reviewed_by == 'ops-user'
    assert approved.version == 3


def test_reject_moves_pending_review_to_rejected_with_reason():
    service = ReviewFlowService(CandidateMessageStore())
    record = service.create_candidate(
        bot_id='bot-welcome',
        bot_display_name='Luna',
        scenario_id='welcome',
        content_mode='template_rewrite',
        text='Welcome to Moms Club!',
        context={'group_id': '120363001234567890@g.us'},
    )
    service.submit_for_review(record.id)

    rejected = service.reject(record.id, reviewer='ops-user', reason='too generic')

    assert rejected.status == 'rejected'
    assert rejected.review_reason == 'too generic'
    assert rejected.reviewed_by == 'ops-user'


def test_mark_sent_moves_approved_to_sent():
    service = ReviewFlowService(CandidateMessageStore())
    record = service.create_candidate(
        bot_id='bot-welcome',
        bot_display_name='Luna',
        scenario_id='welcome',
        content_mode='template_rewrite',
        text='Welcome to Moms Club!',
        context={'group_id': '120363001234567890@g.us'},
    )
    service.submit_for_review(record.id)
    service.approve(record.id, reviewer='ops-user')

    sent = service.mark_sent(record.id, outbound_message_id='msg-001')

    assert sent.status == 'sent'
    assert sent.outbound_message_id == 'msg-001'


def test_mark_failed_moves_approved_to_failed():
    service = ReviewFlowService(CandidateMessageStore())
    record = service.create_candidate(
        bot_id='bot-welcome',
        bot_display_name='Luna',
        scenario_id='welcome',
        content_mode='template_rewrite',
        text='Welcome to Moms Club!',
        context={'group_id': '120363001234567890@g.us'},
    )
    service.submit_for_review(record.id)
    service.approve(record.id, reviewer='ops-user')

    failed = service.mark_failed(record.id, error='bridge timeout')

    assert failed.status == 'failed'
    assert failed.error_message == 'bridge timeout'


def test_cannot_approve_without_pending_review():
    service = ReviewFlowService(CandidateMessageStore())
    record = service.create_candidate(
        bot_id='bot-welcome',
        bot_display_name='Luna',
        scenario_id='welcome',
        content_mode='template_rewrite',
        text='Welcome to Moms Club!',
        context={'group_id': '120363001234567890@g.us'},
    )

    try:
        service.approve(record.id, reviewer='ops-user')
        raised = False
    except ValueError as exc:
        raised = True
        assert 'pending_review' in str(exc)

    assert raised is True


def test_list_candidates_can_filter_by_status():
    service = ReviewFlowService(CandidateMessageStore())
    first = service.create_candidate(
        bot_id='bot-welcome',
        bot_display_name='Luna',
        scenario_id='welcome',
        content_mode='template_rewrite',
        text='Welcome to Moms Club!',
        context={'group_id': '120363001234567890@g.us'},
    )
    second = service.create_candidate(
        bot_id='bot-icebreaker',
        bot_display_name='Mia',
        scenario_id='cold_start',
        content_mode='ai_assisted',
        text='What do you think about today\'s side hustle tips?',
        context={'group_id': '120363001234567890@g.us'},
    )
    service.submit_for_review(first.id)
    service.submit_for_review(second.id)
    service.approve(second.id, reviewer='ops-user')

    pending = service.list_candidates(status='pending_review')
    approved = service.list_candidates(status='approved')

    assert [item.id for item in pending] == [first.id]
    assert [item.id for item in approved] == [second.id]

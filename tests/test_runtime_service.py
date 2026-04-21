from datetime import datetime, timedelta, timezone

from whatsapp_bot_system.runtime import build_runtime_state, create_candidate_message


def test_build_runtime_state_maps_raw_event_log_to_domain_state():
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    payload = {
        'group_id': '120363001234567890@g.us',
        'now': now.isoformat(),
        'pending_new_members': 2,
        'upcoming_event_at': (now + timedelta(minutes=20)).isoformat(),
        'messages': [
            {
                'sender_type': 'human',
                'sender_id': 'user-1',
                'sent_at': (now - timedelta(minutes=25)).isoformat(),
                'body': 'hello group',
            },
            {
                'sender_type': 'bot',
                'sender_id': 'bot-icebreaker',
                'sent_at': (now - timedelta(minutes=15)).isoformat(),
                'body': 'welcome back',
            },
            {
                'sender_type': 'bot',
                'sender_id': 'bot-icebreaker',
                'sent_at': (now - timedelta(minutes=5)).isoformat(),
                'body': 'anyone here?',
            },
        ],
        'runtime_events': [{'type': 'manual_review', 'payload': {'reason': 'ops-check'}}],
    }

    state = build_runtime_state(payload)

    assert state.group_id == '120363001234567890@g.us'
    assert state.pending_new_members == 2
    assert state.human_last_message_at == now - timedelta(minutes=25)
    assert state.bot_last_message_at == now - timedelta(minutes=5)
    assert state.bot_last_sent_at['bot-icebreaker'] == now - timedelta(minutes=5)
    assert len(state.recent_group_bot_message_times) == 2
    assert state.runtime_events[0].type == 'manual_review'


def test_create_candidate_message_for_welcome_scenario():
    candidate = create_candidate_message(
        scenario_id='welcome',
        bot_display_name='Luna',
        content_mode='template_rewrite',
        context={
            'pending_new_members': 2,
            'group_name': 'Moms Club',
            'rules_summary': 'Please read the pinned guide.',
        },
    )

    assert candidate.bot_display_name == 'Luna'
    assert candidate.scenario_id == 'welcome'
    assert candidate.content_mode == 'template_rewrite'
    assert 'Moms Club' in candidate.text
    assert 'pinned guide' in candidate.text


def test_create_candidate_message_for_idle_scenario():
    candidate = create_candidate_message(
        scenario_id='cold_start',
        bot_display_name='Mia',
        content_mode='ai_assisted',
        context={
            'topic_hint': 'today\'s side hustle tips',
        },
    )

    assert candidate.scenario_id == 'cold_start'
    assert candidate.content_mode == 'ai_assisted'
    assert 'side hustle' in candidate.text

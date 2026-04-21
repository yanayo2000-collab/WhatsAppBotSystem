from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from whatsapp_bot_system.domain import GroupRuntimeState, RuntimeEvent


@dataclass(frozen=True)
class CandidateMessage:
    scenario_id: str
    bot_display_name: str
    content_mode: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def build_runtime_state(raw: dict[str, Any]) -> GroupRuntimeState:
    now = _parse_datetime(raw['now'])
    messages = [_normalize_message(item) for item in raw.get('messages', []) if isinstance(item, dict)]
    human_messages = [item for item in messages if item['sender_type'] == 'human']
    bot_messages = [item for item in messages if item['sender_type'] == 'bot']

    bot_last_sent_at: dict[str, datetime] = {}
    recent_bot_message_times: dict[str, list[datetime]] = {}
    for item in bot_messages:
        sender_id = item['sender_id']
        sent_at = item['sent_at']
        bot_last_sent_at[sender_id] = max(sent_at, bot_last_sent_at.get(sender_id, sent_at))
        recent_bot_message_times.setdefault(sender_id, []).append(sent_at)

    runtime_events = [
        RuntimeEvent(type=str(item.get('type') or '').strip(), payload=item.get('payload') or {})
        for item in raw.get('runtime_events', [])
        if isinstance(item, dict) and str(item.get('type') or '').strip()
    ]

    return GroupRuntimeState(
        group_id=str(raw.get('group_id') or '').strip(),
        now=now,
        human_last_message_at=max((item['sent_at'] for item in human_messages), default=None),
        bot_last_message_at=max((item['sent_at'] for item in bot_messages), default=None),
        pending_new_members=int(raw.get('pending_new_members', 0)),
        upcoming_event_at=_parse_datetime(raw['upcoming_event_at']) if raw.get('upcoming_event_at') else None,
        bot_last_sent_at=bot_last_sent_at,
        recent_group_bot_message_times=[item['sent_at'] for item in bot_messages],
        recent_bot_message_times=recent_bot_message_times,
        runtime_events=runtime_events,
    )


def create_candidate_message(
    scenario_id: str,
    bot_display_name: str,
    content_mode: str,
    context: dict[str, Any] | None = None,
) -> CandidateMessage:
    payload = context or {}
    text = _render_candidate_text(scenario_id=scenario_id, bot_display_name=bot_display_name, context=payload)
    return CandidateMessage(
        scenario_id=scenario_id,
        bot_display_name=bot_display_name,
        content_mode=content_mode,
        text=text,
    )


def _normalize_message(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        'sender_type': str(raw.get('sender_type') or 'human').strip(),
        'sender_id': str(raw.get('sender_id') or '').strip(),
        'sent_at': _parse_datetime(raw['sent_at']),
        'body': str(raw.get('body') or '').strip(),
    }


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _render_candidate_text(scenario_id: str, bot_display_name: str, context: dict[str, Any]) -> str:
    group_name = context.get('group_name') or 'the group'
    if scenario_id == 'welcome':
        rules_summary = context.get('rules_summary') or 'Please check the pinned rules.'
        pending = int(context.get('pending_new_members', 1))
        return (
            f"Hi and welcome to {group_name}! I'm {bot_display_name}. "
            f"We just had {pending} new member(s) join — {rules_summary}"
        )
    if scenario_id == 'cold_start':
        topic_hint = context.get('topic_hint') or 'today\'s highlights'
        return f"Hey everyone, I'm {bot_display_name} — what do you think about {topic_hint}?"
    if scenario_id == 'event_preheat':
        event_name = context.get('event_name') or 'today\'s event'
        event_time = context.get('event_time') or 'soon'
        return f"Quick heads-up from {bot_display_name}: {event_name} starts {event_time}. Who's joining?"
    if scenario_id == 'manual_review':
        note = context.get('review_note') or 'please review this candidate before sending.'
        return f"[{bot_display_name}] Manual review requested: {note}"
    return f"[{bot_display_name}] Candidate message for scenario {scenario_id}."

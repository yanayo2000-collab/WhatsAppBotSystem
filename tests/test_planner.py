from datetime import datetime, timedelta, timezone

from whatsapp_bot_system.domain import GroupRuntimeState, RuntimeEvent
from whatsapp_bot_system.planner import load_multi_bot_config, plan_group_action


def _sample_config():
    return {
        "enabled": True,
        "group_id": "120363001234567890@g.us",
        "bots": [
            {
                "id": "bot-welcome",
                "display_name": "Luna",
                "role": "welcomer",
                "active_hours": list(range(8, 22)),
                "cooldown_seconds": 600,
                "content_modes": ["template_rewrite", "fixed"],
            },
            {
                "id": "bot-icebreaker",
                "display_name": "Mia",
                "role": "icebreaker",
                "active_hours": list(range(8, 23)),
                "cooldown_seconds": 900,
                "content_modes": ["ai_assisted", "template_rewrite"],
            },
        ],
        "frequency": {
            "group_min_interval_seconds": 180,
            "human_grace_period_seconds": 180,
            "max_group_messages_per_hour": 6,
            "max_bot_messages_per_hour": 3,
        },
        "scenarios": [
            {
                "id": "manual_review",
                "trigger": "manual_review",
                "priority": 120,
                "bot_roles": ["welcomer", "icebreaker"],
                "content_mode": "template_rewrite",
            },
            {
                "id": "welcome",
                "trigger": "new_member",
                "priority": 100,
                "bot_roles": ["welcomer"],
                "content_mode": "template_rewrite",
            },
            {
                "id": "event_preheat",
                "trigger": "event_preheat",
                "priority": 80,
                "preheat_window_minutes": 30,
                "bot_roles": ["icebreaker", "welcomer"],
                "content_mode": "fixed",
            },
            {
                "id": "cold_start",
                "trigger": "idle",
                "priority": 50,
                "idle_seconds": 600,
                "bot_roles": ["icebreaker"],
                "content_mode": "ai_assisted",
            },
        ],
    }


def test_new_member_welcome_has_priority_over_idle():
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    config = load_multi_bot_config(_sample_config())
    state = GroupRuntimeState(
        group_id=config.group_id,
        now=now,
        human_last_message_at=now - timedelta(minutes=20),
        bot_last_message_at=now - timedelta(minutes=20),
        pending_new_members=2,
    )

    plan = plan_group_action(config, state)

    assert plan is not None
    assert plan.scenario_id == "welcome"
    assert plan.bot_id == "bot-welcome"
    assert plan.content_mode == "template_rewrite"


def test_idle_waits_for_human_grace_period():
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    config = load_multi_bot_config(_sample_config())
    state = GroupRuntimeState(
        group_id=config.group_id,
        now=now,
        human_last_message_at=now - timedelta(seconds=120),
        bot_last_message_at=now - timedelta(minutes=20),
    )

    assert plan_group_action(config, state) is None


def test_manual_review_bypasses_idle_and_wins_priority():
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    config = load_multi_bot_config(_sample_config())
    state = GroupRuntimeState(
        group_id=config.group_id,
        now=now,
        human_last_message_at=now - timedelta(seconds=30),
        bot_last_message_at=now - timedelta(minutes=20),
        runtime_events=[RuntimeEvent(type="manual_review")],
    )

    plan = plan_group_action(config, state)

    assert plan is not None
    assert plan.scenario_id == "manual_review"


def test_event_preheat_triggers_inside_window():
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    config = load_multi_bot_config(_sample_config())
    state = GroupRuntimeState(
        group_id=config.group_id,
        now=now,
        human_last_message_at=now - timedelta(minutes=25),
        bot_last_message_at=now - timedelta(minutes=15),
        upcoming_event_at=now + timedelta(minutes=20),
    )

    plan = plan_group_action(config, state)

    assert plan is not None
    assert plan.scenario_id == "event_preheat"
    assert plan.content_mode == "fixed"

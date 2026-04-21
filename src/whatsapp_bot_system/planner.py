from __future__ import annotations

from datetime import timedelta
from typing import Any

from whatsapp_bot_system.domain import (
    BotConfig,
    FrequencyPolicy,
    GroupRuntimeState,
    PlannedGroupAction,
    ScenarioConfig,
    WhatsAppMultiBotConfig,
)


def load_multi_bot_config(raw: dict[str, Any] | None) -> WhatsAppMultiBotConfig:
    data = raw or {}
    frequency_raw = data.get('frequency') or {}
    bots = [_parse_bot(item) for item in data.get('bots', []) if isinstance(item, dict)]
    scenarios = [_parse_scenario(item) for item in data.get('scenarios', []) if isinstance(item, dict)]
    return WhatsAppMultiBotConfig(
        enabled=bool(data.get('enabled', False)),
        group_id=str(data.get('group_id') or '').strip(),
        bots=[bot for bot in bots if bot.id],
        frequency=FrequencyPolicy(
            group_min_interval_seconds=int(frequency_raw.get('group_min_interval_seconds', 180)),
            human_grace_period_seconds=int(frequency_raw.get('human_grace_period_seconds', 180)),
            max_group_messages_per_hour=int(frequency_raw.get('max_group_messages_per_hour', 12)),
            max_bot_messages_per_hour=int(frequency_raw.get('max_bot_messages_per_hour', 4)),
        ),
        scenarios=[scenario for scenario in scenarios if scenario.id and scenario.trigger],
    )


def plan_group_action(config: WhatsAppMultiBotConfig, state: GroupRuntimeState) -> PlannedGroupAction | None:
    if not config.enabled or not config.bots or not config.scenarios:
        return None
    if config.group_id and config.group_id != state.group_id:
        return None

    scenarios = sorted((s for s in config.scenarios if s.enabled), key=lambda s: s.priority, reverse=True)
    for scenario in scenarios:
        if not _scenario_matches(scenario, state, config.frequency):
            continue
        bot = _pick_bot(config, state, scenario)
        if bot is None:
            continue
        return PlannedGroupAction(
            scenario_id=scenario.id,
            bot_id=bot.id,
            content_mode=scenario.content_mode or (bot.content_modes[0] if bot.content_modes else 'template_rewrite'),
            trigger=scenario.trigger,
            reason=_build_reason(scenario.trigger, state),
        )
    return None


def _parse_bot(raw: dict[str, Any]) -> BotConfig:
    bot_id = str(raw.get('id') or '').strip()
    display_name = str(raw.get('display_name') or bot_id).strip() or bot_id
    role = str(raw.get('role') or 'general').strip() or 'general'
    return BotConfig(
        id=bot_id,
        role=role,
        display_name=display_name,
        active_hours=[int(h) for h in raw.get('active_hours') or []],
        cooldown_seconds=int(raw.get('cooldown_seconds', 900)),
        content_modes=[str(mode).strip() for mode in raw.get('content_modes') or ['template_rewrite'] if str(mode).strip()],
    )


def _parse_scenario(raw: dict[str, Any]) -> ScenarioConfig:
    return ScenarioConfig(
        id=str(raw.get('id') or '').strip(),
        trigger=str(raw.get('trigger') or '').strip(),
        priority=int(raw.get('priority', 50)),
        enabled=bool(raw.get('enabled', True)),
        idle_seconds=int(raw.get('idle_seconds', 600)),
        preheat_window_minutes=int(raw.get('preheat_window_minutes', 30)),
        bot_roles=[str(role).strip() for role in raw.get('bot_roles') or [] if str(role).strip()],
        content_mode=str(raw.get('content_mode') or 'template_rewrite').strip() or 'template_rewrite',
    )


def _scenario_matches(scenario: ScenarioConfig, state: GroupRuntimeState, frequency: FrequencyPolicy) -> bool:
    if _group_cooldown_active(state, frequency):
        return False
    now = state.now
    if scenario.trigger == 'manual_review':
        return any(event.type == 'manual_review' for event in state.runtime_events)
    if scenario.trigger == 'new_member':
        return state.pending_new_members > 0
    if scenario.trigger == 'event_preheat':
        if state.upcoming_event_at is None:
            return False
        delta = state.upcoming_event_at - now
        return timedelta(0) <= delta <= timedelta(minutes=scenario.preheat_window_minutes)
    if scenario.trigger == 'idle':
        if state.human_last_message_at is None:
            return True
        silence_seconds = (now - state.human_last_message_at).total_seconds()
        return silence_seconds >= max(scenario.idle_seconds, frequency.human_grace_period_seconds)
    return False


def _pick_bot(config: WhatsAppMultiBotConfig, state: GroupRuntimeState, scenario: ScenarioConfig) -> BotConfig | None:
    candidates = [bot for bot in config.bots if not scenario.bot_roles or bot.role in scenario.bot_roles]
    for bot in sorted(candidates, key=lambda b: b.id):
        if not bot.is_active_at(state.now):
            continue
        if _bot_cooldown_active(bot, state):
            continue
        if _bot_hourly_limit_reached(bot, state, config.frequency):
            continue
        if _group_hourly_limit_reached(state, config.frequency):
            continue
        return bot
    return None


def _group_cooldown_active(state: GroupRuntimeState, frequency: FrequencyPolicy) -> bool:
    if state.bot_last_message_at is None:
        return False
    return (state.now - state.bot_last_message_at).total_seconds() < frequency.group_min_interval_seconds


def _bot_cooldown_active(bot: BotConfig, state: GroupRuntimeState) -> bool:
    last_sent = state.bot_last_sent_at.get(bot.id)
    if last_sent is None:
        return False
    return (state.now - last_sent).total_seconds() < bot.cooldown_seconds


def _group_hourly_limit_reached(state: GroupRuntimeState, frequency: FrequencyPolicy) -> bool:
    one_hour_ago = state.now - timedelta(hours=1)
    timestamps = list(state.recent_group_bot_message_times)
    if not timestamps and state.bot_last_message_at is not None:
        timestamps.append(state.bot_last_message_at)
    return len([ts for ts in timestamps if ts >= one_hour_ago]) >= frequency.max_group_messages_per_hour


def _bot_hourly_limit_reached(bot: BotConfig, state: GroupRuntimeState, frequency: FrequencyPolicy) -> bool:
    one_hour_ago = state.now - timedelta(hours=1)
    timestamps = state.recent_bot_message_times.get(bot.id, [])
    return len([ts for ts in timestamps if ts >= one_hour_ago]) >= frequency.max_bot_messages_per_hour


def _build_reason(trigger: str, state: GroupRuntimeState) -> str:
    if trigger == 'new_member':
        return f'{state.pending_new_members} new member(s) pending welcome'
    if trigger == 'manual_review':
        return 'manual review requested'
    if trigger == 'event_preheat' and state.upcoming_event_at is not None:
        return f'event starts at {state.upcoming_event_at.isoformat()}'
    if trigger == 'idle' and state.human_last_message_at is not None:
        seconds = int((state.now - state.human_last_message_at).total_seconds())
        return f'group idle for {seconds} seconds'
    return trigger

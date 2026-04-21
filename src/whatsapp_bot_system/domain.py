from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class BotConfig:
    id: str
    role: str
    display_name: str
    active_hours: list[int] = field(default_factory=list)
    cooldown_seconds: int = 900
    content_modes: list[str] = field(default_factory=lambda: ['template_rewrite'])

    def is_active_at(self, now: datetime) -> bool:
        return True if not self.active_hours else now.hour in self.active_hours


@dataclass(frozen=True)
class FrequencyPolicy:
    group_min_interval_seconds: int = 180
    human_grace_period_seconds: int = 180
    max_group_messages_per_hour: int = 12
    max_bot_messages_per_hour: int = 4


@dataclass(frozen=True)
class ScenarioConfig:
    id: str
    trigger: str
    priority: int = 50
    enabled: bool = True
    idle_seconds: int = 600
    preheat_window_minutes: int = 30
    bot_roles: list[str] = field(default_factory=list)
    content_mode: str = 'template_rewrite'


@dataclass(frozen=True)
class WhatsAppMultiBotConfig:
    enabled: bool = False
    group_id: str = ''
    bots: list[BotConfig] = field(default_factory=list)
    frequency: FrequencyPolicy = field(default_factory=FrequencyPolicy)
    scenarios: list[ScenarioConfig] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class GroupRuntimeState:
    group_id: str
    now: datetime
    human_last_message_at: datetime | None = None
    bot_last_message_at: datetime | None = None
    pending_new_members: int = 0
    upcoming_event_at: datetime | None = None
    bot_last_sent_at: dict[str, datetime] = field(default_factory=dict)
    recent_group_bot_message_times: list[datetime] = field(default_factory=list)
    recent_bot_message_times: dict[str, list[datetime]] = field(default_factory=dict)
    runtime_events: list[RuntimeEvent] = field(default_factory=list)


@dataclass(frozen=True)
class PlannedGroupAction:
    scenario_id: str
    bot_id: str
    content_mode: str
    trigger: str
    reason: str

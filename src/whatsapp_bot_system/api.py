from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from pydantic import BaseModel, Field

from whatsapp_bot_system.domain import GroupRuntimeState, RuntimeEvent
from whatsapp_bot_system.planner import load_multi_bot_config, plan_group_action


class RuntimeEventPayload(BaseModel):
    type: str
    payload: dict = Field(default_factory=dict)


class GroupRuntimeStatePayload(BaseModel):
    group_id: str
    now: datetime
    human_last_message_at: datetime | None = None
    bot_last_message_at: datetime | None = None
    pending_new_members: int = 0
    upcoming_event_at: datetime | None = None
    bot_last_sent_at: dict[str, datetime] = Field(default_factory=dict)
    recent_group_bot_message_times: list[datetime] = Field(default_factory=list)
    recent_bot_message_times: dict[str, list[datetime]] = Field(default_factory=dict)
    runtime_events: list[RuntimeEventPayload] = Field(default_factory=list)


class PlannerDryRunRequest(BaseModel):
    config: dict
    state: GroupRuntimeStatePayload


def create_app() -> FastAPI:
    app = FastAPI(title='WhatsApp Bot System', version='0.1.0')

    @app.get('/health')
    def health() -> dict:
        return {'status': 'ok'}

    @app.post('/v1/planner/dry-run')
    def planner_dry_run(request: PlannerDryRunRequest) -> dict:
        config = load_multi_bot_config(request.config)
        state = GroupRuntimeState(
            group_id=request.state.group_id,
            now=request.state.now,
            human_last_message_at=request.state.human_last_message_at,
            bot_last_message_at=request.state.bot_last_message_at,
            pending_new_members=request.state.pending_new_members,
            upcoming_event_at=request.state.upcoming_event_at,
            bot_last_sent_at=request.state.bot_last_sent_at,
            recent_group_bot_message_times=request.state.recent_group_bot_message_times,
            recent_bot_message_times=request.state.recent_bot_message_times,
            runtime_events=[RuntimeEvent(type=item.type, payload=item.payload) for item in request.state.runtime_events],
        )
        plan = plan_group_action(config, state)
        return {
            'matched': plan is not None,
            'plan': None if plan is None else {
                'scenario_id': plan.scenario_id,
                'bot_id': plan.bot_id,
                'content_mode': plan.content_mode,
                'trigger': plan.trigger,
                'reason': plan.reason,
            }
        }

    return app


app = create_app()

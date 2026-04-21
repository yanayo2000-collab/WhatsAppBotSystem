from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from whatsapp_bot_system.domain import GroupRuntimeState, RuntimeEvent
from whatsapp_bot_system.planner import load_multi_bot_config, plan_group_action
from whatsapp_bot_system.runtime import build_runtime_state, create_candidate_message


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
    state: GroupRuntimeStatePayload | None = None
    runtime_input: dict[str, Any] | None = None
    candidate_context: dict[str, Any] = Field(default_factory=dict)


def create_app() -> FastAPI:
    app = FastAPI(title='WhatsApp Bot System', version='0.1.0')

    @app.get('/health')
    def health() -> dict:
        return {'status': 'ok'}

    @app.post('/v1/planner/dry-run')
    def planner_dry_run(request: PlannerDryRunRequest) -> dict:
        config = load_multi_bot_config(request.config)
        state = _build_state_from_request(request)
        plan = plan_group_action(config, state)
        if plan is None:
            return {'matched': False, 'plan': None, 'candidate_message': None}

        bot_name = _resolve_bot_name(request.config, plan.bot_id)
        candidate = create_candidate_message(
            scenario_id=plan.scenario_id,
            bot_display_name=bot_name,
            content_mode=plan.content_mode,
            context=request.candidate_context,
        )
        return {
            'matched': True,
            'plan': {
                'scenario_id': plan.scenario_id,
                'bot_id': plan.bot_id,
                'content_mode': plan.content_mode,
                'trigger': plan.trigger,
                'reason': plan.reason,
            },
            'candidate_message': {
                'bot_display_name': candidate.bot_display_name,
                'scenario_id': candidate.scenario_id,
                'content_mode': candidate.content_mode,
                'text': candidate.text,
            },
        }

    return app


app = create_app()


def _build_state_from_request(request: PlannerDryRunRequest) -> GroupRuntimeState:
    if request.runtime_input is not None:
        return build_runtime_state(request.runtime_input)
    assert request.state is not None
    return GroupRuntimeState(
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


def _resolve_bot_name(config: dict[str, Any], bot_id: str) -> str:
    for item in config.get('bots', []):
        if isinstance(item, dict) and item.get('id') == bot_id:
            return str(item.get('display_name') or bot_id)
    return bot_id

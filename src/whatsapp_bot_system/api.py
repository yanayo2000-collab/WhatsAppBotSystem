from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from whatsapp_bot_system.domain import GroupRuntimeState, RuntimeEvent
from whatsapp_bot_system.execution_store_sqlite import SQLiteExecutionAttemptStore
from whatsapp_bot_system.executor import DryRunSender, MockSender, SendExecutionService, SenderRegistry, WebhookSender
from whatsapp_bot_system.planner import load_multi_bot_config, plan_group_action
from whatsapp_bot_system.review_flow import ReviewFlowService
from whatsapp_bot_system.review_store_sqlite import SQLiteCandidateMessageStore
from whatsapp_bot_system.runtime import build_runtime_state, create_candidate_message
from whatsapp_bot_system.templates import TemplateCatalog, render_candidate_from_template


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


class CreateCandidateRequest(BaseModel):
    bot_id: str
    bot_display_name: str
    scenario_id: str
    content_mode: str
    text: str
    context: dict[str, Any] = Field(default_factory=dict)


class ReviewDecisionRequest(BaseModel):
    reviewer: str
    reason: str | None = None


class MarkSentRequest(BaseModel):
    outbound_message_id: str


class MarkFailedRequest(BaseModel):
    error: str


class RenderTemplateRequest(BaseModel):
    catalog: dict | None = None
    bot_id: str
    scenario_id: str
    context: dict[str, Any] = Field(default_factory=dict)


class SendCandidateRequest(BaseModel):
    sender: str | None = None


def create_app(
    db_path: str | Path | None = None,
    execution_db_path: str | Path | None = None,
    default_sender: str = 'mock',
    settings_templates: dict[str, Any] | None = None,
    webhook_endpoint: str = '',
    webhook_timeout_seconds: float = 10.0,
    webhook_secret: str = '',
) -> FastAPI:
    resolved_db_path = ':memory:' if db_path is None else Path(db_path)
    resolved_execution_db_path = ':memory:' if execution_db_path is None else Path(execution_db_path)
    resolved_templates = settings_templates or {'personas': {}, 'scenarios': {}}
    store = SQLiteCandidateMessageStore(resolved_db_path)
    attempt_store = SQLiteExecutionAttemptStore(resolved_execution_db_path)
    review_service = ReviewFlowService(store)
    sender_registry = SenderRegistry(
        default_sender=default_sender,
        senders={
            'mock': MockSender(),
            'dry_run': DryRunSender(),
            **({'webhook': WebhookSender(endpoint=webhook_endpoint, timeout_seconds=webhook_timeout_seconds, secret=webhook_secret)} if webhook_endpoint else {}),
        },
    )
    execution_service = SendExecutionService(review_service, sender_registry, attempt_store)
    app = FastAPI(title='WhatsApp Bot System', version='0.1.0')

    @app.get('/health')
    def health() -> dict:
        return {
            'status': 'ok',
            'review_db_path': str(resolved_db_path),
            'execution_db_path': str(resolved_execution_db_path),
            'default_sender': default_sender,
            'available_senders': sorted(sender_registry.senders.keys()),
        }

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
                'metadata': candidate.metadata,
            },
        }

    @app.post('/v1/templates/render')
    def render_template(request: RenderTemplateRequest) -> dict:
        catalog = TemplateCatalog.from_dict(request.catalog or resolved_templates)
        rendered = render_candidate_from_template(
            catalog=catalog,
            bot_id=request.bot_id,
            scenario_id=request.scenario_id,
            context=request.context,
        )
        return {
            'bot_display_name': rendered.bot_display_name,
            'scenario_id': rendered.scenario_id,
            'content_mode': rendered.content_mode,
            'text': rendered.text,
            'metadata': rendered.metadata,
        }

    @app.post('/v1/review/candidates')
    def create_candidate(request: CreateCandidateRequest) -> dict:
        record = review_service.create_candidate(
            bot_id=request.bot_id,
            bot_display_name=request.bot_display_name,
            scenario_id=request.scenario_id,
            content_mode=request.content_mode,
            text=request.text,
            context=request.context,
        )
        return _serialize_candidate(record)

    @app.get('/v1/review/candidates')
    def list_candidates(status: str | None = None) -> dict:
        try:
            items = review_service.list_candidates(status=status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {'items': [_serialize_candidate(item) for item in items]}

    @app.post('/v1/review/candidates/{candidate_id}/submit')
    def submit_candidate(candidate_id: str) -> dict:
        return _apply_transition(lambda: review_service.submit_for_review(candidate_id))

    @app.post('/v1/review/candidates/{candidate_id}/approve')
    def approve_candidate(candidate_id: str, request: ReviewDecisionRequest) -> dict:
        return _apply_transition(lambda: review_service.approve(candidate_id, reviewer=request.reviewer))

    @app.post('/v1/review/candidates/{candidate_id}/reject')
    def reject_candidate(candidate_id: str, request: ReviewDecisionRequest) -> dict:
        return _apply_transition(
            lambda: review_service.reject(
                candidate_id,
                reviewer=request.reviewer,
                reason=request.reason or 'rejected',
            )
        )

    @app.post('/v1/review/candidates/{candidate_id}/sent')
    def mark_candidate_sent(candidate_id: str, request: MarkSentRequest) -> dict:
        return _apply_transition(lambda: review_service.mark_sent(candidate_id, outbound_message_id=request.outbound_message_id))

    @app.post('/v1/review/candidates/{candidate_id}/failed')
    def mark_candidate_failed(candidate_id: str, request: MarkFailedRequest) -> dict:
        return _apply_transition(lambda: review_service.mark_failed(candidate_id, error=request.error))

    @app.post('/v1/execution/candidates/{candidate_id}/send')
    def send_candidate(candidate_id: str, request: SendCandidateRequest | None = None) -> dict:
        sender_name = None if request is None else request.sender
        return _apply_transition(lambda: execution_service.send_candidate(candidate_id, sender_name=sender_name))

    @app.get('/v1/execution/candidates/{candidate_id}/attempts')
    def list_attempts(candidate_id: str) -> dict:
        items = execution_service.list_attempts(candidate_id)
        return {'items': [_serialize_attempt(item) for item in items]}

    return app


app = create_app(db_path=Path('data/review_flow.db'), execution_db_path=Path('data/execution_attempts.db'))


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


def _apply_transition(fn) -> dict:
    try:
        return _serialize_candidate(fn())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f'Candidate not found: {exc.args[0]}') from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _serialize_candidate(record) -> dict:
    return {
        'id': record.id,
        'bot_id': record.bot_id,
        'bot_display_name': record.bot_display_name,
        'scenario_id': record.scenario_id,
        'content_mode': record.content_mode,
        'text': record.text,
        'context': record.context,
        'status': record.status,
        'version': record.version,
        'created_at': record.created_at.isoformat(),
        'updated_at': record.updated_at.isoformat(),
        'reviewed_by': record.reviewed_by,
        'review_reason': record.review_reason,
        'outbound_message_id': record.outbound_message_id,
        'error_message': record.error_message,
    }


def _serialize_attempt(record) -> dict:
    return {
        'id': record.id,
        'candidate_id': record.candidate_id,
        'sender_type': record.sender_type,
        'status': record.status,
        'outbound_message_id': record.outbound_message_id,
        'error_message': record.error_message,
        'created_at': record.created_at,
    }

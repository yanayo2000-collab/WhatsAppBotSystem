from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from whatsapp_bot_system.domain import GroupRuntimeState, RuntimeEvent
from whatsapp_bot_system.execution_store_sqlite import SQLiteExecutionAttemptStore
from whatsapp_bot_system.executor import DryRunSender, MockSender, SendExecutionService, SenderRegistry, WebhookSender
from whatsapp_bot_system.planner import evaluate_group_action, load_multi_bot_config
from whatsapp_bot_system.planner_audit_store_sqlite import PlannerAuditRecord, SQLitePlannerAuditStore
from whatsapp_bot_system.review_flow import ReviewFlowService
from whatsapp_bot_system.review_store_sqlite import SQLiteCandidateMessageStore
from whatsapp_bot_system.runtime import build_runtime_state, create_candidate_message
from whatsapp_bot_system.runtime_ingest_store_sqlite import RuntimeIngestRecord, SQLiteRuntimeIngestStore
from whatsapp_bot_system.runtime_sources import load_runtime_input_from_file
from whatsapp_bot_system.scheduler_config_store_sqlite import SchedulerConfigRecord, SQLiteSchedulerConfigStore
from whatsapp_bot_system.scheduler_run_store_sqlite import SchedulerRunRecord, SQLiteSchedulerRunStore
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


class PlannerExecuteRequest(PlannerDryRunRequest):
    submit_for_review: bool = True
    workflow: str = 'queue'
    reviewer: str = 'ops-runner'


class RunnerRuntimeFileExecuteRequest(BaseModel):
    config: dict
    runtime_file_path: str
    candidate_context: dict[str, Any] = Field(default_factory=dict)
    workflow: str = 'queue'
    reviewer: str = 'ops-runner'


class RuntimeIngestRequest(BaseModel):
    source: str
    group_id: str
    runtime_input: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class SchedulerExecuteLatestRequest(BaseModel):
    config: dict
    group_id: str
    candidate_context: dict[str, Any] = Field(default_factory=dict)
    workflow: str = 'queue'
    reviewer: str = 'ops-runner'


class SchedulerExecuteMultiRequest(BaseModel):
    items: list[SchedulerExecuteLatestRequest]


class SchedulerConfigRequest(BaseModel):
    group_id: str
    enabled: bool
    workflow: str
    reviewer: str
    candidate_context: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any]


class SchedulerConfigUpdateRequest(BaseModel):
    enabled: bool
    workflow: str
    reviewer: str
    candidate_context: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any]


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
    planner_audit_db_path: str | Path | None = None,
    runtime_ingest_db_path: str | Path | None = None,
    scheduler_run_db_path: str | Path | None = None,
    scheduler_config_db_path: str | Path | None = None,
    default_sender: str = 'mock',
    settings_templates: dict[str, Any] | None = None,
    webhook_endpoint: str = '',
    webhook_timeout_seconds: float = 10.0,
    webhook_secret: str = '',
) -> FastAPI:
    resolved_db_path = ':memory:' if db_path is None else Path(db_path)
    resolved_execution_db_path = ':memory:' if execution_db_path is None else Path(execution_db_path)
    resolved_planner_audit_db_path = ':memory:' if planner_audit_db_path is None else Path(planner_audit_db_path)
    resolved_runtime_ingest_db_path = ':memory:' if runtime_ingest_db_path is None else Path(runtime_ingest_db_path)
    resolved_scheduler_run_db_path = ':memory:' if scheduler_run_db_path is None else Path(scheduler_run_db_path)
    resolved_scheduler_config_db_path = ':memory:' if scheduler_config_db_path is None else Path(scheduler_config_db_path)
    resolved_templates = settings_templates or {'personas': {}, 'scenarios': {}}
    store = SQLiteCandidateMessageStore(resolved_db_path)
    attempt_store = SQLiteExecutionAttemptStore(resolved_execution_db_path)
    planner_audit_store = SQLitePlannerAuditStore(resolved_planner_audit_db_path)
    runtime_ingest_store = SQLiteRuntimeIngestStore(resolved_runtime_ingest_db_path)
    scheduler_run_store = SQLiteSchedulerRunStore(resolved_scheduler_run_db_path)
    scheduler_config_store = SQLiteSchedulerConfigStore(resolved_scheduler_config_db_path)
    review_service = ReviewFlowService(store)
    sender_registry = SenderRegistry(
        default_sender=default_sender,
        senders={
            'mock': MockSender(),
            'dry_run': DryRunSender(),
            **(
                {
                    'webhook': WebhookSender(
                        endpoint=webhook_endpoint,
                        timeout_seconds=webhook_timeout_seconds,
                        secret=webhook_secret,
                    )
                }
                if webhook_endpoint
                else {}
            ),
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
            'planner_audit_db_path': str(resolved_planner_audit_db_path),
            'runtime_ingest_db_path': str(resolved_runtime_ingest_db_path),
            'scheduler_run_db_path': str(resolved_scheduler_run_db_path),
            'scheduler_config_db_path': str(resolved_scheduler_config_db_path),
            'default_sender': default_sender,
            'available_senders': sorted(sender_registry.senders.keys()),
        }

    @app.get('/', response_class=HTMLResponse)
    def dashboard() -> str:
        return _render_dashboard_html()

    @app.get('/v1/dashboard/summary')
    def dashboard_summary() -> dict:
        candidates = review_service.list_candidates()
        counts = {status: 0 for status in ['generated', 'pending_review', 'approved', 'rejected', 'sent', 'failed']}
        attempts = []
        for item in candidates:
            counts[item.status] = counts.get(item.status, 0) + 1
            attempts.extend(execution_service.list_attempts(item.id))
        attempts.sort(key=lambda item: item.created_at, reverse=True)
        recent_candidates = sorted(candidates, key=lambda item: item.updated_at, reverse=True)[:10]
        return {
            'health': health(),
            'queue': {
                **counts,
                'total': len(candidates),
            },
            'recent_candidates': [_serialize_candidate(item) for item in recent_candidates],
            'recent_attempts': [_serialize_attempt(item) for item in attempts[:10]],
            'recent_planner_audits': [_serialize_planner_audit(item) for item in planner_audit_store.list(limit=10)],
            'recent_runtime_ingests': [_serialize_runtime_ingest(item) for item in runtime_ingest_store.list(limit=10)],
            'recent_scheduler_runs': [_serialize_scheduler_run(item) for item in scheduler_run_store.list(limit=10)],
            'recent_scheduler_configs': [_serialize_scheduler_config(item) for item in scheduler_config_store.list()[-10:]],
        }

    @app.get('/v1/dashboard/group-status')
    def dashboard_group_status(enabled_only: bool = False, sort_by: str = 'group_id_asc') -> dict:
        config_map = {item.group_id: item for item in scheduler_config_store.list()}
        ingest_map = {item.group_id: item for item in runtime_ingest_store.list()}
        run_map = {item.group_id: item for item in scheduler_run_store.list()}
        candidate_map = {}
        for item in review_service.list_candidates():
            group_id = str(item.context.get('group_id') or '')
            if group_id and group_id not in candidate_map:
                candidate_map[group_id] = item
        group_ids = sorted(set(config_map) | set(ingest_map) | set(run_map) | set(candidate_map))
        items = [
            {
                'group_id': group_id,
                'config_enabled': config_map[group_id].enabled if group_id in config_map else False,
                'latest_scheduler_config': None if group_id not in config_map else _serialize_scheduler_config(config_map[group_id]),
                'latest_runtime_ingest': None if group_id not in ingest_map else _serialize_runtime_ingest(ingest_map[group_id]),
                'latest_scheduler_run': None if group_id not in run_map else _serialize_scheduler_run(run_map[group_id]),
                'latest_candidate': None if group_id not in candidate_map else _serialize_candidate(candidate_map[group_id]),
            }
            for group_id in group_ids
        ]
        if enabled_only:
            items = [item for item in items if item['config_enabled']]
        if sort_by == 'latest_scheduler_run_desc':
            items.sort(key=lambda item: (item['latest_scheduler_run'] or {}).get('created_at', ''), reverse=True)
        elif sort_by == 'latest_scheduler_run_asc':
            items.sort(key=lambda item: (item['latest_scheduler_run'] or {}).get('created_at', ''))
        else:
            items.sort(key=lambda item: item['group_id'])
        return {'items': items}

    @app.post('/v1/dashboard/groups/{group_id}/run-latest')
    def dashboard_group_run_latest(group_id: str) -> dict:
        config_record = scheduler_config_store.latest(group_id)
        return _execute_scheduler_latest(
            request=SchedulerExecuteLatestRequest(
                config=config_record.config,
                group_id=group_id,
                candidate_context=config_record.candidate_context,
                workflow=config_record.workflow,
                reviewer=config_record.reviewer,
            ),
            runtime_ingest_store=runtime_ingest_store,
            planner_audit_store=planner_audit_store,
            review_service=review_service,
            execution_service=execution_service,
            scheduler_run_store=scheduler_run_store,
        )

    @app.post('/v1/dashboard/groups/{group_id}/disable')
    def dashboard_group_disable(group_id: str) -> dict:
        current = scheduler_config_store.latest(group_id)
        record = SchedulerConfigRecord(
            id=f'scfg_{uuid4().hex[:12]}',
            group_id=group_id,
            enabled=False,
            workflow=current.workflow,
            reviewer=current.reviewer,
            candidate_context=current.candidate_context,
            config=current.config,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        scheduler_config_store.save(record)
        return _serialize_scheduler_config(record)

    @app.post('/v1/dashboard/groups/{group_id}/enable')
    def dashboard_group_enable(group_id: str) -> dict:
        current = scheduler_config_store.latest(group_id)
        record = SchedulerConfigRecord(
            id=f'scfg_{uuid4().hex[:12]}',
            group_id=group_id,
            enabled=True,
            workflow=current.workflow,
            reviewer=current.reviewer,
            candidate_context=current.candidate_context,
            config=current.config,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        scheduler_config_store.save(record)
        return _serialize_scheduler_config(record)

    @app.post('/v1/dashboard/groups/run-tick')
    def dashboard_group_run_tick() -> dict:
        return execute_scheduler_tick()

    @app.post('/v1/scheduler/configs')
    def create_scheduler_config(request: SchedulerConfigRequest) -> dict:
        record = SchedulerConfigRecord(
            id=f'scfg_{uuid4().hex[:12]}',
            group_id=request.group_id,
            enabled=request.enabled,
            workflow=request.workflow,
            reviewer=request.reviewer,
            candidate_context=request.candidate_context,
            config=request.config,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        scheduler_config_store.save(record)
        return _serialize_scheduler_config(record)

    @app.get('/v1/scheduler/configs')
    def list_scheduler_configs() -> dict:
        return {'items': [_serialize_scheduler_config(item) for item in scheduler_config_store.list()]}

    @app.get('/v1/scheduler/configs/latest')
    def latest_scheduler_config(group_id: str) -> dict:
        try:
            record = scheduler_config_store.latest(group_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f'No scheduler config found for group: {group_id}') from exc
        return _serialize_scheduler_config(record)

    @app.put('/v1/scheduler/configs/{group_id}')
    def update_scheduler_config(group_id: str, request: SchedulerConfigUpdateRequest) -> dict:
        record = SchedulerConfigRecord(
            id=f'scfg_{uuid4().hex[:12]}',
            group_id=group_id,
            enabled=request.enabled,
            workflow=request.workflow,
            reviewer=request.reviewer,
            candidate_context=request.candidate_context,
            config=request.config,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        scheduler_config_store.save(record)
        return _serialize_scheduler_config(record)

    @app.get('/v1/scheduler/runs')
    def list_scheduler_runs() -> dict:
        return {'items': [_serialize_scheduler_run(item) for item in scheduler_run_store.list()]}

    @app.post('/v1/runtime/ingest')
    def ingest_runtime(request: RuntimeIngestRequest) -> dict:
        record = RuntimeIngestRecord(
            id=f'ingest_{uuid4().hex[:12]}',
            source=request.source,
            group_id=request.group_id,
            runtime_input=request.runtime_input,
            metadata=request.metadata,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        runtime_ingest_store.save(record)
        return _serialize_runtime_ingest(record)

    @app.get('/v1/runtime/ingest')
    def list_runtime_ingests(group_id: str | None = None) -> dict:
        return {'items': [_serialize_runtime_ingest(item) for item in runtime_ingest_store.list(group_id=group_id)]}

    @app.get('/v1/runtime/ingest/latest')
    def latest_runtime_ingest(group_id: str) -> dict:
        try:
            record = runtime_ingest_store.latest(group_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f'No runtime ingest found for group: {group_id}') from exc
        return _serialize_runtime_ingest(record)

    @app.get('/v1/planner/audits')
    def list_planner_audits() -> dict:
        return {'items': [_serialize_planner_audit(item) for item in planner_audit_store.list()]}

    @app.post('/v1/planner/dry-run')
    def planner_dry_run(request: PlannerDryRunRequest) -> dict:
        execution, audit = _plan_candidate_execution(request)
        planner_audit_store.save(audit)
        if execution is None:
            return {'matched': False, 'plan': None, 'candidate_message': None, 'planner_audit': _serialize_planner_audit(audit)}

        plan, candidate = execution
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
            'planner_audit': _serialize_planner_audit(audit),
        }

    @app.post('/v1/ops/planner/execute')
    def execute_planner(request: PlannerExecuteRequest) -> dict:
        execution, audit = _plan_candidate_execution(request)
        planner_audit_store.save(audit)
        if execution is None:
            return {'matched': False, 'plan': None, 'candidate': None, 'planner_audit': _serialize_planner_audit(audit)}

        plan, candidate = execution
        record = review_service.create_candidate(
            bot_id=plan.bot_id,
            bot_display_name=candidate.bot_display_name,
            scenario_id=plan.scenario_id,
            content_mode=plan.content_mode,
            text=candidate.text,
            context=request.candidate_context,
        )
        record = _apply_workflow(record_id=record.id, workflow=request.workflow, reviewer=request.reviewer, submit_for_review=request.submit_for_review, review_service=review_service, execution_service=execution_service)
        return {
            'matched': True,
            'plan': {
                'scenario_id': plan.scenario_id,
                'bot_id': plan.bot_id,
                'content_mode': plan.content_mode,
                'trigger': plan.trigger,
                'reason': plan.reason,
            },
            'candidate': _serialize_candidate(record),
            'planner_audit': _serialize_planner_audit(audit),
        }

    @app.post('/v1/runner/runtime-file/execute')
    def execute_runtime_file_runner(request: RunnerRuntimeFileExecuteRequest) -> dict:
        runtime_input = load_runtime_input_from_file(request.runtime_file_path)
        execution, audit = _plan_candidate_execution(
            PlannerExecuteRequest(
                config=request.config,
                runtime_input=runtime_input,
                candidate_context=request.candidate_context,
                submit_for_review=True,
                workflow=request.workflow,
                reviewer=request.reviewer,
            )
        )
        planner_audit_store.save(audit)
        if execution is None:
            return {
                'matched': False,
                'candidate': None,
                'runtime_source': {'type': 'file', 'path': request.runtime_file_path},
                'planner_audit': _serialize_planner_audit(audit),
            }

        plan, candidate = execution
        record = review_service.create_candidate(
            bot_id=plan.bot_id,
            bot_display_name=candidate.bot_display_name,
            scenario_id=plan.scenario_id,
            content_mode=plan.content_mode,
            text=candidate.text,
            context=request.candidate_context,
        )
        record = _apply_workflow(record_id=record.id, workflow=request.workflow, reviewer=request.reviewer, submit_for_review=True, review_service=review_service, execution_service=execution_service)
        return {
            'matched': True,
            'plan': {
                'scenario_id': plan.scenario_id,
                'bot_id': plan.bot_id,
                'content_mode': plan.content_mode,
                'trigger': plan.trigger,
                'reason': plan.reason,
            },
            'candidate': _serialize_candidate(record),
            'runtime_source': {'type': 'file', 'path': request.runtime_file_path},
            'planner_audit': _serialize_planner_audit(audit),
        }

    @app.post('/v1/scheduler/execute-latest')
    def execute_scheduler_latest(request: SchedulerExecuteLatestRequest) -> dict:
        result = _execute_scheduler_latest(request=request, runtime_ingest_store=runtime_ingest_store, planner_audit_store=planner_audit_store, review_service=review_service, execution_service=execution_service, scheduler_run_store=scheduler_run_store)
        return result

    @app.post('/v1/scheduler/execute-multi')
    def execute_scheduler_multi(request: SchedulerExecuteMultiRequest) -> dict:
        return {
            'items': [
                _execute_scheduler_latest(
                    request=item,
                    runtime_ingest_store=runtime_ingest_store,
                    planner_audit_store=planner_audit_store,
                    review_service=review_service,
                    execution_service=execution_service,
                    scheduler_run_store=scheduler_run_store,
                )
                for item in request.items
            ]
        }

    @app.post('/v1/scheduler/tick')
    def execute_scheduler_tick() -> dict:
        enabled_configs = [item for item in scheduler_config_store.list() if item.enabled]
        items = [
            _execute_scheduler_latest(
                request=SchedulerExecuteLatestRequest(
                    config=item.config,
                    group_id=item.group_id,
                    candidate_context=item.candidate_context,
                    workflow=item.workflow,
                    reviewer=item.reviewer,
                ),
                runtime_ingest_store=runtime_ingest_store,
                planner_audit_store=planner_audit_store,
                review_service=review_service,
                execution_service=execution_service,
                scheduler_run_store=scheduler_run_store,
            )
            for item in enabled_configs
        ]
        return {'items': items}

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


app = create_app(
    db_path=Path('data/review_flow.db'),
    execution_db_path=Path('data/execution_attempts.db'),
    planner_audit_db_path=Path('data/planner_audits.db'),
)


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


def _plan_candidate_execution(request: PlannerDryRunRequest):
    config = load_multi_bot_config(request.config)
    state = _build_state_from_request(request)
    decision = evaluate_group_action(config, state)
    audit = PlannerAuditRecord(
        id=f'audit_{uuid4().hex[:12]}',
        group_id=state.group_id,
        matched=decision.matched,
        scenario_id=None if decision.action is None else decision.action.scenario_id,
        bot_id=None if decision.action is None else decision.action.bot_id,
        trigger=None if decision.action is None else decision.action.trigger,
        decision_reason=decision.decision_reason,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    if decision.action is None:
        return None, audit
    plan = decision.action
    bot_name = _resolve_bot_name(request.config, plan.bot_id)
    candidate = create_candidate_message(
        scenario_id=plan.scenario_id,
        bot_display_name=bot_name,
        content_mode=plan.content_mode,
        context=request.candidate_context,
    )
    return (plan, candidate), audit


def _apply_workflow(*, record_id: str, workflow: str, reviewer: str, submit_for_review: bool, review_service: ReviewFlowService, execution_service: SendExecutionService):
    record = review_service.get_candidate(record_id)
    if submit_for_review and record.status == 'generated':
        record = review_service.submit_for_review(record.id)
    if workflow == 'queue':
        return record
    if workflow == 'approve':
        if record.status == 'generated':
            record = review_service.submit_for_review(record.id)
        return review_service.approve(record.id, reviewer=reviewer)
    if workflow == 'send':
        if record.status == 'generated':
            record = review_service.submit_for_review(record.id)
        if record.status == 'pending_review':
            record = review_service.approve(record.id, reviewer=reviewer)
        return execution_service.send_candidate(record.id)
    raise HTTPException(status_code=400, detail=f'Unsupported workflow: {workflow}')


def _execute_scheduler_latest(*, request: SchedulerExecuteLatestRequest, runtime_ingest_store: SQLiteRuntimeIngestStore, planner_audit_store: SQLitePlannerAuditStore, review_service: ReviewFlowService, execution_service: SendExecutionService, scheduler_run_store: SQLiteSchedulerRunStore) -> dict:
    try:
        ingest = runtime_ingest_store.latest(request.group_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f'No runtime ingest found for group: {request.group_id}') from exc
    execution, audit = _plan_candidate_execution(
        PlannerExecuteRequest(
            config=request.config,
            runtime_input=ingest.runtime_input,
            candidate_context=request.candidate_context,
            submit_for_review=True,
            workflow=request.workflow,
            reviewer=request.reviewer,
        )
    )
    planner_audit_store.save(audit)
    scheduler_run_id = f'srun_{uuid4().hex[:12]}'
    created_at = datetime.now(timezone.utc).isoformat()
    if execution is None:
        run = scheduler_run_store.save(
            SchedulerRunRecord(
                id=scheduler_run_id,
                group_id=request.group_id,
                status='no_match',
                workflow=request.workflow,
                runtime_ingest_id=ingest.id,
                planner_audit_id=audit.id,
                candidate_id=None,
                created_at=created_at,
            )
        )
        return {
            'group_id': request.group_id,
            'matched': False,
            'candidate': None,
            'runtime_source': {'type': 'ingest', 'ingest_id': ingest.id, 'group_id': ingest.group_id},
            'planner_audit': _serialize_planner_audit(audit),
            'scheduler_run': _serialize_scheduler_run(run),
        }
    plan, candidate = execution
    record = review_service.create_candidate(
        bot_id=plan.bot_id,
        bot_display_name=candidate.bot_display_name,
        scenario_id=plan.scenario_id,
        content_mode=plan.content_mode,
        text=candidate.text,
        context={**request.candidate_context, 'group_id': request.group_id},
    )
    record = _apply_workflow(record_id=record.id, workflow=request.workflow, reviewer=request.reviewer, submit_for_review=True, review_service=review_service, execution_service=execution_service)
    run = scheduler_run_store.save(
        SchedulerRunRecord(
            id=scheduler_run_id,
            group_id=request.group_id,
            status=record.status,
            workflow=request.workflow,
            runtime_ingest_id=ingest.id,
            planner_audit_id=audit.id,
            candidate_id=record.id,
            created_at=created_at,
        )
    )
    return {
        'group_id': request.group_id,
        'matched': True,
        'plan': {
            'scenario_id': plan.scenario_id,
            'bot_id': plan.bot_id,
            'content_mode': plan.content_mode,
            'trigger': plan.trigger,
            'reason': plan.reason,
        },
        'candidate': _serialize_candidate(record),
        'runtime_source': {'type': 'ingest', 'ingest_id': ingest.id, 'group_id': ingest.group_id},
        'planner_audit': _serialize_planner_audit(audit),
        'scheduler_run': _serialize_scheduler_run(run),
    }


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


def _serialize_planner_audit(record) -> dict:
    return {
        'id': record.id,
        'group_id': record.group_id,
        'matched': record.matched,
        'scenario_id': record.scenario_id,
        'bot_id': record.bot_id,
        'trigger': record.trigger,
        'decision_reason': record.decision_reason,
        'created_at': record.created_at,
    }


def _serialize_runtime_ingest(record) -> dict:
    return {
        'id': record.id,
        'source': record.source,
        'group_id': record.group_id,
        'runtime_input': record.runtime_input,
        'metadata': record.metadata,
        'created_at': record.created_at,
    }


def _serialize_scheduler_run(record) -> dict:
    return {
        'id': record.id,
        'group_id': record.group_id,
        'status': record.status,
        'workflow': record.workflow,
        'runtime_ingest_id': record.runtime_ingest_id,
        'planner_audit_id': record.planner_audit_id,
        'candidate_id': record.candidate_id,
        'created_at': record.created_at,
    }


def _serialize_scheduler_config(record) -> dict:
    return {
        'id': record.id,
        'group_id': record.group_id,
        'enabled': record.enabled,
        'workflow': record.workflow,
        'reviewer': record.reviewer,
        'candidate_context': record.candidate_context,
        'config': record.config,
        'created_at': record.created_at,
    }


def _render_dashboard_html() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>WhatsApp Bot System Dashboard</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
    body { margin: 0; background: #f5f7fb; color: #1f2937; }
    .wrap { max-width: 1200px; margin: 0 auto; padding: 24px; }
    .hero, .panel { background: #fff; border-radius: 16px; padding: 20px; box-shadow: 0 8px 30px rgba(15, 23, 42, 0.08); margin-bottom: 16px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
    .stat { background: linear-gradient(180deg, #eff6ff, #f8fafc); border-radius: 12px; padding: 14px; }
    .stat strong { display: block; font-size: 28px; margin-top: 8px; }
    .row { display: grid; grid-template-columns: 1.2fr 1fr; gap: 16px; }
    textarea, input { width: 100%; box-sizing: border-box; border: 1px solid #dbe3f0; border-radius: 10px; padding: 10px 12px; font: inherit; }
    textarea { min-height: 140px; resize: vertical; }
    button { border: 0; border-radius: 10px; padding: 10px 14px; font: inherit; cursor: pointer; background: #2563eb; color: white; }
    button.secondary { background: #e5e7eb; color: #111827; }
    .item { border: 1px solid #e5e7eb; border-radius: 12px; padding: 14px; margin-top: 12px; }
    .muted { color: #6b7280; font-size: 14px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
    .label { display: inline-block; padding: 4px 10px; border-radius: 999px; background: #eef2ff; color: #3730a3; font-size: 12px; }
    @media (max-width: 900px) { .row { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>WhatsApp Bot System Dashboard</h1>
      <p class="muted">MVP operations console for queue review, planner execution, and recent send attempts.</p>
      <div id="health" class="muted">Loading health…</div>
    </section>

    <section class="panel">
      <h2>Queue Snapshot</h2>
      <div id="queue-stats" class="grid"></div>
    </section>

    <section class="panel">
      <h2>Planner Execute</h2>
      <p class="muted">Paste config, runtime input, and candidate context JSON to generate a review candidate via <code>/v1/ops/planner/execute</code>.</p>
      <div class="row">
        <div>
          <label>Planner Config JSON</label>
          <textarea id="planner-config"></textarea>
          <label style="display:block;margin-top:12px;">Runtime Input JSON</label>
          <textarea id="planner-runtime"></textarea>
        </div>
        <div>
          <label>Candidate Context JSON</label>
          <textarea id="planner-context"></textarea>
          <label style="display:block;margin-top:12px;">Workflow</label>
          <select id="planner-workflow" style="width:100%;box-sizing:border-box;border:1px solid #dbe3f0;border-radius:10px;padding:10px 12px;font:inherit;">
            <option value="queue">queue → pending_review</option>
            <option value="approve">queue → approved</option>
            <option value="send">queue → approved → send</option>
          </select>
          <div class="actions">
            <button id="planner-submit">Run Planner Workflow</button>
            <button class="secondary" id="planner-refresh">Refresh Dashboard</button>
          </div>
          <pre id="planner-result" class="item muted">No execution yet.</pre>
        </div>
      </div>
    </section>

    <div class="row">
      <section class="panel">
        <h2>Pending / Recent Candidates</h2>
        <div id="candidates"></div>
      </section>
      <section class="panel">
        <h2>Recent Attempts</h2>
        <div id="attempts"></div>
      </section>
    </div>

    <section class="panel">
      <h2>Recent Planner Audits</h2>
      <div id="planner-audits"></div>
    </section>

    <section class="panel">
      <h2>Group Status Overview</h2>
      <div class="actions">
        <label style="display:flex;align-items:center;gap:8px;">
          <input id="group-status-filter-enabled" type="checkbox" />
          <span class="muted">Enabled only</span>
        </label>
        <select id="group-status-sort" style="width:auto;min-width:220px;box-sizing:border-box;border:1px solid #dbe3f0;border-radius:10px;padding:10px 12px;font:inherit;">
          <option value="group_id_asc">Sort: Group ID</option>
          <option value="latest_scheduler_run_desc">Sort: Latest run newest first</option>
          <option value="latest_scheduler_run_asc">Sort: Latest run oldest first</option>
        </select>
      </div>
      <div id="group-status-cards"></div>
    </section>

    <section class="panel" id="scheduler-config-editor">
      <h2>Scheduler Config Editor</h2>
      <div class="row">
        <div>
          <label>Group ID</label>
          <input id="scheduler-config-group-id" />
          <label style="display:block;margin-top:12px;">Enabled</label>
          <select id="scheduler-config-enabled" style="width:100%;box-sizing:border-box;border:1px solid #dbe3f0;border-radius:10px;padding:10px 12px;font:inherit;">
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
          <label style="display:block;margin-top:12px;">Workflow</label>
          <select id="scheduler-config-workflow" style="width:100%;box-sizing:border-box;border:1px solid #dbe3f0;border-radius:10px;padding:10px 12px;font:inherit;">
            <option value="queue">queue</option>
            <option value="approve">approve</option>
            <option value="send">send</option>
          </select>
          <label style="display:block;margin-top:12px;">Reviewer</label>
          <input id="scheduler-config-reviewer" />
        </div>
        <div>
          <label>Candidate Context JSON</label>
          <textarea id="scheduler-config-candidate-context"></textarea>
          <label style="display:block;margin-top:12px;">Bot Config JSON</label>
          <textarea id="scheduler-config-bot-config"></textarea>
          <div class="actions">
            <button id="scheduler-config-save">Save Scheduler Config</button>
            <button class="secondary" id="scheduler-config-update">Update Existing Config</button>
          </div>
        </div>
      </div>
      <h3>Recent Scheduler Configs</h3>
      <div id="scheduler-configs"></div>
    </section>

    <section class="panel">
      <h2>Runtime Webhook / Scheduler</h2>
      <div class="row">
        <div>
          <label>Runtime Ingest JSON</label>
          <textarea id="runtime-ingest-input"></textarea>
          <div class="actions">
            <button id="runtime-ingest-submit">Ingest Runtime</button>
          </div>
        </div>
        <div>
          <label>Scheduler Group ID</label>
          <input id="scheduler-group-id" />
          <div class="actions">
            <button id="scheduler-run-latest">Run Latest Ingest</button>
            <button class="secondary" id="scheduler-tick-run">Run Batch Tick</button>
          </div>
          <pre id="scheduler-result" class="item muted">No scheduler execution yet.</pre>
          <h3>Recent Runtime Ingests</h3>
          <div id="runtime-ingests"></div>
          <h3 style="margin-top:16px;">Recent Scheduler Runs</h3>
          <div id="scheduler-runs"></div>
        </div>
      </div>
    </section>
  </div>

  <script>
    const defaultConfig = {
      enabled: true,
      group_id: '120363001234567890@g.us',
      bots: [{ id: 'bot-welcome', display_name: 'Luna', role: 'welcomer', active_hours: Array.from({length: 14}, (_, i) => i + 8), cooldown_seconds: 600, content_modes: ['template_rewrite'] }],
      scenarios: [{ id: 'welcome', trigger: 'new_member', priority: 100, bot_roles: ['welcomer'], content_mode: 'template_rewrite' }]
    };
    const defaultRuntime = { group_id: '120363001234567890@g.us', now: '2026-04-21T12:00:00+00:00', pending_new_members: 1, messages: [] };
    const defaultContext = { group_name: 'Moms Club', rules_summary: 'Please read the pinned guide.', pending_new_members: 1 };
    const defaultRuntimeIngest = { source: 'webhook', group_id: '120363001234567890@g.us', runtime_input: defaultRuntime, metadata: { provider: 'bridge-a' } };
    const defaultSchedulerConfig = { group_id: '120363001234567890@g.us', enabled: true, workflow: 'send', reviewer: 'dashboard-scheduler', candidate_context: defaultContext, config: defaultConfig };
    document.getElementById('planner-config').value = JSON.stringify(defaultConfig, null, 2);
    document.getElementById('planner-runtime').value = JSON.stringify(defaultRuntime, null, 2);
    document.getElementById('planner-context').value = JSON.stringify(defaultContext, null, 2);
    document.getElementById('runtime-ingest-input').value = JSON.stringify(defaultRuntimeIngest, null, 2);
    document.getElementById('scheduler-config-group-id').value = defaultSchedulerConfig.group_id;
    document.getElementById('scheduler-config-enabled').value = String(defaultSchedulerConfig.enabled);
    document.getElementById('scheduler-config-workflow').value = defaultSchedulerConfig.workflow;
    document.getElementById('scheduler-config-reviewer').value = defaultSchedulerConfig.reviewer;
    document.getElementById('scheduler-config-candidate-context').value = JSON.stringify(defaultSchedulerConfig.candidate_context, null, 2);
    document.getElementById('scheduler-config-bot-config').value = JSON.stringify(defaultSchedulerConfig.config, null, 2);
    document.getElementById('scheduler-group-id').value = '120363001234567890@g.us';

    async function requestJson(url, options) {
      const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Request failed: ${response.status}`);
      }
      return response.json();
    }

    function renderQueue(queue) {
      const stats = [
        ['Total', queue.total], ['Pending Review', queue.pending_review], ['Approved', queue.approved], ['Sent', queue.sent], ['Failed', queue.failed], ['Rejected', queue.rejected]
      ];
      document.getElementById('queue-stats').innerHTML = stats.map(([label, value]) => `<div class="stat"><span class="muted">${label}</span><strong>${value ?? 0}</strong></div>`).join('');
    }

    function renderCandidates(items) {
      document.getElementById('candidates').innerHTML = items.length ? items.map((item) => `
        <div class="item">
          <div><span class="label">${item.status}</span> <strong>${item.bot_display_name}</strong> · ${item.scenario_id}</div>
          <div class="muted" style="margin-top:8px;">${item.text}</div>
          <div class="actions">
            ${item.status === 'pending_review' ? `<button onclick="approveCandidate('${item.id}')">Approve</button><button class="secondary" onclick="rejectCandidate('${item.id}')">Reject</button>` : ''}
            ${item.status === 'approved' ? `<button onclick="sendCandidate('${item.id}')">Send</button>` : ''}
          </div>
        </div>`).join('') : '<div class="muted">No candidates yet.</div>';
    }

    function renderAttempts(items) {
      document.getElementById('attempts').innerHTML = items.length ? items.map((item) => `
        <div class="item">
          <div><span class="label">${item.status}</span> ${item.sender_type}</div>
          <div class="muted" style="margin-top:8px;">candidate=${item.candidate_id}</div>
          <div class="muted">outbound=${item.outbound_message_id || '-'}</div>
        </div>`).join('') : '<div class="muted">No attempts yet.</div>';
    }

    function renderPlannerAudits(items) {
      document.getElementById('planner-audits').innerHTML = items.length ? items.map((item) => `
        <div class="item">
          <div><span class="label">${item.matched ? 'matched' : 'blocked'}</span> ${item.group_id}</div>
          <div class="muted" style="margin-top:8px;">decision=${item.decision_reason}</div>
          <div class="muted">scenario=${item.scenario_id || '-'} · bot=${item.bot_id || '-'}</div>
        </div>`).join('') : '<div class="muted">No planner audits yet.</div>';
    }

    function renderRuntimeIngests(items) {
      document.getElementById('runtime-ingests').innerHTML = items.length ? items.map((item) => `
        <div class="item">
          <div><span class="label">${item.source}</span> ${item.group_id}</div>
          <div class="muted" style="margin-top:8px;">pending_new_members=${item.runtime_input.pending_new_members ?? 0}</div>
          <div class="muted">provider=${item.metadata.provider || '-'}</div>
        </div>`).join('') : '<div class="muted">No runtime ingests yet.</div>';
    }

    function renderSchedulerRuns(items) {
      document.getElementById('scheduler-runs').innerHTML = items.length ? items.map((item) => `
        <div class="item">
          <div><span class="label">${item.status}</span> ${item.group_id}</div>
          <div class="muted" style="margin-top:8px;">workflow=${item.workflow}</div>
          <div class="muted">candidate=${item.candidate_id || '-'} · audit=${item.planner_audit_id || '-'}</div>
        </div>`).join('') : '<div class="muted">No scheduler runs yet.</div>';
    }

    function renderSchedulerConfigs(items) {
      document.getElementById('scheduler-configs').innerHTML = items.length ? items.map((item) => `
        <div class="item">
          <div><span class="label">${item.enabled ? 'enabled' : 'disabled'}</span> ${item.group_id}</div>
          <div class="muted" style="margin-top:8px;">workflow=${item.workflow} · reviewer=${item.reviewer}</div>
          <div class="actions">
            <button onclick="loadGroupConfigIntoForm('${item.group_id}')">Edit config</button>
          </div>
        </div>`).join('') : '<div class="muted">No scheduler configs yet.</div>';
    }

    function renderGroupStatus(items) {
      document.getElementById('group-status-cards').innerHTML = items.length ? items.map((item) => `
        <div class="item">
          <div><span class="label">${item.config_enabled ? 'enabled' : 'disabled'}</span> ${item.group_id}</div>
          <div class="muted" style="margin-top:8px;">latest run=${item.latest_scheduler_run?.status || '-'} · latest candidate=${item.latest_candidate?.status || '-'}</div>
          <div class="muted">ingest=${item.latest_runtime_ingest?.source || '-'} · workflow=${item.latest_scheduler_config?.workflow || '-'}</div>
          <div class="actions">
            <button onclick="runGroupLatest('${item.group_id}')">Run latest</button>
            <button onclick="loadGroupConfigIntoForm('${item.group_id}')">Edit</button>
            <button class="secondary" onclick="toggleGroupConfig('${item.group_id}', ${item.config_enabled ? 'false' : 'true'})">${item.config_enabled ? 'Disable' : 'Enable'}</button>
          </div>
        </div>`).join('') : '<div class="muted">No group status yet.</div>';
    }

    async function applyGroupStatusFilters() {
      const enabledOnly = document.getElementById('group-status-filter-enabled').checked;
      const sortBy = document.getElementById('group-status-sort').value;
      return requestJson(`/v1/dashboard/group-status?enabled_only=${enabledOnly}&sort_by=${encodeURIComponent(sortBy)}`);
    }

    async function loadDashboard() {
      const [summary, groupStatus] = await Promise.all([
        requestJson('/v1/dashboard/summary'),
        applyGroupStatusFilters(),
      ]);
      document.getElementById('health').textContent = `Health: ${summary.health.status} · default sender=${summary.health.default_sender} · senders=${summary.health.available_senders.join(', ')}`;
      renderQueue(summary.queue);
      renderCandidates(summary.recent_candidates);
      renderAttempts(summary.recent_attempts);
      renderPlannerAudits(summary.recent_planner_audits || []);
      renderRuntimeIngests(summary.recent_runtime_ingests || []);
      renderSchedulerRuns(summary.recent_scheduler_runs || []);
      renderSchedulerConfigs(summary.recent_scheduler_configs || []);
      renderGroupStatus(groupStatus.items || []);
    }

    async function approveCandidate(id) {
      await requestJson(`/v1/review/candidates/${id}/approve`, { method: 'POST', body: JSON.stringify({ reviewer: 'dashboard-ui' }) });
      await loadDashboard();
    }

    async function rejectCandidate(id) {
      await requestJson(`/v1/review/candidates/${id}/reject`, { method: 'POST', body: JSON.stringify({ reviewer: 'dashboard-ui', reason: 'Rejected from dashboard UI' }) });
      await loadDashboard();
    }

    async function sendCandidate(id) {
      await requestJson(`/v1/execution/candidates/${id}/send`, { method: 'POST', body: JSON.stringify({}) });
      await loadDashboard();
    }

    async function executePlanner() {
      const workflow = document.getElementById('planner-workflow').value;
      const payload = {
        config: JSON.parse(document.getElementById('planner-config').value),
        runtime_input: JSON.parse(document.getElementById('planner-runtime').value),
        candidate_context: JSON.parse(document.getElementById('planner-context').value),
        submit_for_review: true,
        workflow,
        reviewer: 'dashboard-ui',
      };
      const data = await requestJson('/v1/ops/planner/execute', { method: 'POST', body: JSON.stringify(payload) });
      document.getElementById('planner-result').textContent = JSON.stringify(data, null, 2);
      await loadDashboard();
    }

    async function ingestRuntime() {
      const payload = JSON.parse(document.getElementById('runtime-ingest-input').value);
      const data = await requestJson('/v1/runtime/ingest', { method: 'POST', body: JSON.stringify(payload) });
      document.getElementById('scheduler-result').textContent = JSON.stringify(data, null, 2);
      await loadDashboard();
    }

    async function saveVisualSchedulerConfig() {
      const payload = {
        group_id: document.getElementById('scheduler-config-group-id').value,
        enabled: document.getElementById('scheduler-config-enabled').value === 'true',
        workflow: document.getElementById('scheduler-config-workflow').value,
        reviewer: document.getElementById('scheduler-config-reviewer').value,
        candidate_context: JSON.parse(document.getElementById('scheduler-config-candidate-context').value),
        config: JSON.parse(document.getElementById('scheduler-config-bot-config').value),
      };
      const data = await requestJson('/v1/scheduler/configs', { method: 'POST', body: JSON.stringify(payload) });
      document.getElementById('scheduler-result').textContent = JSON.stringify(data, null, 2);
      document.getElementById('scheduler-group-id').value = payload.group_id;
      await loadDashboard();
    }

    async function updateExistingSchedulerConfig() {
      const groupId = document.getElementById('scheduler-config-group-id').value;
      const payload = {
        enabled: document.getElementById('scheduler-config-enabled').value === 'true',
        workflow: document.getElementById('scheduler-config-workflow').value,
        reviewer: document.getElementById('scheduler-config-reviewer').value,
        candidate_context: JSON.parse(document.getElementById('scheduler-config-candidate-context').value),
        config: JSON.parse(document.getElementById('scheduler-config-bot-config').value),
      };
      const data = await requestJson(`/v1/scheduler/configs/${groupId}`, { method: 'PUT', body: JSON.stringify(payload) });
      document.getElementById('scheduler-result').textContent = JSON.stringify(data, null, 2);
      document.getElementById('scheduler-group-id').value = groupId;
      await loadDashboard();
    }

    async function loadGroupConfigIntoForm(groupId) {
      const data = await requestJson(`/v1/scheduler/configs/latest?group_id=${encodeURIComponent(groupId)}`);
      document.getElementById('scheduler-config-group-id').value = data.group_id;
      document.getElementById('scheduler-config-enabled').value = String(data.enabled);
      document.getElementById('scheduler-config-workflow').value = data.workflow;
      document.getElementById('scheduler-config-reviewer').value = data.reviewer;
      document.getElementById('scheduler-config-candidate-context').value = JSON.stringify(data.candidate_context || {}, null, 2);
      document.getElementById('scheduler-config-bot-config').value = JSON.stringify(data.config || {}, null, 2);
      document.getElementById('scheduler-group-id').value = data.group_id;
      document.getElementById('scheduler-result').textContent = `Loaded config for ${data.group_id}`;
    }

    async function runGroupLatest(groupId) {
      const data = await requestJson(`/v1/dashboard/groups/${groupId}/run-latest`, { method: 'POST', body: JSON.stringify({}) });
      document.getElementById('scheduler-result').textContent = JSON.stringify(data, null, 2);
      await loadDashboard();
    }

    async function toggleGroupConfig(groupId, enable) {
      const endpoint = enable ? 'enable' : 'disable';
      const data = await requestJson(`/v1/dashboard/groups/${groupId}/${endpoint}`, { method: 'POST', body: JSON.stringify({}) });
      document.getElementById('scheduler-result').textContent = JSON.stringify(data, null, 2);
      await loadDashboard();
    }

    async function runSchedulerLatest() {
      const payload = {
        config: JSON.parse(document.getElementById('planner-config').value),
        group_id: document.getElementById('scheduler-group-id').value,
        candidate_context: JSON.parse(document.getElementById('planner-context').value),
        workflow: document.getElementById('planner-workflow').value,
        reviewer: 'dashboard-scheduler',
      };
      const data = await requestJson('/v1/scheduler/execute-latest', { method: 'POST', body: JSON.stringify(payload) });
      document.getElementById('scheduler-result').textContent = JSON.stringify(data, null, 2);
      await loadDashboard();
    }

    async function runSchedulerTick() {
      const data = await requestJson('/v1/scheduler/tick', { method: 'POST', body: JSON.stringify({}) });
      document.getElementById('scheduler-result').textContent = JSON.stringify(data, null, 2);
      await loadDashboard();
    }

    document.getElementById('planner-submit').addEventListener('click', () => executePlanner().catch((error) => {
      document.getElementById('planner-result').textContent = String(error);
    }));
    document.getElementById('scheduler-config-save').addEventListener('click', () => saveVisualSchedulerConfig().catch((error) => {
      document.getElementById('scheduler-result').textContent = String(error);
    }));
    document.getElementById('scheduler-config-update').addEventListener('click', () => updateExistingSchedulerConfig().catch((error) => {
      document.getElementById('scheduler-result').textContent = String(error);
    }));
    document.getElementById('scheduler-config-group-id').addEventListener('change', () => loadGroupConfigIntoForm(document.getElementById('scheduler-config-group-id').value).catch(() => {}));
    document.getElementById('group-status-filter-enabled').addEventListener('change', () => loadDashboard().catch(console.error));
    document.getElementById('group-status-sort').addEventListener('change', () => loadDashboard().catch(console.error));
    document.getElementById('runtime-ingest-submit').addEventListener('click', () => ingestRuntime().catch((error) => {
      document.getElementById('scheduler-result').textContent = String(error);
    }));
    document.getElementById('scheduler-run-latest').addEventListener('click', () => runSchedulerLatest().catch((error) => {
      document.getElementById('scheduler-result').textContent = String(error);
    }));
    document.getElementById('scheduler-tick-run').addEventListener('click', () => runSchedulerTick().catch((error) => {
      document.getElementById('scheduler-result').textContent = String(error);
    }));
    document.getElementById('planner-refresh').addEventListener('click', () => loadDashboard().catch(console.error));
    loadDashboard().catch((error) => {
      document.getElementById('health').textContent = `Dashboard load failed: ${error}`;
    });
  </script>
</body>
</html>
"""

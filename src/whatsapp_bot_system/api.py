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


class 发送CandidateRequest(BaseModel):
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
                        secret=webhook_secret,
                        timeout_seconds=webhook_timeout_seconds,
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
        audit_map = {item.id: item for item in planner_audit_store.list()}
        candidate_map = {}
        for item in review_service.list_candidates():
            group_id = str(item.context.get('group_id') or '')
            if group_id and group_id not in candidate_map:
                candidate_map[group_id] = item
        group_ids = sorted(set(config_map) | set(ingest_map) | set(run_map) | set(candidate_map))
        items = [
            _build_group_status_item(
                group_id=group_id,
                config_record=config_map.get(group_id),
                ingest_record=ingest_map.get(group_id),
                scheduler_run_record=run_map.get(group_id),
                planner_audit_record=audit_map.get(run_map[group_id].planner_audit_id) if group_id in run_map and run_map[group_id].planner_audit_id else None,
                candidate_record=candidate_map.get(group_id),
            )
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
    def send_candidate(candidate_id: str, request: 发送CandidateRequest | None = None) -> dict:
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


def _apply_workflow(*, record_id: str, workflow: str, reviewer: str, submit_for_review: bool, review_service: ReviewFlowService, execution_service: 发送ExecutionService):
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


def _execute_scheduler_latest(*, request: SchedulerExecuteLatestRequest, runtime_ingest_store: SQLiteRuntimeIngestStore, planner_audit_store: SQLitePlannerAuditStore, review_service: ReviewFlowService, execution_service: 发送ExecutionService, scheduler_run_store: SQLiteSchedulerRunStore) -> dict:
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


def _build_group_status_item(
    *,
    group_id: str,
    config_record,
    ingest_record,
    scheduler_run_record,
    planner_audit_record,
    candidate_record,
) -> dict:
    serialized_ingest = None if ingest_record is None else _serialize_runtime_ingest(ingest_record)
    serialized_run = None if scheduler_run_record is None else _serialize_scheduler_run(scheduler_run_record)
    serialized_candidate = None if candidate_record is None else _serialize_candidate(candidate_record)
    latest_failure_reason = None
    if serialized_candidate and serialized_candidate.get('error_message'):
        latest_failure_reason = serialized_candidate['error_message']
    elif planner_audit_record is not None:
        latest_failure_reason = planner_audit_record.decision_reason
    return {
        'group_id': group_id,
        'config_enabled': False if config_record is None else config_record.enabled,
        'latest_scheduler_config': None if config_record is None else _serialize_scheduler_config(config_record),
        'latest_runtime_ingest': serialized_ingest,
        'latest_runtime_ingest_at': None if serialized_ingest is None else serialized_ingest['created_at'],
        'latest_scheduler_run': serialized_run,
        'latest_scheduler_run_at': None if serialized_run is None else serialized_run['created_at'],
        'latest_scheduler_run_status': None if serialized_run is None else serialized_run['status'],
        'latest_candidate': serialized_candidate,
        'latest_failure_reason': latest_failure_reason,
    }


def _render_dashboard_html() -> str:
    return """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>WhatsApp 机器人系统后台</title>
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
      <h1>WhatsApp 机器人系统后台</h1>
      <p class="muted">用于队列审核、策略调度、运行查看与发送操作的 MVP 管理后台。</p>
      <div id="health" class="muted">Loading health…</div>
    </section>

    <section class="panel">
      <h2>队列概览</h2>
      <div id="queue-stats" class="grid"></div>
    </section>

    <section class="panel">
      <h2>策略执行</h2>
      <p class="muted">填写配置、运行态和候选上下文 JSON，通过 <code>/v1/ops/planner/execute</code> 生成候选消息。</p>
      <div class="row">
        <div>
          <label>策略配置 JSON</label>
          <textarea id="planner-config"></textarea>
          <label style="display:block;margin-top:12px;">运行态输入 JSON</label>
          <textarea id="planner-runtime"></textarea>
        </div>
        <div>
          <label>候选上下文 JSON</label>
          <textarea id="planner-context"></textarea>
          <label style="display:block;margin-top:12px;">工作流</label>
          <select id="planner-workflow" style="width:100%;box-sizing:border-box;border:1px solid #dbe3f0;border-radius:10px;padding:10px 12px;font:inherit;">
            <option value="queue">入队 → 待审核</option>
            <option value="approve">入队 → 已通过</option>
            <option value="send">入队 → 已通过 → 发送</option>
          </select>
          <div class="actions">
            <button id="planner-submit">执行策略工作流</button>
            <button class="secondary" id="planner-refresh">刷新后台</button>
          </div>
          <pre id="planner-result" class="item muted">暂无执行结果。</pre>
        </div>
      </div>
    </section>

    <div class="row">
      <section class="panel">
        <h2>待审核 / 最近候选消息</h2>
        <div id="candidates"></div>
      </section>
      <section class="panel">
        <h2>最近发送尝试</h2>
        <div id="attempts"></div>
      </section>
    </div>

    <section class="panel">
      <h2>最近策略审计</h2>
      <div id="planner-audits"></div>
    </section>

    <section class="panel">
      <h2>群组状态总览</h2>
      <div class="actions">
        <label style="display:flex;align-items:center;gap:8px;">
          <input id="group-status-filter-enabled" type="checkbox" />
          <span class="muted">仅看启用中</span>
        </label>
        <select id="group-status-sort" style="width:auto;min-width:220px;box-sizing:border-box;border:1px solid #dbe3f0;border-radius:10px;padding:10px 12px;font:inherit;">
          <option value="group_id_asc">排序：群组 ID</option>
          <option value="latest_scheduler_run_desc">排序：最近运行（新到旧）</option>
          <option value="latest_scheduler_run_asc">排序：最近运行（旧到新）</option>
        </select>
      </div>
      <div id="group-status-cards"></div>
    </section>

    <section class="panel" id="scheduler-config-editor">
      <h2>调度配置编辑</h2>
      <div class="item" style="margin-bottom:16px;background:#f8fafc;">
        <div style="font-weight:600;margin-bottom:10px;">中文辅助表单</div>
        <div class="row">
          <div>
            <label>群名称</label>
            <input id="scheduler-form-group-name" />
            <label style="display:block;margin-top:12px;">群公告摘要</label>
            <textarea id="scheduler-form-rules-summary"></textarea>
            <label style="display:block;margin-top:12px;">采集提供方</label>
            <input id="scheduler-form-provider" />
          </div>
          <div>
            <label>机器人昵称</label>
            <input id="scheduler-form-bot-display-name" />
            <label style="display:block;margin-top:12px;">机器人角色</label>
            <select id="scheduler-form-bot-role" style="width:100%;box-sizing:border-box;border:1px solid #dbe3f0;border-radius:10px;padding:10px 12px;font:inherit;">
              <option value="welcomer">欢迎机器人</option>
              <option value="starter">话题机器人</option>
              <option value="supporter">陪聊机器人</option>
            </select>
            <label style="display:block;margin-top:12px;">场景 ID</label>
            <select id="scheduler-form-scenario-id" style="width:100%;box-sizing:border-box;border:1px solid #dbe3f0;border-radius:10px;padding:10px 12px;font:inherit;">
              <option value="welcome">新人欢迎</option>
              <option value="cold_start">冷场救场</option>
              <option value="event_preheat">活动预热</option>
              <option value="manual_review">人工审核</option>
            </select>
            <label style="display:block;margin-top:12px;">内容模式</label>
            <select id="scheduler-form-content-mode" style="width:100%;box-sizing:border-box;border:1px solid #dbe3f0;border-radius:10px;padding:10px 12px;font:inherit;">
              <option value="template_rewrite">模板改写</option>
              <option value="fixed_copy">固定话术</option>
              <option value="ai_generate">AI 生成</option>
            </select>
            <label style="display:block;margin-top:12px;">活跃时段</label>
            <div class="actions">
              <div style="flex:1;min-width:0;">
                <label class="muted" style="display:block;margin-bottom:6px;">开始时间</label>
                <input id="scheduler-form-active-start" type="time" value="08:00" />
              </div>
              <div style="flex:1;min-width:0;">
                <label class="muted" style="display:block;margin-bottom:6px;">结束时间</label>
                <input id="scheduler-form-active-end" type="time" value="22:00" />
              </div>
            </div>
            <label style="display:block;margin-top:12px;">冷却时间（秒）</label>
            <input id="scheduler-form-cooldown-seconds" type="number" min="0" />
            <div id="scheduler-form-cooldown-minutes-hint" class="muted" style="margin-top:6px;">约 10.0 分钟</div>
            <label style="display:block;margin-top:12px;">新成员阈值</label>
            <input id="scheduler-form-pending-threshold" type="number" min="0" />
            <div id="scheduler-form-pending-threshold-hint" class="muted" style="margin-top:6px;">达到该人数时，优先触发欢迎场景</div>
          </div>
        </div>
      </div>
      <div id="scheduler-toast" class="item" style="display:none;margin-top:12px;border-color:#bbf7d0;background:#f0fdf4;color:#166534;">保存成功</div>
      <div id="scheduler-preview-card" class="item" style="margin-top:12px;background:#fff7ed;border-color:#fed7aa;">
        <div style="font-weight:600;margin-bottom:8px;">候选文案预览</div>
        <div class="muted" id="scheduler-preview-meta">角色 / 场景 / 内容模式</div>
        <div id="scheduler-preview-copy" style="margin-top:10px;line-height:1.7;">预估文案</div>
      </div>
      <div class="actions" style="margin:12px 0 0;">
        <button class="secondary" id="scheduler-config-advanced-toggle">显示高级模式（JSON）</button>
      </div>
      <div class="row" id="scheduler-config-advanced-panel" style="display:none;">
        <div>
          <label>群组 ID</label>
          <input id="scheduler-config-group-id" />
          <label style="display:block;margin-top:12px;">是否启用</label>
          <select id="scheduler-config-enabled" style="width:100%;box-sizing:border-box;border:1px solid #dbe3f0;border-radius:10px;padding:10px 12px;font:inherit;">
            <option value="true">是</option>
            <option value="false">否</option>
          </select>
          <label style="display:block;margin-top:12px;">工作流</label>
          <select id="scheduler-config-workflow" style="width:100%;box-sizing:border-box;border:1px solid #dbe3f0;border-radius:10px;padding:10px 12px;font:inherit;">
            <option value="queue">入队</option>
            <option value="approve">审核通过</option>
            <option value="send">直接发送</option>
          </select>
          <label style="display:block;margin-top:12px;">审核人</label>
          <input id="scheduler-config-reviewer" />
        </div>
        <div>
          <label>候选上下文 JSON</label>
          <textarea id="scheduler-config-candidate-context"></textarea>
          <label style="display:block;margin-top:12px;">机器人配置 JSON</label>
          <textarea id="scheduler-config-bot-config"></textarea>
          <div class="actions">
            <button id="scheduler-config-save">保存调度配置</button>
            <button class="secondary" id="scheduler-config-update">更新现有配置</button>
          </div>
        </div>
      </div>
      <h3>最近调度配置</h3>
      <div id="scheduler-configs"></div>
    </section>

    <section class="panel">
      <h2>运行态 Webhook / 调度器</h2>
      <div class="row">
        <div>
          <label>运行态采集 JSON</label>
          <textarea id="runtime-ingest-input"></textarea>
          <div class="actions">
            <button id="runtime-ingest-submit">写入运行态</button>
          </div>
        </div>
        <div>
          <label>调度群组 ID</label>
          <input id="scheduler-group-id" />
          <div class="actions">
            <button id="scheduler-run-latest">执行最新采集</button>
            <button class="secondary" id="scheduler-tick-run">执行批量 Tick</button>
          </div>
          <pre id="scheduler-result" class="item muted">暂无调度执行结果。</pre>
          <h3>最近运行态采集</h3>
          <div id="runtime-ingests"></div>
          <h3 style="margin-top:16px;">最近调度运行</h3>
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
    const defaultContext = { group_name: '妈妈成长群', rules_summary: '请先查看群公告。', pending_new_members: 1 };
    const defaultRuntimeIngest = { source: 'webhook', group_id: '120363001234567890@g.us', runtime_input: defaultRuntime, metadata: { provider: '桥接服务A' } };
    const defaultSchedulerConfig = { group_id: '120363001234567890@g.us', enabled: true, workflow: 'send', reviewer: '后台调度', candidate_context: defaultContext, config: defaultConfig };
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

    function updateStructuredSchedulerForm() {
      let candidateContext = {};
      let config = {};
      try {
        candidateContext = JSON.parse(document.getElementById('scheduler-config-candidate-context').value || '{}');
      } catch (_) {}
      try {
        config = JSON.parse(document.getElementById('scheduler-config-bot-config').value || '{}');
      } catch (_) {}
      const firstBot = Array.isArray(config.bots) && config.bots.length ? config.bots[0] : {};
      const firstScenario = Array.isArray(config.scenarios) && config.scenarios.length ? config.scenarios[0] : {};
      document.getElementById('scheduler-form-group-name').value = candidateContext.group_name || '';
      document.getElementById('scheduler-form-rules-summary').value = candidateContext.rules_summary || '';
      document.getElementById('scheduler-form-provider').value = ((JSON.parse(document.getElementById('runtime-ingest-input').value || '{}').metadata) || {}).provider || '';
      document.getElementById('scheduler-form-bot-display-name').value = firstBot.display_name || '';
      document.getElementById('scheduler-form-bot-role').value = firstBot.role || 'welcomer';
      document.getElementById('scheduler-form-scenario-id').value = firstScenario.id || 'welcome';
      document.getElementById('scheduler-form-content-mode').value = firstScenario.content_mode || (Array.isArray(firstBot.content_modes) && firstBot.content_modes[0]) || 'template_rewrite';
      document.getElementById('scheduler-form-active-start').value = formatHourToTimeInput(Array.isArray(firstBot.active_hours) ? firstBot.active_hours[0] : 8);
      document.getElementById('scheduler-form-active-end').value = formatHourToTimeInput(Array.isArray(firstBot.active_hours) && firstBot.active_hours.length ? (firstBot.active_hours[firstBot.active_hours.length - 1] + 1) % 24 : 22);
      document.getElementById('scheduler-form-cooldown-seconds').value = firstBot.cooldown_seconds ?? 0;
      document.getElementById('scheduler-form-cooldown-minutes-hint').textContent = `约 ${((Number(firstBot.cooldown_seconds ?? 0)) / 60).toFixed(1)} 分钟`;
      document.getElementById('scheduler-form-pending-threshold').value = candidateContext.pending_new_members ?? 0;
      renderSchedulerPreviewCard();
    }

    function formatHourToTimeInput(hour) {
      const safeHour = Math.max(0, Math.min(23, Number.isFinite(Number(hour)) ? Number(hour) : 0));
      return `${String(safeHour).padStart(2, '0')}:00`;
    }

    function buildActiveHoursFromRange(startValue, endValue) {
      const startHour = Number(String(startValue || '08:00').split(':')[0]);
      const endHour = Number(String(endValue || '22:00').split(':')[0]);
      const hours = [];
      let current = startHour;
      while (current !== endHour) {
        hours.push(current);
        current = (current + 1) % 24;
        if (hours.length > 24) break;
      }
      return hours;
    }

    function syncSchedulerJsonFromStructuredForm() {
      const candidateContext = JSON.parse(document.getElementById('scheduler-config-candidate-context').value || '{}');
      candidateContext.group_name = document.getElementById('scheduler-form-group-name').value.trim();
      candidateContext.rules_summary = document.getElementById('scheduler-form-rules-summary').value.trim();
      candidateContext.pending_new_members = Number(document.getElementById('scheduler-form-pending-threshold').value || 0);
      document.getElementById('scheduler-config-candidate-context').value = JSON.stringify(candidateContext, null, 2);

      const config = JSON.parse(document.getElementById('scheduler-config-bot-config').value || '{}');
      if (!Array.isArray(config.bots) || !config.bots.length) {
        config.bots = [{}];
      }
      if (!Array.isArray(config.scenarios) || !config.scenarios.length) {
        config.scenarios = [{}];
      }
      config.bots[0].display_name = document.getElementById('scheduler-form-bot-display-name').value.trim();
      config.bots[0].role = document.getElementById('scheduler-form-bot-role').value.trim();
      config.bots[0].content_modes = [document.getElementById('scheduler-form-content-mode').value];
      config.bots[0].active_hours = buildActiveHoursFromRange(
        document.getElementById('scheduler-form-active-start').value,
        document.getElementById('scheduler-form-active-end').value,
      );
      config.bots[0].cooldown_seconds = Number(document.getElementById('scheduler-form-cooldown-seconds').value || 0);
      document.getElementById('scheduler-form-cooldown-minutes-hint').textContent = `约 ${(config.bots[0].cooldown_seconds / 60).toFixed(1)} 分钟`;
      config.scenarios[0].id = document.getElementById('scheduler-form-scenario-id').value.trim();
      config.scenarios[0].bot_roles = [document.getElementById('scheduler-form-bot-role').value.trim()];
      config.scenarios[0].content_mode = document.getElementById('scheduler-form-content-mode').value;
      document.getElementById('scheduler-config-bot-config').value = JSON.stringify(config, null, 2);

      const runtimeIngest = JSON.parse(document.getElementById('runtime-ingest-input').value || '{}');
      runtimeIngest.metadata = runtimeIngest.metadata || {};
      runtimeIngest.metadata.provider = document.getElementById('scheduler-form-provider').value.trim();
      runtimeIngest.runtime_input = runtimeIngest.runtime_input || {};
      runtimeIngest.runtime_input.pending_new_members = Number(document.getElementById('scheduler-form-pending-threshold').value || 0);
      document.getElementById('runtime-ingest-input').value = JSON.stringify(runtimeIngest, null, 2);
      renderSchedulerPreviewCard();
    }

    updateStructuredSchedulerForm();

    function toggleSchedulerAdvancedMode(forceOpen = null) {
      const panel = document.getElementById('scheduler-config-advanced-panel');
      const button = document.getElementById('scheduler-config-advanced-toggle');
      const shouldOpen = forceOpen === null ? panel.style.display === 'none' : forceOpen;
      panel.style.display = shouldOpen ? 'grid' : 'none';
      button.textContent = shouldOpen ? '收起高级模式（JSON）' : '显示高级模式（JSON）';
    }

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
        ['总数', queue.total], ['待审核', queue.pending_review], ['已通过', queue.approved], ['已发送', queue.sent], ['失败', queue.failed], ['已驳回', queue.rejected]
      ];
      document.getElementById('queue-stats').innerHTML = stats.map(([label, value]) => `<div class="stat"><span class="muted">${label}</span><strong>${value ?? 0}</strong></div>`).join('');
    }

    function formatStatusLabel(status) {
      const labels = {
        pending_review: '待审核',
        approved: '已通过',
        sent: '已发送',
        failed: '失败',
        rejected: '已驳回',
        generated: '已生成',
        no_match: '未命中',
      };
      return labels[status] || status || '-';
    }

    function formatWorkflowLabel(workflow) {
      const labels = {
        queue: '入队',
        approve: '审核通过',
        send: '直接发送',
      };
      return labels[workflow] || workflow || '-';
    }

    function formatRoleLabel(role) {
      const labels = {
        welcomer: '欢迎机器人',
        starter: '话题机器人',
        supporter: '陪聊机器人',
      };
      return labels[role] || role || '-';
    }

    function formatScenarioLabel(scenario) {
      const labels = {
        welcome: '新人欢迎',
        cold_start: '冷场救场',
        event_preheat: '活动预热',
        manual_review: '人工审核',
      };
      return labels[scenario] || scenario || '-';
    }

    function formatContentModeLabel(mode) {
      const labels = {
        template_rewrite: '模板改写',
        fixed_copy: '固定话术',
        ai_generate: 'AI 生成',
      };
      return labels[mode] || mode || '-';
    }

    function renderSchedulerPreviewCard() {
      const groupName = document.getElementById('scheduler-form-group-name').value.trim() || '当前群组';
      const role = document.getElementById('scheduler-form-bot-role').value;
      const scenario = document.getElementById('scheduler-form-scenario-id').value;
      const contentMode = document.getElementById('scheduler-form-content-mode').value;
      const botName = document.getElementById('scheduler-form-bot-display-name').value.trim() || '机器人';
      const rulesSummary = document.getElementById('scheduler-form-rules-summary').value.trim() || '请先查看群公告。';
      const pendingThreshold = Number(document.getElementById('scheduler-form-pending-threshold').value || 0);
      const meta = `角色：${formatRoleLabel(role)} · 场景：${formatScenarioLabel(scenario)} · 内容模式：${formatContentModeLabel(contentMode)}`;
      let copy = `${groupName}的朋友们好，我是${botName}，${rulesSummary}`;
      if (scenario === 'welcome') {
        copy = `欢迎加入${groupName}，我是${botName}。${rulesSummary}${pendingThreshold > 0 ? ` 当前有 ${pendingThreshold} 位新成员待欢迎。` : ''}`;
      } else if (scenario === 'cold_start') {
        copy = `${groupName}今天有点安静，我是${botName}，来抛个轻松话题，看看大家最近最关心什么？`;
      } else if (scenario === 'event_preheat') {
        copy = `${groupName}的活动快开始了，我是${botName}，先帮大家热热场，等会儿记得看群公告安排。`;
      } else if (scenario === 'manual_review') {
        copy = `这是给${groupName}准备的人工审核候选文案：我是${botName}，先提醒大家${rulesSummary}`;
      }
      document.getElementById('scheduler-preview-meta').textContent = meta;
      document.getElementById('scheduler-preview-copy').textContent = copy;
    }

    function showSchedulerToast(message) {
      const toast = document.getElementById('scheduler-toast');
      toast.textContent = message;
      toast.style.display = 'block';
    }

    function formatSenderLabel(sender) {
      const labels = {
        mock: '模拟发送',
        dry_run: '演练发送',
        webhook: 'Webhook 发送',
      };
      return labels[sender] || sender || '-';
    }

    function formatSourceLabel(source) {
      const labels = {
        webhook: 'Webhook',
        runtime_file: '运行态文件',
        manual: '手动录入',
      };
      return labels[source] || source || '-';
    }

    function renderCandidates(items) {
      document.getElementById('candidates').innerHTML = items.length ? items.map((item) => `
        <div class="item">
          <div><span class="label">${formatStatusLabel(item.status)}</span> <strong>${item.bot_display_name}</strong> · ${item.scenario_id}</div>
          <div class="muted" style="margin-top:8px;">${item.text}</div>
          <div class="actions">
            ${item.status === 'pending_review' ? `<button onclick="approveCandidate('${item.id}')">通过</button><button class="secondary" onclick="rejectCandidate('${item.id}')">驳回</button>` : ''}
            ${item.status === 'approved' ? `<button onclick="sendCandidate('${item.id}')">发送</button>` : ''}
          </div>
        </div>`).join('') : '<div class="muted">暂无候选消息。</div>';
    }

    function renderAttempts(items) {
      document.getElementById('attempts').innerHTML = items.length ? items.map((item) => `
        <div class="item">
          <div><span class="label">${formatStatusLabel(item.status)}</span> ${formatSenderLabel(item.sender_type)}</div>
          <div class="muted" style="margin-top:8px;">候选=${item.candidate_id}</div>
          <div class="muted">外发消息=${item.outbound_message_id || '-'}</div>
        </div>`).join('') : '<div class="muted">暂无发送尝试。</div>';
    }

    function renderPlannerAudits(items) {
      document.getElementById('planner-audits').innerHTML = items.length ? items.map((item) => `
        <div class="item">
          <div><span class="label">${item.matched ? '已命中' : '已拦截'}</span> ${item.group_id}</div>
          <div class="muted" style="margin-top:8px;">决策=${item.decision_reason}</div>
          <div class="muted">场景=${item.scenario_id || '-'} · 机器人=${item.bot_id || '-'}</div>
        </div>`).join('') : '<div class="muted">暂无策略审计。</div>';
    }

    function renderRuntimeIngests(items) {
      document.getElementById('runtime-ingests').innerHTML = items.length ? items.map((item) => `
        <div class="item">
          <div><span class="label">${formatSourceLabel(item.source)}</span> ${item.group_id}</div>
          <div class="muted" style="margin-top:8px;">待欢迎新成员=${item.runtime_input.pending_new_members ?? 0}</div>
          <div class="muted">提供方=${item.metadata.provider || '-'}</div>
        </div>`).join('') : '<div class="muted">暂无运行态采集。</div>';
    }

    function renderSchedulerRuns(items) {
      document.getElementById('scheduler-runs').innerHTML = items.length ? items.map((item) => `
        <div class="item">
          <div><span class="label">${formatStatusLabel(item.status)}</span> ${item.group_id}</div>
          <div class="muted" style="margin-top:8px;">工作流=${formatWorkflowLabel(item.workflow)}</div>
          <div class="muted">候选=${item.candidate_id || '-'} · 审计=${item.planner_audit_id || '-'}</div>
        </div>`).join('') : '<div class="muted">暂无调度运行。</div>';
    }

    function renderSchedulerConfigs(items) {
      document.getElementById('scheduler-configs').innerHTML = items.length ? items.map((item) => `
        <div class="item">
          <div><span class="label">${item.enabled ? '已启用' : '未启用'}</span> ${item.group_id}</div>
          <div class="muted" style="margin-top:8px;">工作流=${formatWorkflowLabel(item.workflow)} · 审核人=${item.reviewer}</div>
          <div class="actions">
            <button onclick="loadGroupConfigIntoForm('${item.group_id}')">编辑配置</button>
          </div>
        </div>`).join('') : '<div class="muted">暂无调度配置。</div>';
    }

    function renderGroupStatus(items) {
      document.getElementById('group-status-cards').innerHTML = items.length ? items.map((item) => `
        <div class="item">
          <div><span class="label">${item.config_enabled ? '已启用' : '未启用'}</span> ${item.group_id}</div>
          <div class="muted" style="margin-top:8px;">最近运行=${formatStatusLabel(item.latest_scheduler_run_status)} · 最近候选=${formatStatusLabel(item.latest_candidate?.status)}</div>
          <div class="muted">最近采集时间=${item.latest_runtime_ingest_at || '-'} · 最近运行时间=${item.latest_scheduler_run_at || '-'}</div>
          <div class="muted">采集源=${item.latest_runtime_ingest?.source || '-'} · 工作流=${formatWorkflowLabel(item.latest_scheduler_config?.workflow)}</div>
          <div class="muted">最近失败原因=${item.latest_failure_reason || '-'}</div>
          <div class="actions">
            <button onclick="runGroupLatest('${item.group_id}')">执行最新</button>
            <button onclick="loadGroupConfigIntoForm('${item.group_id}')">编辑</button>
            <button class="secondary" onclick="toggleGroupConfig('${item.group_id}', ${item.config_enabled ? 'false' : 'true'})">${item.config_enabled ? '停用' : '启用'}</button>
          </div>
        </div>`).join('') : '<div class="muted">暂无群组状态。</div>';
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
      document.getElementById('health').textContent = `系统状态：${summary.health.status} · 默认发送器=${formatSenderLabel(summary.health.default_sender)} · 可用发送器=${summary.health.available_senders.map(formatSenderLabel).join('、')}`;
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
      await requestJson(`/v1/review/candidates/${id}/reject`, { method: 'POST', body: JSON.stringify({ reviewer: 'dashboard-ui', reason: '后台界面手动驳回' }) });
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
      syncSchedulerJsonFromStructuredForm();
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
      showSchedulerToast(`保存成功：${payload.group_id}`);
      document.getElementById('scheduler-group-id').value = payload.group_id;
      await loadDashboard();
    }

    async function updateExistingSchedulerConfig() {
      const groupId = document.getElementById('scheduler-config-group-id').value;
      syncSchedulerJsonFromStructuredForm();
      const payload = {
        enabled: document.getElementById('scheduler-config-enabled').value === 'true',
        workflow: document.getElementById('scheduler-config-workflow').value,
        reviewer: document.getElementById('scheduler-config-reviewer').value,
        candidate_context: JSON.parse(document.getElementById('scheduler-config-candidate-context').value),
        config: JSON.parse(document.getElementById('scheduler-config-bot-config').value),
      };
      const data = await requestJson(`/v1/scheduler/configs/${groupId}`, { method: 'PUT', body: JSON.stringify(payload) });
      document.getElementById('scheduler-result').textContent = JSON.stringify(data, null, 2);
      showSchedulerToast(`保存成功：${groupId}`);
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
      updateStructuredSchedulerForm();
      toggleSchedulerAdvancedMode(true);
      document.getElementById('scheduler-result').textContent = `已加载 ${data.group_id} 的配置`;
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
    document.getElementById('scheduler-config-advanced-toggle').addEventListener('click', () => toggleSchedulerAdvancedMode());
    ['scheduler-form-group-name', 'scheduler-form-rules-summary', 'scheduler-form-provider', 'scheduler-form-bot-display-name', 'scheduler-form-bot-role', 'scheduler-form-scenario-id', 'scheduler-form-content-mode', 'scheduler-form-active-start', 'scheduler-form-active-end', 'scheduler-form-cooldown-seconds', 'scheduler-form-pending-threshold'].forEach((id) => {
      document.getElementById(id).addEventListener('input', () => {
        try { syncSchedulerJsonFromStructuredForm(); } catch (_) {}
      });
    });
    ['scheduler-config-candidate-context', 'scheduler-config-bot-config', 'runtime-ingest-input'].forEach((id) => {
      document.getElementById(id).addEventListener('input', () => {
        try { updateStructuredSchedulerForm(); } catch (_) {}
      });
    });
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
      document.getElementById('health').textContent = `后台加载失败：${error}`;
    });
  </script>
</body>
</html>
"""

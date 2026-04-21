from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
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


class PlannerExecuteRequest(PlannerDryRunRequest):
    submit_for_review: bool = True


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
        }

    @app.post('/v1/planner/dry-run')
    def planner_dry_run(request: PlannerDryRunRequest) -> dict:
        execution = _plan_candidate_execution(request)
        if execution is None:
            return {'matched': False, 'plan': None, 'candidate_message': None}

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
        }

    @app.post('/v1/ops/planner/execute')
    def execute_planner(request: PlannerExecuteRequest) -> dict:
        execution = _plan_candidate_execution(request)
        if execution is None:
            return {'matched': False, 'plan': None, 'candidate': None}

        plan, candidate = execution
        record = review_service.create_candidate(
            bot_id=plan.bot_id,
            bot_display_name=candidate.bot_display_name,
            scenario_id=plan.scenario_id,
            content_mode=plan.content_mode,
            text=candidate.text,
            context=request.candidate_context,
        )
        if request.submit_for_review:
            record = review_service.submit_for_review(record.id)
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


def _plan_candidate_execution(request: PlannerDryRunRequest):
    config = load_multi_bot_config(request.config)
    state = _build_state_from_request(request)
    plan = plan_group_action(config, state)
    if plan is None:
        return None
    bot_name = _resolve_bot_name(request.config, plan.bot_id)
    candidate = create_candidate_message(
        scenario_id=plan.scenario_id,
        bot_display_name=bot_name,
        content_mode=plan.content_mode,
        context=request.candidate_context,
    )
    return plan, candidate


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
          <div class="actions">
            <button id="planner-submit">Generate Candidate</button>
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
    document.getElementById('planner-config').value = JSON.stringify(defaultConfig, null, 2);
    document.getElementById('planner-runtime').value = JSON.stringify(defaultRuntime, null, 2);
    document.getElementById('planner-context').value = JSON.stringify(defaultContext, null, 2);

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

    async function loadDashboard() {
      const data = await requestJson('/v1/dashboard/summary');
      document.getElementById('health').textContent = `Health: ${data.health.status} · default sender=${data.health.default_sender} · senders=${data.health.available_senders.join(', ')}`;
      renderQueue(data.queue);
      renderCandidates(data.recent_candidates);
      renderAttempts(data.recent_attempts);
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
      const payload = {
        config: JSON.parse(document.getElementById('planner-config').value),
        runtime_input: JSON.parse(document.getElementById('planner-runtime').value),
        candidate_context: JSON.parse(document.getElementById('planner-context').value),
        submit_for_review: true,
      };
      const data = await requestJson('/v1/ops/planner/execute', { method: 'POST', body: JSON.stringify(payload) });
      document.getElementById('planner-result').textContent = JSON.stringify(data, null, 2);
      await loadDashboard();
    }

    document.getElementById('planner-submit').addEventListener('click', () => executePlanner().catch((error) => {
      document.getElementById('planner-result').textContent = String(error);
    }));
    document.getElementById('planner-refresh').addEventListener('click', () => loadDashboard().catch(console.error));
    loadDashboard().catch((error) => {
      document.getElementById('health').textContent = `Dashboard load failed: ${error}`;
    });
  </script>
</body>
</html>
"""

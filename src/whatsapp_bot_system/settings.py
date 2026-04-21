from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class DatabaseSettings:
    review_db_path: str = 'data/review_flow.db'
    execution_db_path: str = 'data/execution_attempts.db'
    planner_audit_db_path: str = 'data/planner_audits.db'
    runtime_ingest_db_path: str = 'data/runtime_ingest.db'
    scheduler_run_db_path: str = 'data/scheduler_runs.db'
    scheduler_config_db_path: str = 'data/scheduler_configs.db'


@dataclass(frozen=True)
class WebhookSenderSettings:
    endpoint: str = ''
    timeout_seconds: float = 10.0
    secret: str = ''


@dataclass(frozen=True)
class ExecutionSettings:
    default_sender: str = 'mock'
    webhook_sender: WebhookSenderSettings = field(default_factory=WebhookSenderSettings)


@dataclass(frozen=True)
class APISettings:
    host: str = '127.0.0.1'
    port: int = 8787


@dataclass(frozen=True)
class AppSettings:
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)
    api: APISettings = field(default_factory=APISettings)
    templates: dict[str, Any] = field(default_factory=lambda: {'personas': {}, 'scenarios': {}})

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> 'AppSettings':
        data = payload or {}
        database = data.get('database') or {}
        execution = data.get('execution') or {}
        webhook_sender = execution.get('webhook_sender') or {}
        api = data.get('api') or {}
        templates = data.get('templates') or {'personas': {}, 'scenarios': {}}
        return cls(
            database=DatabaseSettings(
                review_db_path=str(database.get('review_db_path') or 'data/review_flow.db'),
                execution_db_path=str(database.get('execution_db_path') or 'data/execution_attempts.db'),
                planner_audit_db_path=str(database.get('planner_audit_db_path') or 'data/planner_audits.db'),
                runtime_ingest_db_path=str(database.get('runtime_ingest_db_path') or 'data/runtime_ingest.db'),
                scheduler_run_db_path=str(database.get('scheduler_run_db_path') or 'data/scheduler_runs.db'),
                scheduler_config_db_path=str(database.get('scheduler_config_db_path') or 'data/scheduler_configs.db'),
            ),
            execution=ExecutionSettings(
                default_sender=str(execution.get('default_sender') or 'mock'),
                webhook_sender=WebhookSenderSettings(
                    endpoint=str(webhook_sender.get('endpoint') or ''),
                    timeout_seconds=float(webhook_sender.get('timeout_seconds') or 10.0),
                    secret=str(webhook_sender.get('secret') or ''),
                ),
            ),
            api=APISettings(
                host=str(api.get('host') or '127.0.0.1'),
                port=int(api.get('port') or 8787),
            ),
            templates=templates,
        )


def load_settings(path: str | Path) -> AppSettings:
    config_path = Path(path)
    if not config_path.exists():
        return AppSettings()
    data = yaml.safe_load(config_path.read_text(encoding='utf-8')) or {}
    if not isinstance(data, dict):
        return AppSettings()
    return AppSettings.from_dict(data)

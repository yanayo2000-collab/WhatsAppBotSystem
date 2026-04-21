from __future__ import annotations

from pathlib import Path
from typing import Any

from whatsapp_bot_system.api import create_app
from whatsapp_bot_system.settings import AppSettings, load_settings


def create_app_from_settings(settings: AppSettings):
    return create_app(
        db_path=settings.database.review_db_path,
        execution_db_path=settings.database.execution_db_path,
        planner_audit_db_path=settings.database.planner_audit_db_path,
        runtime_ingest_db_path=settings.database.runtime_ingest_db_path,
        scheduler_run_db_path=settings.database.scheduler_run_db_path,
        scheduler_config_db_path=settings.database.scheduler_config_db_path,
        default_sender=settings.execution.default_sender,
        settings_templates=settings.templates,
        webhook_endpoint=settings.execution.webhook_sender.endpoint,
        webhook_timeout_seconds=settings.execution.webhook_sender.timeout_seconds,
        webhook_secret=settings.execution.webhook_sender.secret,
    )


def create_app_from_settings_dict(payload: dict[str, Any]):
    return create_app_from_settings(AppSettings.from_dict(payload))


def create_app_from_config_path(path: str | Path):
    return create_app_from_settings(load_settings(path))

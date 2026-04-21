from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SchedulerRunRecord:
    id: str
    group_id: str
    status: str
    workflow: str
    runtime_ingest_id: str | None
    planner_audit_id: str | None
    candidate_id: str | None
    created_at: str


class SQLiteSchedulerRunStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS scheduler_runs (
                id TEXT PRIMARY KEY,
                group_id TEXT NOT NULL,
                status TEXT NOT NULL,
                workflow TEXT NOT NULL,
                runtime_ingest_id TEXT,
                planner_audit_id TEXT,
                candidate_id TEXT,
                created_at TEXT NOT NULL
            )
            '''
        )
        self._conn.commit()

    def save(self, record: SchedulerRunRecord) -> SchedulerRunRecord:
        self._conn.execute(
            '''
            INSERT INTO scheduler_runs (
                id, group_id, status, workflow, runtime_ingest_id, planner_audit_id, candidate_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                group_id=excluded.group_id,
                status=excluded.status,
                workflow=excluded.workflow,
                runtime_ingest_id=excluded.runtime_ingest_id,
                planner_audit_id=excluded.planner_audit_id,
                candidate_id=excluded.candidate_id,
                created_at=excluded.created_at
            ''',
            (
                record.id,
                record.group_id,
                record.status,
                record.workflow,
                record.runtime_ingest_id,
                record.planner_audit_id,
                record.candidate_id,
                record.created_at,
            ),
        )
        self._conn.commit()
        return record

    def list(self, limit: int | None = None) -> list[SchedulerRunRecord]:
        sql = 'SELECT * FROM scheduler_runs ORDER BY created_at ASC'
        params: tuple = ()
        if limit is not None:
            sql = 'SELECT * FROM scheduler_runs ORDER BY created_at DESC LIMIT ?'
            params = (limit,)
        rows = self._conn.execute(sql, params).fetchall()
        items = [
            SchedulerRunRecord(
                id=row['id'],
                group_id=row['group_id'],
                status=row['status'],
                workflow=row['workflow'],
                runtime_ingest_id=row['runtime_ingest_id'],
                planner_audit_id=row['planner_audit_id'],
                candidate_id=row['candidate_id'],
                created_at=row['created_at'],
            )
            for row in rows
        ]
        return list(reversed(items)) if limit is not None else items

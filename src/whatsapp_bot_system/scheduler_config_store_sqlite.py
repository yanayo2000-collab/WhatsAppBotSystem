from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SchedulerConfigRecord:
    id: str
    group_id: str
    enabled: bool
    workflow: str
    reviewer: str
    candidate_context: dict
    config: dict
    created_at: str


class SQLiteSchedulerConfigStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS scheduler_configs (
                id TEXT PRIMARY KEY,
                group_id TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                workflow TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                candidate_context_json TEXT NOT NULL,
                config_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            '''
        )
        self._conn.commit()

    def save(self, record: SchedulerConfigRecord) -> SchedulerConfigRecord:
        self._conn.execute(
            '''
            INSERT INTO scheduler_configs (
                id, group_id, enabled, workflow, reviewer, candidate_context_json, config_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                group_id=excluded.group_id,
                enabled=excluded.enabled,
                workflow=excluded.workflow,
                reviewer=excluded.reviewer,
                candidate_context_json=excluded.candidate_context_json,
                config_json=excluded.config_json,
                created_at=excluded.created_at
            ''',
            (
                record.id,
                record.group_id,
                1 if record.enabled else 0,
                record.workflow,
                record.reviewer,
                json.dumps(record.candidate_context, ensure_ascii=False, sort_keys=True),
                json.dumps(record.config, ensure_ascii=False, sort_keys=True),
                record.created_at,
            ),
        )
        self._conn.commit()
        return record

    def list(self, enabled_only: bool = False) -> list[SchedulerConfigRecord]:
        sql = 'SELECT * FROM scheduler_configs'
        if enabled_only:
            sql += ' WHERE enabled = 1'
        sql += ' ORDER BY created_at ASC'
        rows = self._conn.execute(sql).fetchall()
        return [self._deserialize(row) for row in rows]

    def latest(self, group_id: str) -> SchedulerConfigRecord:
        row = self._conn.execute(
            'SELECT * FROM scheduler_configs WHERE group_id = ? ORDER BY created_at DESC LIMIT 1',
            (group_id,),
        ).fetchone()
        if row is None:
            raise KeyError(group_id)
        return self._deserialize(row)

    def _deserialize(self, row: sqlite3.Row) -> SchedulerConfigRecord:
        return SchedulerConfigRecord(
            id=row['id'],
            group_id=row['group_id'],
            enabled=bool(row['enabled']),
            workflow=row['workflow'],
            reviewer=row['reviewer'],
            candidate_context=json.loads(row['candidate_context_json']),
            config=json.loads(row['config_json']),
            created_at=row['created_at'],
        )

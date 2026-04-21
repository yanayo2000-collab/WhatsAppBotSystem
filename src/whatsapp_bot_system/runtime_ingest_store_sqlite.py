from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeIngestRecord:
    id: str
    source: str
    group_id: str
    runtime_input: dict
    metadata: dict
    created_at: str


class SQLiteRuntimeIngestStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS runtime_ingests (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                group_id TEXT NOT NULL,
                runtime_input_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            '''
        )
        self._conn.commit()

    def save(self, record: RuntimeIngestRecord) -> RuntimeIngestRecord:
        self._conn.execute(
            '''
            INSERT INTO runtime_ingests (
                id, source, group_id, runtime_input_json, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source=excluded.source,
                group_id=excluded.group_id,
                runtime_input_json=excluded.runtime_input_json,
                metadata_json=excluded.metadata_json,
                created_at=excluded.created_at
            ''',
            (
                record.id,
                record.source,
                record.group_id,
                json.dumps(record.runtime_input, ensure_ascii=False, sort_keys=True),
                json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
                record.created_at,
            ),
        )
        self._conn.commit()
        return record

    def list(self, group_id: str | None = None, limit: int | None = None) -> list[RuntimeIngestRecord]:
        sql = 'SELECT * FROM runtime_ingests'
        params: list = []
        if group_id:
            sql += ' WHERE group_id = ?'
            params.append(group_id)
        sql += ' ORDER BY created_at DESC'
        if limit is not None:
            sql += ' LIMIT ?'
            params.append(limit)
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [self._deserialize(row) for row in rows]

    def latest(self, group_id: str) -> RuntimeIngestRecord:
        rows = self.list(group_id=group_id, limit=1)
        if not rows:
            raise KeyError(group_id)
        return rows[0]

    def _deserialize(self, row: sqlite3.Row) -> RuntimeIngestRecord:
        return RuntimeIngestRecord(
            id=row['id'],
            source=row['source'],
            group_id=row['group_id'],
            runtime_input=json.loads(row['runtime_input_json']),
            metadata=json.loads(row['metadata_json']),
            created_at=row['created_at'],
        )

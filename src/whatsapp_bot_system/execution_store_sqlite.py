from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExecutionAttemptRecord:
    id: str
    candidate_id: str
    sender_type: str
    status: str
    outbound_message_id: str | None
    error_message: str | None
    created_at: str


class SQLiteExecutionAttemptStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS execution_attempts (
                id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                sender_type TEXT NOT NULL,
                status TEXT NOT NULL,
                outbound_message_id TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL
            )
            '''
        )
        self._conn.commit()

    def save(self, record: ExecutionAttemptRecord) -> ExecutionAttemptRecord:
        self._conn.execute(
            '''
            INSERT INTO execution_attempts (
                id, candidate_id, sender_type, status, outbound_message_id, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                candidate_id=excluded.candidate_id,
                sender_type=excluded.sender_type,
                status=excluded.status,
                outbound_message_id=excluded.outbound_message_id,
                error_message=excluded.error_message,
                created_at=excluded.created_at
            ''',
            (
                record.id,
                record.candidate_id,
                record.sender_type,
                record.status,
                record.outbound_message_id,
                record.error_message,
                record.created_at,
            ),
        )
        self._conn.commit()
        return record

    def list_for_candidate(self, candidate_id: str) -> list[ExecutionAttemptRecord]:
        rows = self._conn.execute(
            'SELECT * FROM execution_attempts WHERE candidate_id = ? ORDER BY created_at ASC',
            (candidate_id,),
        ).fetchall()
        return [
            ExecutionAttemptRecord(
                id=row['id'],
                candidate_id=row['candidate_id'],
                sender_type=row['sender_type'],
                status=row['status'],
                outbound_message_id=row['outbound_message_id'],
                error_message=row['error_message'],
                created_at=row['created_at'],
            )
            for row in rows
        ]

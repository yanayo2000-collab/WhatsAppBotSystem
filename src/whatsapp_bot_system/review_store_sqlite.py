from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from whatsapp_bot_system.review_flow import CandidateMessageRecord


class SQLiteCandidateMessageStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS candidate_messages (
                id TEXT PRIMARY KEY,
                bot_id TEXT NOT NULL,
                bot_display_name TEXT NOT NULL,
                scenario_id TEXT NOT NULL,
                content_mode TEXT NOT NULL,
                text TEXT NOT NULL,
                context_json TEXT NOT NULL,
                status TEXT NOT NULL,
                version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                reviewed_by TEXT,
                review_reason TEXT,
                outbound_message_id TEXT,
                error_message TEXT
            )
            '''
        )
        self._conn.commit()

    def save(self, record: CandidateMessageRecord) -> CandidateMessageRecord:
        self._conn.execute(
            '''
            INSERT INTO candidate_messages (
                id, bot_id, bot_display_name, scenario_id, content_mode, text,
                context_json, status, version, created_at, updated_at,
                reviewed_by, review_reason, outbound_message_id, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                bot_id=excluded.bot_id,
                bot_display_name=excluded.bot_display_name,
                scenario_id=excluded.scenario_id,
                content_mode=excluded.content_mode,
                text=excluded.text,
                context_json=excluded.context_json,
                status=excluded.status,
                version=excluded.version,
                created_at=excluded.created_at,
                updated_at=excluded.updated_at,
                reviewed_by=excluded.reviewed_by,
                review_reason=excluded.review_reason,
                outbound_message_id=excluded.outbound_message_id,
                error_message=excluded.error_message
            ''',
            self._serialize(record),
        )
        self._conn.commit()
        return record

    def get(self, record_id: str) -> CandidateMessageRecord:
        row = self._conn.execute(
            'SELECT * FROM candidate_messages WHERE id = ?',
            (record_id,),
        ).fetchone()
        if row is None:
            raise KeyError(record_id)
        return self._deserialize(row)

    def list(self, status: str | None = None) -> list[CandidateMessageRecord]:
        if status is None:
            rows = self._conn.execute(
                'SELECT * FROM candidate_messages ORDER BY created_at ASC'
            ).fetchall()
        else:
            rows = self._conn.execute(
                'SELECT * FROM candidate_messages WHERE status = ? ORDER BY created_at ASC',
                (status,),
            ).fetchall()
        return [self._deserialize(row) for row in rows]

    def _serialize(self, record: CandidateMessageRecord) -> tuple:
        return (
            record.id,
            record.bot_id,
            record.bot_display_name,
            record.scenario_id,
            record.content_mode,
            record.text,
            json.dumps(record.context, ensure_ascii=False, sort_keys=True),
            record.status,
            record.version,
            record.created_at.isoformat(),
            record.updated_at.isoformat(),
            record.reviewed_by,
            record.review_reason,
            record.outbound_message_id,
            record.error_message,
        )

    def _deserialize(self, row: sqlite3.Row) -> CandidateMessageRecord:
        return CandidateMessageRecord(
            id=row['id'],
            bot_id=row['bot_id'],
            bot_display_name=row['bot_display_name'],
            scenario_id=row['scenario_id'],
            content_mode=row['content_mode'],
            text=row['text'],
            context=json.loads(row['context_json']),
            status=row['status'],
            version=row['version'],
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at']),
            reviewed_by=row['reviewed_by'],
            review_reason=row['review_reason'],
            outbound_message_id=row['outbound_message_id'],
            error_message=row['error_message'],
        )

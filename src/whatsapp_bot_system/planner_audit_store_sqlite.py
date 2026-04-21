from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PlannerAuditRecord:
    id: str
    group_id: str
    matched: bool
    scenario_id: str | None
    bot_id: str | None
    trigger: str | None
    decision_reason: str
    created_at: str


class SQLitePlannerAuditStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS planner_audits (
                id TEXT PRIMARY KEY,
                group_id TEXT NOT NULL,
                matched INTEGER NOT NULL,
                scenario_id TEXT,
                bot_id TEXT,
                trigger TEXT,
                decision_reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            '''
        )
        self._conn.commit()

    def save(self, record: PlannerAuditRecord) -> PlannerAuditRecord:
        self._conn.execute(
            '''
            INSERT INTO planner_audits (
                id, group_id, matched, scenario_id, bot_id, trigger, decision_reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                group_id=excluded.group_id,
                matched=excluded.matched,
                scenario_id=excluded.scenario_id,
                bot_id=excluded.bot_id,
                trigger=excluded.trigger,
                decision_reason=excluded.decision_reason,
                created_at=excluded.created_at
            ''',
            (
                record.id,
                record.group_id,
                1 if record.matched else 0,
                record.scenario_id,
                record.bot_id,
                record.trigger,
                record.decision_reason,
                record.created_at,
            ),
        )
        self._conn.commit()
        return record

    def list(self, limit: int | None = None) -> list[PlannerAuditRecord]:
        sql = 'SELECT * FROM planner_audits ORDER BY created_at ASC'
        params: tuple = ()
        if limit is not None:
            sql = 'SELECT * FROM planner_audits ORDER BY created_at DESC LIMIT ?'
            params = (limit,)
        rows = self._conn.execute(sql, params).fetchall()
        items = [
            PlannerAuditRecord(
                id=row['id'],
                group_id=row['group_id'],
                matched=bool(row['matched']),
                scenario_id=row['scenario_id'],
                bot_id=row['bot_id'],
                trigger=row['trigger'],
                decision_reason=row['decision_reason'],
                created_at=row['created_at'],
            )
            for row in rows
        ]
        return list(reversed(items)) if limit is not None else items

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


_ALLOWED_STATUSES = {
    'generated',
    'pending_review',
    'approved',
    'rejected',
    'sent',
    'failed',
}


@dataclass(frozen=True)
class CandidateMessageRecord:
    id: str
    bot_id: str
    bot_display_name: str
    scenario_id: str
    content_mode: str
    text: str
    context: dict[str, Any]
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
    reviewed_by: str | None = None
    review_reason: str | None = None
    outbound_message_id: str | None = None
    error_message: str | None = None


class CandidateMessageStore:
    def __init__(self) -> None:
        self._records: dict[str, CandidateMessageRecord] = {}

    def save(self, record: CandidateMessageRecord) -> CandidateMessageRecord:
        self._records[record.id] = record
        return record

    def get(self, record_id: str) -> CandidateMessageRecord:
        if record_id not in self._records:
            raise KeyError(record_id)
        return self._records[record_id]

    def list(self, status: str | None = None) -> list[CandidateMessageRecord]:
        items = list(self._records.values())
        items.sort(key=lambda item: item.created_at)
        if status is None:
            return items
        return [item for item in items if item.status == status]


class ReviewFlowService:
    def __init__(self, store: CandidateMessageStore) -> None:
        self.store = store

    def create_candidate(
        self,
        *,
        bot_id: str,
        bot_display_name: str,
        scenario_id: str,
        content_mode: str,
        text: str,
        context: dict[str, Any],
    ) -> CandidateMessageRecord:
        now = _utcnow()
        record = CandidateMessageRecord(
            id=f'cand_{uuid4().hex[:12]}',
            bot_id=bot_id,
            bot_display_name=bot_display_name,
            scenario_id=scenario_id,
            content_mode=content_mode,
            text=text,
            context=context,
            status='generated',
            version=1,
            created_at=now,
            updated_at=now,
        )
        return self.store.save(record)

    def submit_for_review(self, record_id: str) -> CandidateMessageRecord:
        return self._transition(record_id, allowed_from={'generated'}, status='pending_review')

    def approve(self, record_id: str, *, reviewer: str) -> CandidateMessageRecord:
        return self._transition(
            record_id,
            allowed_from={'pending_review'},
            status='approved',
            reviewed_by=reviewer,
            review_reason=None,
            error_message=None,
        )

    def reject(self, record_id: str, *, reviewer: str, reason: str) -> CandidateMessageRecord:
        return self._transition(
            record_id,
            allowed_from={'pending_review'},
            status='rejected',
            reviewed_by=reviewer,
            review_reason=reason,
        )

    def mark_sent(self, record_id: str, *, outbound_message_id: str) -> CandidateMessageRecord:
        return self._transition(
            record_id,
            allowed_from={'approved'},
            status='sent',
            outbound_message_id=outbound_message_id,
            error_message=None,
        )

    def mark_failed(self, record_id: str, *, error: str) -> CandidateMessageRecord:
        return self._transition(
            record_id,
            allowed_from={'approved'},
            status='failed',
            error_message=error,
        )

    def list_candidates(self, status: str | None = None) -> list[CandidateMessageRecord]:
        if status is not None and status not in _ALLOWED_STATUSES:
            raise ValueError(f'Unsupported status filter: {status}')
        return self.store.list(status=status)

    def get_candidate(self, record_id: str) -> CandidateMessageRecord:
        return self.store.get(record_id)

    def _transition(
        self,
        record_id: str,
        *,
        allowed_from: set[str],
        status: str,
        reviewed_by: str | None = None,
        review_reason: str | None = None,
        outbound_message_id: str | None = None,
        error_message: str | None = None,
    ) -> CandidateMessageRecord:
        record = self.store.get(record_id)
        if record.status not in allowed_from:
            allowed = ', '.join(sorted(allowed_from))
            raise ValueError(f'Candidate must be in one of [{allowed}] before moving to {status}')
        updated = replace(
            record,
            status=status,
            version=record.version + 1,
            updated_at=_utcnow(),
            reviewed_by=reviewed_by if reviewed_by is not None else record.reviewed_by,
            review_reason=review_reason if review_reason is not None else record.review_reason,
            outbound_message_id=outbound_message_id if outbound_message_id is not None else record.outbound_message_id,
            error_message=error_message if error_message is not None else record.error_message,
        )
        return self.store.save(updated)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

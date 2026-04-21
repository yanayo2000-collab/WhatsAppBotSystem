from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from whatsapp_bot_system.execution_store_sqlite import ExecutionAttemptRecord, SQLiteExecutionAttemptStore
from whatsapp_bot_system.review_flow import ReviewFlowService


@dataclass
class BaseSender:
    sender_type: str

    def send(self, *, candidate_id: str, text: str, context: dict) -> str:
        raise NotImplementedError


@dataclass
class MockSender(BaseSender):
    should_fail: bool = False
    fail_reason: str = 'mock send failed'
    sent_messages: list[dict] = field(default_factory=list)

    def __init__(self, should_fail: bool = False, fail_reason: str = 'mock send failed'):
        super().__init__(sender_type='mock')
        self.should_fail = should_fail
        self.fail_reason = fail_reason
        self.sent_messages = []

    def send(self, *, candidate_id: str, text: str, context: dict) -> str:
        if self.should_fail:
            raise RuntimeError(self.fail_reason)
        outbound_message_id = f'mock-msg-{uuid4().hex[:8]}'
        self.sent_messages.append(
            {
                'candidate_id': candidate_id,
                'text': text,
                'context': context,
                'outbound_message_id': outbound_message_id,
            }
        )
        return outbound_message_id


@dataclass
class DryRunSender(BaseSender):
    def __init__(self):
        super().__init__(sender_type='dry_run')

    def send(self, *, candidate_id: str, text: str, context: dict) -> str:
        return f'dryrun-msg-{uuid4().hex[:8]}'


@dataclass
class SenderRegistry:
    default_sender: str
    senders: dict[str, BaseSender]

    def get_sender(self, name: str | None = None) -> BaseSender:
        sender_name = name or self.default_sender
        if sender_name not in self.senders:
            raise KeyError(sender_name)
        return self.senders[sender_name]


class InMemoryExecutionAttemptStore:
    def __init__(self) -> None:
        self._items: list[ExecutionAttemptRecord] = []

    def save(self, record: ExecutionAttemptRecord) -> ExecutionAttemptRecord:
        self._items = [item for item in self._items if item.id != record.id]
        self._items.append(record)
        self._items.sort(key=lambda item: item.created_at)
        return record

    def list_for_candidate(self, candidate_id: str) -> list[ExecutionAttemptRecord]:
        return [item for item in self._items if item.candidate_id == candidate_id]


class SendExecutionService:
    def __init__(
        self,
        review_service: ReviewFlowService,
        registry_or_sender,
        attempt_store=None,
    ) -> None:
        self.review_service = review_service
        if hasattr(registry_or_sender, 'get_sender'):
            self.registry = registry_or_sender
        else:
            sender = registry_or_sender
            self.registry = SenderRegistry(default_sender=sender.sender_type, senders={sender.sender_type: sender})
        self.attempt_store = attempt_store or InMemoryExecutionAttemptStore()

    def send_candidate(self, candidate_id: str, sender_name: str | None = None):
        candidate = self.review_service.get_candidate(candidate_id)
        sender = self.registry.get_sender(sender_name)
        attempt_id = f'attempt_{uuid4().hex[:12]}'
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            outbound_message_id = sender.send(
                candidate_id=candidate.id,
                text=candidate.text,
                context=candidate.context,
            )
            self.attempt_store.save(
                ExecutionAttemptRecord(
                    id=attempt_id,
                    candidate_id=candidate.id,
                    sender_type=sender.sender_type,
                    status='sent',
                    outbound_message_id=outbound_message_id,
                    error_message=None,
                    created_at=timestamp,
                )
            )
        except Exception as exc:
            self.attempt_store.save(
                ExecutionAttemptRecord(
                    id=attempt_id,
                    candidate_id=candidate.id,
                    sender_type=sender.sender_type,
                    status='failed',
                    outbound_message_id=None,
                    error_message=str(exc),
                    created_at=timestamp,
                )
            )
            return self.review_service.mark_failed(candidate.id, error=str(exc))
        return self.review_service.mark_sent(candidate.id, outbound_message_id=outbound_message_id)

    def list_attempts(self, candidate_id: str) -> list[ExecutionAttemptRecord]:
        return self.attempt_store.list_for_candidate(candidate_id)

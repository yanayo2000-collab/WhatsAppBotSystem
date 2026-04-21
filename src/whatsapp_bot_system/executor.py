from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from whatsapp_bot_system.review_flow import ReviewFlowService


@dataclass
class MockSender:
    should_fail: bool = False
    fail_reason: str = 'mock send failed'
    sent_messages: list[dict] = field(default_factory=list)

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


class SendExecutionService:
    def __init__(self, review_service: ReviewFlowService, sender: MockSender) -> None:
        self.review_service = review_service
        self.sender = sender

    def send_candidate(self, candidate_id: str):
        candidate = self.review_service.get_candidate(candidate_id)
        try:
            outbound_message_id = self.sender.send(
                candidate_id=candidate.id,
                text=candidate.text,
                context=candidate.context,
            )
        except Exception as exc:
            return self.review_service.mark_failed(candidate.id, error=str(exc))
        return self.review_service.mark_sent(candidate.id, outbound_message_id=outbound_message_id)

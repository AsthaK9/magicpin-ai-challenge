"""
Conversation handler module for multi-turn conversations.
Provides respond(state, merchant_message) -> dict per challenge brief §7.4.
"""

from __future__ import annotations
from typing import Any, Dict
from core.models import ConversationState, ReplyRequest
from core.reply_handler import ReplyHandler


def respond(state: ConversationState, merchant_message: str) -> Dict[str, Any]:
    """
    Given the conversation so far + the merchant's latest message, produce the reply.
    Returns dict with keys: action, body, cta, wait_seconds, rationale.
    """
    req = ReplyRequest(
        conversation_id=state.conversation_id,
        merchant_id=state.merchant_id,
        customer_id=state.customer_id,
        from_role="merchant",
        message=merchant_message,
        received_at="",
        turn_number=len(state.turns) + 1,
    )
    res = ReplyHandler.handle_reply(req)
    return res.model_dump(exclude_none=True)

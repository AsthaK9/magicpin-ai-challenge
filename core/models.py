"""
Pydantic data models for the magicpin Vera Merchant AI Assistant.
Defines schemas for all 5 HTTP endpoints and the 4-context framework.
"""

from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# =============================================================================
# API Request / Response Schemas
# =============================================================================

class ContextPushRequest(BaseModel):
    scope: Literal["category", "merchant", "customer", "trigger"]
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: str


class ContextPushResponse(BaseModel):
    accepted: bool
    ack_id: Optional[str] = None
    stored_at: Optional[str] = None
    reason: Optional[str] = None
    current_version: Optional[int] = None
    details: Optional[str] = None


class HealthzResponse(BaseModel):
    status: str = "ok"
    uptime_seconds: int
    contexts_loaded: Dict[str, int]


class MetadataResponse(BaseModel):
    team_name: str
    team_members: List[str]
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str


class TickRequest(BaseModel):
    now: str
    available_triggers: List[str] = Field(default_factory=list)


class Action(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    send_as: Literal["vera", "merchant_on_behalf"]
    trigger_id: str
    template_name: str
    template_params: List[str]
    body: str
    cta: str
    suppression_key: str
    rationale: str


class TickResponse(BaseModel):
    actions: List[Action]


class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int


class ReplyResponse(BaseModel):
    action: Literal["send", "wait", "end"]
    body: Optional[str] = None
    cta: Optional[str] = None
    wait_seconds: Optional[int] = None
    rationale: str


# =============================================================================
# Internal Context & Conversation Dataclasses
# =============================================================================

class ConversationTurn(BaseModel):
    from_role: str
    message: str
    timestamp: str
    action_taken: Optional[str] = None


class ConversationState(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    trigger_id: Optional[str] = None
    turns: List[ConversationTurn] = Field(default_factory=list)
    status: Literal["active", "waiting", "ended"] = "active"
    auto_reply_count: int = 0
    last_bot_body: Optional[str] = None
    waiting_until: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

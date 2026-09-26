"""
magicpin AI Challenge — Vera Merchant AI Assistant Bot
======================================================
Exposes:
  1. compose(category, merchant, trigger, customer=None) -> dict
  2. FastAPI app with:
     - GET  /v1/healthz
     - GET  /v1/metadata
     - POST /v1/context
     - POST /v1/tick
     - POST /v1/reply
     - POST /v1/teardown (optional cleanup)
"""

from __future__ import annotations
import sys
from typing import Any, Dict, Optional
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
import uvicorn

from core.models import (
    ContextPushRequest,
    HealthzResponse,
    MetadataResponse,
    ReplyRequest,
    TickRequest,
)
from core.state import store
from core.composer import MessageComposer
from core.engine import DecisionEngine
from core.reply_handler import ReplyHandler


# =============================================================================
# Standalone Compose Function (Challenge Brief §7.1)
# =============================================================================

def compose(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Given the 4 contexts, compose and return the next WhatsApp message.
    Returns dict with keys: body, cta, send_as, suppression_key, rationale.
    Deterministic, zero hallucinations, category-tailored.
    """
    return MessageComposer.compose(
        category=category,
        merchant=merchant,
        trigger=trigger,
        customer=customer,
    )


# =============================================================================
# FastAPI Application & Endpoints (Testing Brief §2)
# =============================================================================

app = FastAPI(
    title="magicpin Vera AI Assistant",
    description="Merchant engagement assistant for WhatsApp",
    version="1.0.0",
)


@app.get("/v1/healthz", response_model=HealthzResponse)
async def healthz():
    """Liveness probe reporting uptime and counts of loaded contexts."""
    return HealthzResponse(
        status="ok",
        uptime_seconds=store.uptime_seconds,
        contexts_loaded=store.get_counts(),
    )


@app.get("/v1/metadata", response_model=MetadataResponse)
async def metadata():
    """Bot identity and technical metadata."""
    return MetadataResponse(
        team_name="Astha",
        team_members=["Astha"],
        model="deterministic-context-composer",
        approach="4-context dynamic slot composition with intent-transition state router",
        contact_email="asthakumari9922@gmail.com",
        version="1.0.0",
    )


@app.post("/v1/context")
async def push_context(body: ContextPushRequest):
    """
    Ingest a category, merchant, customer, or trigger context.
    Idempotent by (context_id, version).
    Returns 409 if version is stale (<= current version).
    """
    accepted, reason_or_ack, details = store.push_context(
        scope=body.scope,
        context_id=body.context_id,
        version=body.version,
        payload=body.payload,
        delivered_at=body.delivered_at,
    )

    if not accepted:
        if reason_or_ack == "stale_version":
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "accepted": False,
                    "reason": "stale_version",
                    "current_version": details.get("current_version"),
                },
            )
        elif reason_or_ack == "invalid_scope":
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "accepted": False,
                    "reason": "invalid_scope",
                    "details": details.get("details"),
                },
            )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"accepted": False, "reason": reason_or_ack},
        )

    return {
        "accepted": True,
        "ack_id": reason_or_ack,
        "stored_at": details.get("stored_at"),
    }


@app.post("/v1/tick")
async def tick(body: TickRequest):
    """
    Periodic wake-up. Inspects active triggers and context state,
    and returns proactive messages to send.
    """
    res = DecisionEngine.process_tick(body)
    return res.model_dump()


@app.post("/v1/reply")
async def reply(body: ReplyRequest):
    """
    Receive simulated merchant or customer reply.
    Responds synchronously with next action: 'send', 'wait', or 'end'.
    """
    res = ReplyHandler.handle_reply(body)
    return res.model_dump(exclude_none=True)


@app.post("/v1/teardown")
async def teardown():
    """Optional teardown hook to reset in-memory state after test suite."""
    store.reset()
    return {"status": "ok", "message": "state reset"}


if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=8080, log_level="info")

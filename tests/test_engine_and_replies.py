"""
Unit tests for DecisionEngine and ReplyHandler:
- Multi-turn conversation handling
- Auto-reply back-off and termination
- Explicit commitment intent transition (Actioning words only, NO qualifying words)
- Hostility / Opt-out termination and merchant suppression
- Off-topic redirection
- Customer slot confirmation
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from core.models import ReplyRequest, TickRequest
from core.state import store
from core.engine import DecisionEngine
from core.reply_handler import ReplyHandler
from conversation_handlers import respond


@pytest.fixture(autouse=True)
def clean_state():
    store.reset()
    yield
    store.reset()


def test_engine_urgency_and_max_cap():
    # Setup Category
    store.push_context("category", "salons", 1, {"slug": "salons", "voice": {"tone": "warm"}}, "")

    # Setup 25 merchants and 25 triggers with varying urgencies
    for i in range(1, 26):
        mid = f"m_{i:03d}"
        tid = f"trg_{i:03d}"
        urgency = (i % 5) + 1  # 1 to 5

        store.push_context("merchant", mid, 1, {
            "merchant_id": mid,
            "category_slug": "salons",
            "identity": {"name": f"Salon {i}", "owner_first_name": f"Owner {i}"},
            "performance": {"views": 1000 + i, "calls": 10},
        }, "")

        store.push_context("trigger", tid, 1, {
            "id": tid,
            "kind": "curious_ask_due",
            "scope": "merchant",
            "merchant_id": mid,
            "payload": {"ask_template": "service_in_demand"},
            "urgency": urgency,
            "suppression_key": f"supp_{tid}",
        }, "")

    all_trgs = [f"trg_{i:03d}" for i in range(1, 26)]
    req = TickRequest(now="2026-04-26T10:00:00Z", available_triggers=all_trgs)
    res = DecisionEngine.process_tick(req)

    # Max cap is 20
    assert len(res.actions) == 20

    # Ensure actions are sorted by urgency descending
    # The first action should have urgency 5
    first_trg = store.get_context("trigger", res.actions[0].trigger_id)
    assert first_trg["urgency"] == 5


def test_reply_auto_reply_turn_progression():
    # Turn 1 of auto-reply: returns wait
    req1 = ReplyRequest(
        conversation_id="conv_auto_test",
        merchant_id="m_001",
        from_role="merchant",
        message="Thank you for contacting us! Our team will respond shortly.",
        received_at="2026-04-26T10:00:00Z",
        turn_number=2,
    )
    res1 = ReplyHandler.handle_reply(req1)
    assert res1.action == "wait"
    assert res1.wait_seconds == 14400

    # Turn 2 of auto-reply: returns end
    req2 = ReplyRequest(
        conversation_id="conv_auto_test",
        merchant_id="m_001",
        from_role="merchant",
        message="Thank you for contacting us! Our team will respond shortly.",
        received_at="2026-04-26T10:05:00Z",
        turn_number=3,
    )
    res2 = ReplyHandler.handle_reply(req2)
    assert res2.action == "end"


def test_reply_intent_transition_actioning_words():
    req = ReplyRequest(
        conversation_id="conv_intent",
        merchant_id="m_002",
        from_role="merchant",
        message="Ok lets do it. Whats next?",
        received_at="2026-04-26T10:00:00Z",
        turn_number=2,
    )
    res = ReplyHandler.handle_reply(req)
    assert res.action == "send"
    assert res.body is not None

    body_lower = res.body.lower()
    # Required actioning words
    actioning = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
    assert any(w in body_lower for w in actioning)

    # Disallowed qualifying words
    qualifying = ["would you", "do you", "can you tell", "what if", "how about"]
    assert not any(w in body_lower for w in qualifying)


def test_reply_hostile_terminates_and_suppresses():
    req = ReplyRequest(
        conversation_id="conv_hostile",
        merchant_id="m_003_hostile",
        from_role="merchant",
        message="Stop messaging me. This is useless spam.",
        received_at="2026-04-26T10:00:00Z",
        turn_number=2,
    )
    res = ReplyHandler.handle_reply(req)
    assert res.action == "end"
    assert store.is_merchant_suppressed("m_003_hostile")

    # In subsequent tick, this merchant's triggers must be skipped
    store.push_context("category", "salons", 1, {"slug": "salons"}, "")
    store.push_context("merchant", "m_003_hostile", 1, {
        "merchant_id": "m_003_hostile",
        "category_slug": "salons",
        "identity": {"name": "Hostile Salon"},
    }, "")
    store.push_context("trigger", "trg_hostile", 1, {
        "id": "trg_hostile",
        "kind": "curious_ask_due",
        "merchant_id": "m_003_hostile",
        "payload": {},
    }, "")

    tick_res = DecisionEngine.process_tick(TickRequest(now="2026-04-26T10:10:00Z", available_triggers=["trg_hostile"]))
    assert tick_res.actions == []


def test_reply_off_topic_polite_redirect():
    req = ReplyRequest(
        conversation_id="conv_gst",
        merchant_id="m_004",
        from_role="merchant",
        message="Can you also help me file my GST and income tax?",
        received_at="2026-04-26T10:00:00Z",
        turn_number=2,
    )
    res = ReplyHandler.handle_reply(req)
    assert res.action == "send"
    assert "gst" in res.body.lower()
    assert "ca" in res.body.lower() or "accountant" in res.body.lower()
    assert res.cta == "binary_confirm_cancel"


def test_conversation_handlers_respond_wrapper():
    conv = store.get_or_create_conversation("conv_wrap", merchant_id="m_005")
    reply_dict = respond(conv, "Ok let's do it, proceed.")
    assert reply_dict["action"] == "send"
    assert "draft" in reply_dict["body"].lower() or "proceed" in reply_dict["body"].lower()

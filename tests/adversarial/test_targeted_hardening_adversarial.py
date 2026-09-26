"""
Targeted Adversarial Test Suite verifying hardened capabilities:
- non-dental regulation_change
- unseen trigger
- missing merchant_id
- duplicate same-kind triggers
- multiple reply turns
- hostile reply
- off-topic reply (expanded categories + non-misclassification)
- fresh metric
- fresh customer scope
- determinism verification
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from core.models import ReplyRequest, TickRequest
from core.state import store
from core.engine import DecisionEngine
from core.composer import MessageComposer
from core.reply_handler import ReplyHandler


@pytest.fixture(autouse=True)
def clean_state():
    store.reset()
    yield
    store.reset()


def test_adversarial_non_dental_regulation_change():
    """Verify regulation_change for non-dental category derives purely from payload/context."""
    cat = {
        "slug": "restaurants",
        "voice": {"tone": "operator"},
        "digest": [{
            "id": "d_fssai_hygiene",
            "title": "FSSAI Food Safety Audit Schedule",
            "source": "FSSAI Gazette Notification 2026-Q2",
            "deadline": "2026-08-31",
            "summary": "Mandatory hygiene rating audits for commercial kitchens with over 50 daily covers.",
        }]
    }
    merchant = {
        "merchant_id": "m_rest_01",
        "category_slug": "restaurants",
        "identity": {"name": "Spice Route Kitchen", "owner_first_name": "Sanjay"},
    }
    trigger = {
        "id": "trg_reg_fssai",
        "scope": "merchant",
        "kind": "regulation_change",
        "payload": {
            "top_item_id": "d_fssai_hygiene",
            "deadline_iso": "2026-08-31",
        },
    }

    res = MessageComposer.compose(cat, merchant, trigger)
    assert res is not None
    body = res["body"]
    # Must use context facts
    assert "2026-08-31" in body
    assert "FSSAI" in body or "Food Safety" in body or "Spice Route" in body
    assert "Sanjay" in body
    # Must NOT contain dental terms
    for taboo in ["dental", "dci", "radiograph", "iopa", "msv", "teeth", "clinic"]:
        assert taboo not in body.lower(), f"Leaked dental term: {taboo}"


def test_adversarial_unseen_trigger():
    """Unseen trigger kind handled gracefully without fabricating statistics or URLs."""
    cat = {"slug": "gyms", "voice": {"tone": "coaching"}}
    merchant = {
        "merchant_id": "m_iron_gym",
        "category_slug": "gyms",
        "identity": {"name": "Iron Gym", "owner_first_name": "Vikram"},
        "performance": {"views": 1500, "calls": 45, "ctr": 0.03},
    }
    trigger = {
        "id": "trg_energy_grant",
        "scope": "merchant",
        "kind": "clean_energy_rebate",
        "payload": {
            "topic": "rooftop solar incentive",
            "metric": "views",
            "delta_pct": 0.15,
        },
    }

    res = MessageComposer.compose(cat, merchant, trigger)
    assert res is not None
    body = res["body"]
    assert "Vikram" in body
    assert "Iron Gym" in body
    assert "rooftop solar incentive" in body
    assert "+15%" in body or "views is up" in body.lower()
    # Must never hallucinate URLs
    assert "http" not in body


def test_adversarial_missing_merchant_id():
    """DecisionEngine and composer must not crash if merchant payload omits merchant_id."""
    store.push_context("category", "salons", 1, {"slug": "salons"}, "")
    # Payload has NO 'merchant_id' field inside the dict
    store.push_context("merchant", "m_sparse_01", 1, {
        "category_slug": "salons",
        "identity": {"name": "Velvet Salon", "owner_first_name": "Pooja"},
    }, "")
    store.push_context("trigger", "trg_sparse_01", 1, {
        "id": "trg_sparse_01",
        "kind": "curious_ask_due",
        "scope": "merchant",
        "merchant_id": "m_sparse_01",
        "urgency": 3,
        "payload": {},
    }, "")

    tick_res = DecisionEngine.process_tick(TickRequest(
        now="2026-04-26T10:00:00Z",
        available_triggers=["trg_sparse_01"]
    ))
    assert len(tick_res.actions) == 1
    action = tick_res.actions[0]
    assert action.merchant_id == "m_sparse_01"
    assert "Velvet Salon" in action.body or "Pooja" in action.body


def test_adversarial_duplicate_same_kind_triggers_different_conv_ids():
    """Two separate triggers of the same kind for the same merchant must NOT share conversation_id."""
    cat = {"slug": "salons"}
    merchant = {
        "merchant_id": "m_salon_dup",
        "category_slug": "salons",
        "identity": {"name": "Bliss Salon"},
    }
    trg1 = {
        "id": "trg_dip_views_01",
        "kind": "perf_dip",
        "scope": "merchant",
        "merchant_id": "m_salon_dup",
        "payload": {"metric": "views", "delta_pct": -0.2},
    }
    trg2 = {
        "id": "trg_dip_calls_02",
        "kind": "perf_dip",
        "scope": "merchant",
        "merchant_id": "m_salon_dup",
        "payload": {"metric": "calls", "delta_pct": -0.35},
    }

    res1 = MessageComposer.compose(cat, merchant, trg1)
    res2 = MessageComposer.compose(cat, merchant, trg2)

    assert res1["conversation_id"] != res2["conversation_id"]
    assert "trg_dip_views_01" in res1["conversation_id"] or "01" in res1["conversation_id"]
    assert "trg_dip_calls_02" in res2["conversation_id"] or "02" in res2["conversation_id"]


def test_adversarial_multiple_reply_turns_progression():
    """Sequential intent replies across turns 2, 3, 4 must NOT repeat identical verbatim text."""
    actioning = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
    qualifying = ["would you", "do you", "can you tell", "what if", "how about"]

    bodies = []
    for turn in [2, 3, 4]:
        req = ReplyRequest(
            conversation_id="conv_progression_test",
            merchant_id="m_prog_01",
            from_role="merchant",
            message="Let's do it, proceed.",
            received_at="2026-04-26T12:00:00Z",
            turn_number=turn,
        )
        res = ReplyHandler.handle_reply(req)
        assert res.action == "send"
        assert res.body is not None

        body_lower = res.body.lower()
        # Must strictly obey action mode rules
        assert any(w in body_lower for w in actioning), f"Turn {turn} missing actioning word"
        assert not any(w in body_lower for w in qualifying), f"Turn {turn} contains qualifying word"

        bodies.append(res.body)

    # All three turns must have different response bodies
    assert len(set(bodies)) == 3, f"Expected 3 distinct bodies across turns, got: {bodies}"


def test_adversarial_hostile_reply_suppression():
    """Hostile reply triggers immediate conversation end and merchant suppression."""
    req = ReplyRequest(
        conversation_id="conv_hostile_test",
        merchant_id="m_hostile_99",
        from_role="merchant",
        message="Stop messaging me! This is unwanted harassment.",
        received_at="2026-04-26T12:00:00Z",
        turn_number=2,
    )
    res = ReplyHandler.handle_reply(req)
    assert res.action == "end"
    assert store.is_merchant_suppressed("m_hostile_99")


def test_adversarial_off_topic_reply_handling():
    """Off-topic queries receive polite redirections, while legitimate questions remain on topic."""
    # 1. Tax inquiry -> CA redirect
    req_tax = ReplyRequest(
        conversation_id="conv_ot_tax",
        merchant_id="m_ot_01",
        from_role="merchant",
        message="Can you help me file my GST and ITR?",
        received_at="2026-04-26T12:00:00Z",
        turn_number=2,
    )
    res_tax = ReplyHandler.handle_reply(req_tax)
    assert res_tax.action == "send"
    assert "gst" in res_tax.body.lower()
    assert "ca" in res_tax.body.lower() or "accountant" in res_tax.body.lower()

    # 2. Loan inquiry -> Finance redirect
    req_loan = ReplyRequest(
        conversation_id="conv_ot_loan",
        merchant_id="m_ot_02",
        from_role="merchant",
        message="I need a business loan of 5 lakhs",
        received_at="2026-04-26T12:00:00Z",
        turn_number=2,
    )
    res_loan = ReplyHandler.handle_reply(req_loan)
    assert res_loan.action == "send"
    assert "loan" in res_loan.body.lower() or "financial" in res_loan.body.lower()

    # 3. Legitimate merchant query -> NOT classified as off-topic!
    req_legit = ReplyRequest(
        conversation_id="conv_legit",
        merchant_id="m_ot_03",
        from_role="merchant",
        message="Can we change the discount to 20% on the cleaning offer?",
        received_at="2026-04-26T12:00:00Z",
        turn_number=2,
    )
    res_legit = ReplyHandler.handle_reply(req_legit)
    assert res_legit.action == "send"
    # Should advance to next step, NOT mention GST or CA
    assert "gst" not in res_legit.body.lower()
    assert "accountant" not in res_legit.body.lower()
    assert "loan" not in res_legit.body.lower()


def test_adversarial_fresh_metric():
    """Context update with fresh metrics is reflected immediately in composed output."""
    cat = {"slug": "gyms"}
    m = {
        "merchant_id": "m_fresh_perf",
        "category_slug": "gyms",
        "identity": {"name": "Titan Gym", "owner_first_name": "Rohan"},
        "performance": {"views": 9400, "calls": 120},
    }
    trg = {
        "id": "trg_dormant_fresh",
        "kind": "dormant_with_vera",
        "scope": "merchant",
        "payload": {"days_since_last_merchant_message": 25},
    }

    res = MessageComposer.compose(cat, m, trg)
    assert "9,400 views" in res["body"]
    assert "Rohan" in res["body"]


def test_adversarial_fresh_customer_scope():
    """Fresh customer-scoped trigger creates merchant_on_behalf message addressing customer."""
    cat = {"slug": "salons", "voice": {"tone": "warm"}}
    merchant = {
        "merchant_id": "m_salon_fresh",
        "category_slug": "salons",
        "identity": {"name": "Luxe Salon", "owner_first_name": "Sunita"},
    }
    customer = {
        "customer_id": "c_fresh_99",
        "identity": {"name": "Deepika"},
        "relationship": {"last_visit": "2026-01-10"},
    }
    trigger = {
        "id": "trg_lapsed_fresh",
        "kind": "customer_lapsed_soft",
        "scope": "customer",
        "customer_id": "c_fresh_99",
        "merchant_id": "m_salon_fresh",
        "payload": {"last_service": "Hair Spa", "days_since_last_visit": 90},
    }

    res = MessageComposer.compose(cat, merchant, trigger, customer)
    assert res["send_as"] == "merchant_on_behalf"
    assert "Deepika" in res["body"]
    assert "Luxe Salon" in res["body"] or "Sunita" in res["body"]
    assert res["customer_id"] == "c_fresh_99"


def test_adversarial_determinism():
    """Running identical composition 5 times yields exact identical output every time."""
    cat = {"slug": "pharmacies", "voice": {"tone": "precise"}}
    merchant = {
        "merchant_id": "m_det_01",
        "category_slug": "pharmacies",
        "identity": {"name": "Health First Pharmacy", "owner_first_name": "Manoj"},
        "performance": {"views": 3200, "calls": 60},
    }
    trigger = {
        "id": "trg_det_01",
        "kind": "category_seasonal",
        "scope": "merchant",
        "payload": {"season": "monsoon", "trends": ["antifungal_demand_+40"]},
    }

    first_res = MessageComposer.compose(cat, merchant, trigger)
    for _ in range(4):
        subsequent_res = MessageComposer.compose(cat, merchant, trigger)
        assert subsequent_res == first_res, "Non-deterministic output detected!"

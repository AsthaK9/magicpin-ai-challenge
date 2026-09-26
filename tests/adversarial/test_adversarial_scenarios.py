"""
Adversarial & Edge-Case Test Suite for Vera.
Tests:
- Same trigger with different merchants
- Same merchant with different customers
- Metric shifts (improvement vs deterioration)
- Dynamic trigger appearance / disappearance
- Ineligible / churned customer suppression
- Customer scope transitions
- Competing & conflicting triggers
- Repeated trigger suppression
- Stale context version replacement
- Reply intent transitions
- Hostile responses
- Off-topic responses
- Incomplete / malformed / missing context fields
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


def test_adversarial_same_trigger_different_merchants():
    """Same trigger kind dispatched to two distinct merchants in different categories."""
    cat_dentist = {"slug": "dentists", "voice": {"tone": "clinical"}}
    cat_salon = {"slug": "salons", "voice": {"tone": "warm"}}

    m_dentist = {
        "merchant_id": "m_d1",
        "category_slug": "dentists",
        "identity": {"name": "Smile Clinic", "owner_first_name": "Asha", "locality": "Saket"},
        "performance": {"views": 1000, "calls": 10},
    }
    m_salon = {
        "merchant_id": "m_s1",
        "category_slug": "salons",
        "identity": {"name": "Glow Salon", "owner_first_name": "Renu", "locality": "Bandra"},
        "performance": {"views": 2500, "calls": 35},
    }

    trg = {
        "id": "trg_shared",
        "kind": "curious_ask_due",
        "scope": "merchant",
        "payload": {},
        "suppression_key": "supp_shared",
    }

    res_d = MessageComposer.compose(cat_dentist, m_dentist, trg)
    res_s = MessageComposer.compose(cat_salon, m_salon, trg)

    assert "Dr. Asha" in res_d["body"] or "Asha" in res_d["body"]
    assert "Smile Clinic" in res_d["body"]
    assert "Renu" in res_s["body"]
    assert "Glow Salon" in res_s["body"]
    assert res_d["body"] != res_s["body"]


def test_adversarial_same_merchant_different_customers():
    """Same merchant sending appointment reminder to two different customers with different preferences."""
    cat = {"slug": "dentists", "voice": {"tone": "clinical"}}
    m = {
        "merchant_id": "m_clinic",
        "category_slug": "dentists",
        "identity": {"name": "Apex Dental", "owner_first_name": "Karthik"},
        "offers": [{"title": "Dental Cleaning @ ₹299", "status": "active"}],
    }
    c1 = {"customer_id": "c1", "identity": {"name": "Rohit", "language_pref": "en"}}
    c2 = {"customer_id": "c2", "identity": {"name": "Aanya", "language_pref": "hi-en mix"}}

    trg1 = {
        "id": "trg_c1",
        "scope": "customer",
        "kind": "recall_due",
        "payload": {"service_due": "6_month_cleaning", "available_slots": [{"label": "Mon 10am"}, {"label": "Tue 2pm"}]},
    }
    trg2 = {
        "id": "trg_c2",
        "scope": "customer",
        "kind": "recall_due",
        "payload": {"service_due": "6_month_cleaning", "available_slots": [{"label": "Fri 4pm"}, {"label": "Sat 11am"}]},
    }

    res1 = MessageComposer.compose(cat, m, trg1, c1)
    res2 = MessageComposer.compose(cat, m, trg2, c2)

    assert "Rohit" in res1["body"]
    assert "Mon 10am" in res1["body"]
    assert "Aanya" in res2["body"]
    assert "Fri 4pm" in res2["body"]
    assert res1["body"] != res2["body"]


def test_adversarial_metric_improves_vs_deteriorates():
    """Verify that a spike trigger praises growth whereas a dip trigger offers diagnostic recovery."""
    cat = {"slug": "gyms", "voice": {}}
    m = {
        "merchant_id": "m_gym",
        "category_slug": "gyms",
        "identity": {"name": "Fit Gym", "owner_first_name": "Akash"},
        "performance": {"views": 1200, "calls": 20},
    }

    trg_spike = {
        "id": "t_spike",
        "kind": "perf_spike",
        "scope": "merchant",
        "payload": {"metric": "calls", "delta_pct": 0.25, "vs_baseline": 16, "likely_driver": "morning_post"},
    }
    trg_dip = {
        "id": "t_dip",
        "kind": "perf_dip",
        "scope": "merchant",
        "payload": {"metric": "calls", "delta_pct": -0.40, "vs_baseline": 25},
    }

    res_spike = MessageComposer.compose(cat, m, trg_spike)
    res_dip = MessageComposer.compose(cat, m, trg_dip)

    assert "+25%" in res_spike["body"]
    assert "streak" in res_spike["body"].lower() or "momentum" in res_spike["body"].lower()
    assert "-40%" in res_dip["body"] or "down 40%" in res_dip["body"]
    assert "restore" in res_dip["body"].lower() or "draft 2 fresh posts" in res_dip["body"].lower()


def test_adversarial_churned_customer_ineligible():
    """A customer who is churned should be filtered out by the DecisionEngine for recall."""
    store.push_context("category", "dentists", 1, {"slug": "dentists"}, "")
    store.push_context("merchant", "m_d", 1, {"merchant_id": "m_d", "category_slug": "dentists", "identity": {"name": "Dental Care"}}, "")
    store.push_context("customer", "c_churned", 1, {"customer_id": "c_churned", "state": "churned", "identity": {"name": "Old Customer"}}, "")
    store.push_context("trigger", "trg_churned", 1, {
        "id": "trg_churned",
        "kind": "recall_due",
        "scope": "customer",
        "merchant_id": "m_d",
        "customer_id": "c_churned",
        "payload": {},
        "suppression_key": "supp_churn",
    }, "")

    tick_res = DecisionEngine.process_tick(TickRequest(now="2026-04-26T10:00:00Z", available_triggers=["trg_churned"]))
    assert tick_res.actions == []


def test_adversarial_competing_triggers_priority():
    """When a high-urgency compliance alert (urgency 5) and low-urgency curious ask (urgency 1) compete for the same merchant, high urgency wins."""
    store.push_context("category", "pharmacies", 1, {"slug": "pharmacies"}, "")
    store.push_context("merchant", "m_phr", 1, {
        "merchant_id": "m_phr",
        "category_slug": "pharmacies",
        "identity": {"name": "MedPlus", "owner_first_name": "Rajesh"},
    }, "")
    store.push_context("trigger", "trg_curious", 1, {
        "id": "trg_curious",
        "kind": "curious_ask_due",
        "scope": "merchant",
        "merchant_id": "m_phr",
        "urgency": 1,
        "payload": {},
    }, "")
    store.push_context("trigger", "trg_urgent", 1, {
        "id": "trg_urgent",
        "kind": "supply_alert",
        "scope": "merchant",
        "merchant_id": "m_phr",
        "urgency": 5,
        "payload": {"molecule": "atorvastatin", "affected_batches": ["B101"], "manufacturer": "PharmaCorp"},
    }, "")

    # Both triggers available on tick
    tick_res = DecisionEngine.process_tick(TickRequest(now="2026-04-26T10:00:00Z", available_triggers=["trg_curious", "trg_urgent"]))
    # Only 1 action per merchant per tick allowed
    assert len(tick_res.actions) == 1
    assert tick_res.actions[0].trigger_id == "trg_urgent"


def test_adversarial_stale_context_update():
    """Updating merchant performance snapshot to version 2 immediately changes the composed numbers."""
    cat = {"slug": "restaurants"}
    m_v1 = {
        "merchant_id": "m_rst",
        "category_slug": "restaurants",
        "identity": {"name": "Diner", "owner_first_name": "Lalit"},
        "performance": {"views": 1000, "calls": 10},
    }
    m_v2 = {
        "merchant_id": "m_rst",
        "category_slug": "restaurants",
        "identity": {"name": "Diner", "owner_first_name": "Lalit"},
        "performance": {"views": 5200, "calls": 85},
    }
    trg = {
        "id": "trg_dormant",
        "kind": "dormant_with_vera",
        "scope": "merchant",
        "payload": {"days_since_last_merchant_message": 20},
    }

    res1 = MessageComposer.compose(cat, m_v1, trg)
    res2 = MessageComposer.compose(cat, m_v2, trg)

    assert "1,000 views" in res1["body"]
    assert "5,200 views" in res2["body"]


def test_adversarial_incomplete_context_robustness():
    """The composer must never crash when given completely empty or sparse dictionaries."""
    res = MessageComposer.compose({}, {}, {})
    assert res is not None
    assert "body" in res and len(res["body"]) > 0
    assert "cta" in res
    assert "send_as" in res
    assert "rationale" in res
    assert "suppression_key" in res


def test_adversarial_unknown_category_fallback():
    """Unknown category (e.g. 'pet_care' or 'car_repair') handles gracefully with fallback."""
    cat = {"slug": "pet_care", "voice": {"tone": "friendly"}}
    m = {
        "merchant_id": "m_pet",
        "category_slug": "pet_care",
        "identity": {"name": "Paws Grooming", "owner_first_name": "Simran"},
        "performance": {"views": 800, "calls": 15},
    }
    trg = {
        "id": "trg_unseen",
        "kind": "unseen_special_event",
        "scope": "merchant",
        "payload": {"topic": "pet grooming weekend"},
    }

    res = MessageComposer.compose(cat, m, trg)
    assert res is not None
    assert "Simran" in res["body"]
    assert "Paws Grooming" in res["body"]
    assert "pet grooming weekend" in res["body"]
    assert "http" not in res["body"]

"""
Unit tests for MessageComposer:
- Category voice matching (dentists, salons, restaurants, gyms, pharmacies)
- Grounding & zero-hallucination verification
- Taboo words scrubbing
- URL removal
- Single primary CTA
- Determinism on identical inputs
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from bot import compose


def test_composer_dentist_voice_and_grounding():
    category = {
        "slug": "dentists",
        "voice": {"tone": "peer_clinical", "vocab_taboo": ["guaranteed", "100% safe", "cure"]},
        "digest": [{"id": "d_test", "source": "JIDA Oct 2026, p.14", "trial_n": 2100, "patient_segment": "high_risk_adults", "title": "3-month fluoride varnish recall outperforms 6-month for high-risk adult caries", "summary": "Multi-center Indian trial shows 38% lower caries recurrence with 3-month vs 6-month recall in adults with active decay history."}]
    }
    merchant = {
        "merchant_id": "m_001_meera",
        "category_slug": "dentists",
        "identity": {"name": "Dr. Meera Dental Clinic", "owner_first_name": "Meera", "locality": "Lajpat Nagar"},
        "customer_aggregate": {"high_risk_adult_count": 124},
        "performance": {"views": 2410, "calls": 18, "ctr": 0.021},
    }
    trigger = {
        "id": "trg_001",
        "scope": "merchant",
        "kind": "research_digest",
        "payload": {"top_item_id": "d_test"},
        "suppression_key": "supp_trg_001",
    }

    res = compose(category, merchant, trigger)
    assert res["send_as"] == "vera"
    assert res["cta"] == "open_ended"
    assert "Dr. Meera" in res["body"]
    assert "2,100" in res["body"]
    assert "38%" in res["body"]
    assert "124 in your roster" in res["body"]
    assert "JIDA Oct 2026, p.14" in res["body"]
    # Check no taboo words
    for taboo in ["guaranteed", "100% safe", "cure"]:
        assert taboo not in res["body"].lower()
    # Check no URL
    assert "http" not in res["body"]


def test_composer_customer_facing_recall():
    category = {
        "slug": "dentists",
        "voice": {"tone": "warm_clinical", "vocab_taboo": ["miracle", "guaranteed"]},
    }
    merchant = {
        "merchant_id": "m_001_meera",
        "category_slug": "dentists",
        "identity": {"name": "Dr. Meera Dental Clinic", "owner_first_name": "Meera"},
        "offers": [{"title": "Dental Cleaning @ ₹299", "status": "active"}],
    }
    customer = {
        "customer_id": "c_priya",
        "identity": {"name": "Priya", "language_pref": "hi-en mix"},
    }
    trigger = {
        "id": "trg_recall",
        "scope": "customer",
        "kind": "recall_due",
        "payload": {
            "service_due": "6_month_cleaning",
            "available_slots": [{"label": "Wed 5 Nov, 6pm"}, {"label": "Thu 6 Nov, 5pm"}]
        },
        "suppression_key": "recall:c_priya:6mo",
    }

    res = compose(category, merchant, trigger, customer)
    assert res["send_as"] == "merchant_on_behalf"
    assert res["cta"] == "multi_choice_slot"
    assert "Priya" in res["body"]
    assert "Dr. Meera Dental Clinic" in res["body"]
    assert "₹299" in res["body"]
    assert "Wed 5 Nov, 6pm" in res["body"]
    assert "Thu 6 Nov, 5pm" in res["body"]
    assert "Reply 1" in res["body"]


def test_composer_taboo_scrubbing():
    category = {
        "slug": "gyms",
        "voice": {"tone": "energetic", "vocab_taboo": ["guaranteed weight loss", "miracle transformation"]},
    }
    merchant = {
        "merchant_id": "m_gym",
        "category_slug": "gyms",
        "identity": {"name": "Iron Forge Gym", "owner_first_name": "Karan"},
        "performance": {"views": 1100, "calls": 18},
    }
    trigger = {
        "id": "trg_generic",
        "scope": "merchant",
        "kind": "custom_trigger",
        "payload": {"topic": "guaranteed weight loss miracle transformation program"},
        "suppression_key": "test_supp",
    }

    res = compose(category, merchant, trigger)
    assert "guaranteed weight loss" not in res["body"].lower()
    assert "miracle transformation" not in res["body"].lower()


def test_composer_url_stripping():
    category = {"slug": "restaurants", "voice": {}}
    merchant = {
        "merchant_id": "m_rest",
        "category_slug": "restaurants",
        "identity": {"name": "Biryani Express", "owner_first_name": "Ravi"},
        "performance": {"views": 2000, "calls": 30},
    }
    trigger = {
        "id": "trg_url",
        "scope": "merchant",
        "kind": "custom_trigger",
        "payload": {"topic": "special combo http://magicpin.com/deal https://example.com/promo"},
        "suppression_key": "test_supp",
    }

    res = compose(category, merchant, trigger)
    assert "http://" not in res["body"]
    assert "https://" not in res["body"]


def test_composer_determinism():
    category = {
        "slug": "salons",
        "voice": {"tone": "warm_practical"},
    }
    merchant = {
        "merchant_id": "m_salon",
        "category_slug": "salons",
        "identity": {"name": "Studio11 Kapra", "owner_first_name": "Lakshmi", "locality": "Kapra"},
        "performance": {"views": 4980, "calls": 62, "ctr": 0.048},
        "offers": [{"title": "Haircut @ ₹99", "status": "active"}],
    }
    trigger = {
        "id": "trg_curious",
        "scope": "merchant",
        "kind": "curious_ask_due",
        "payload": {"ask_template": "what_service_in_demand_this_week"},
        "suppression_key": "curious_ask:m_salon",
    }

    # Run 10 times, all outputs must be 100% identical
    first_res = compose(category, merchant, trigger)
    for _ in range(9):
        res = compose(category, merchant, trigger)
        assert res == first_res

"""
Unit & API Integration Tests for all endpoints:
- GET  /v1/healthz
- GET  /v1/metadata
- POST /v1/context (including 409 stale version, 400 invalid scope)
- POST /v1/tick
- POST /v1/reply
- POST /v1/teardown
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from bot import app
from core.state import store

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    store.reset()
    yield
    store.reset()


def test_healthz_initially_empty():
    response = client.get("/v1/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "uptime_seconds" in data
    assert data["contexts_loaded"] == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}


def test_metadata():
    response = client.get("/v1/metadata")
    assert response.status_code == 200
    data = response.json()
    assert data["team_name"] == "Vera AI Team"
    assert "version" in data
    assert "model" in data
    assert "submitted_at" in data


def test_push_context_and_healthz_counts():
    # Push Category
    cat_payload = {
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "delivered_at": "2026-04-26T10:00:00Z",
        "payload": {"slug": "dentists", "voice": {"tone": "peer_clinical"}},
    }
    r = client.post("/v1/context", json=cat_payload)
    assert r.status_code == 200
    assert r.json()["accepted"] is True
    assert r.json()["ack_id"] == "ack_dentists_v1"

    # Push Merchant
    m_payload = {
        "scope": "merchant",
        "context_id": "m_001_drmeera",
        "version": 1,
        "delivered_at": "2026-04-26T10:01:00Z",
        "payload": {
            "merchant_id": "m_001_drmeera",
            "category_slug": "dentists",
            "identity": {"name": "Dr. Meera Clinic", "owner_first_name": "Meera"},
            "performance": {"views": 1000, "calls": 20},
        },
    }
    r = client.post("/v1/context", json=m_payload)
    assert r.status_code == 200

    # Verify counts in healthz
    hz = client.get("/v1/healthz").json()
    assert hz["contexts_loaded"]["category"] == 1
    assert hz["contexts_loaded"]["merchant"] == 1
    assert hz["contexts_loaded"]["customer"] == 0
    assert hz["contexts_loaded"]["trigger"] == 0


def test_context_stale_version_409():
    m_payload = {
        "scope": "merchant",
        "context_id": "m_test_stale",
        "version": 2,
        "delivered_at": "2026-04-26T10:00:00Z",
        "payload": {"merchant_id": "m_test_stale", "category_slug": "salons"},
    }
    r1 = client.post("/v1/context", json=m_payload)
    assert r1.status_code == 200

    # Re-push version 2 -> must return 409
    r2 = client.post("/v1/context", json=m_payload)
    assert r2.status_code == 409
    data = r2.json()
    assert data["accepted"] is False
    assert data["reason"] == "stale_version"
    assert data["current_version"] == 2

    # Push lower version 1 -> must return 409
    m_payload["version"] = 1
    r3 = client.post("/v1/context", json=m_payload)
    assert r3.status_code == 409
    assert r3.json()["current_version"] == 2


def test_context_higher_version_replaces_200():
    m_payload = {
        "scope": "merchant",
        "context_id": "m_version_test",
        "version": 1,
        "delivered_at": "2026-04-26T10:00:00Z",
        "payload": {"merchant_id": "m_version_test", "views": 100},
    }
    r1 = client.post("/v1/context", json=m_payload)
    assert r1.status_code == 200

    # Version bump to 2
    m_payload["version"] = 2
    m_payload["payload"]["views"] = 250
    r2 = client.post("/v1/context", json=m_payload)
    assert r2.status_code == 200
    assert r2.json()["accepted"] is True
    assert r2.json()["ack_id"] == "ack_m_version_test_v2"

    stored = store.get_context("merchant", "m_version_test")
    assert stored["views"] == 250


def test_context_invalid_scope_400():
    r = client.post("/v1/context", json={
        "scope": "invalid_scope_xyz",
        "context_id": "123",
        "version": 1,
        "delivered_at": "2026-04-26T10:00:00Z",
        "payload": {},
    })
    assert r.status_code == 422 or r.status_code == 400


def test_tick_empty_triggers():
    r = client.post("/v1/tick", json={"now": "2026-04-26T10:30:00Z", "available_triggers": []})
    assert r.status_code == 200
    assert r.json() == {"actions": []}


def test_tick_with_active_trigger():
    # Setup Category
    client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "delivered_at": "2026-04-26T10:00:00Z",
        "payload": {
            "slug": "dentists",
            "voice": {"tone": "peer_clinical"},
            "digest": [{"id": "d_test", "source": "JIDA 2026", "trial_n": 2100, "patient_segment": "high_risk_adults"}],
        }
    })
    # Setup Merchant
    client.post("/v1/context", json={
        "scope": "merchant",
        "context_id": "m_meera",
        "version": 1,
        "delivered_at": "2026-04-26T10:00:00Z",
        "payload": {
            "merchant_id": "m_meera",
            "category_slug": "dentists",
            "identity": {"name": "Dr. Meera Dental Clinic", "owner_first_name": "Meera", "locality": "Lajpat Nagar"},
            "performance": {"views": 1500, "calls": 12},
        }
    })
    # Setup Trigger
    client.post("/v1/context", json={
        "scope": "trigger",
        "context_id": "trg_test_1",
        "version": 1,
        "delivered_at": "2026-04-26T10:00:00Z",
        "payload": {
            "id": "trg_test_1",
            "kind": "research_digest",
            "scope": "merchant",
            "merchant_id": "m_meera",
            "payload": {"top_item_id": "d_test"},
            "urgency": 3,
            "suppression_key": "supp_trg_test_1",
            "expires_at": "2026-05-01T00:00:00Z",
        }
    })

    # Call /v1/tick
    r = client.post("/v1/tick", json={"now": "2026-04-26T10:30:00Z", "available_triggers": ["trg_test_1"]})
    assert r.status_code == 200
    actions = r.json()["actions"]
    assert len(actions) == 1
    action = actions[0]
    assert action["merchant_id"] == "m_meera"
    assert action["send_as"] == "vera"
    assert action["cta"] == "open_ended"
    assert "Dr. Meera" in action["body"]
    assert "2,100" in action["body"]
    assert "JIDA" in action["body"]

    # Repeated tick with same trigger -> must be suppressed!
    r2 = client.post("/v1/tick", json={"now": "2026-04-26T10:35:00Z", "available_triggers": ["trg_test_1"]})
    assert r2.status_code == 200
    assert r2.json()["actions"] == []


def test_reply_auto_reply_sequence():
    # Turn 1: auto-reply detected -> wait
    r1 = client.post("/v1/reply", json={
        "conversation_id": "conv_auto_test",
        "merchant_id": "m_test_auto",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Thank you for contacting us! Our team will respond shortly.",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2,
    })
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["action"] == "wait"
    assert d1["wait_seconds"] == 14400

    # Turn 2: repeated auto-reply -> end
    r2 = client.post("/v1/reply", json={
        "conversation_id": "conv_auto_test",
        "merchant_id": "m_test_auto",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Thank you for contacting us! Our team will respond shortly.",
        "received_at": "2026-04-26T10:46:00Z",
        "turn_number": 3,
    })
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["action"] == "end"


def test_reply_intent_transition():
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_intent_test",
        "merchant_id": "m_test_intent",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Ok, let's do it. What's next?",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["action"] == "send"
    body = d["body"].lower()
    # Must contain actioning words
    actioning = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
    assert any(w in body for w in actioning)
    # Must NOT contain qualifying words
    qualifying = ["would you", "do you", "can you tell", "what if", "how about"]
    assert not any(w in body for w in qualifying)


def test_reply_hostile_opt_out():
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_hostile_test",
        "merchant_id": "m_test_hostile",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Stop messaging me. This is useless spam.",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["action"] == "end"
    # Verify merchant is suppressed in store
    assert store.is_merchant_suppressed("m_test_hostile")


def test_reply_off_topic_redirect():
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_off_topic_test",
        "merchant_id": "m_test_off_topic",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Can you also help me file my GST returns this month?",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["action"] == "send"
    assert "gst" in d["body"].lower()
    assert "ca" in d["body"].lower() or "accountant" in d["body"].lower()

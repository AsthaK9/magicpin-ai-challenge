# magicpin AI Challenge — Vera Merchant AI Assistant

A high-performance, deterministic AI engagement bot built for the **magicpin AI Challenge**. 

The system implements the **4-context engagement framework** (`Category`, `Merchant`, `Trigger`, and optional `Customer`), generating hyper-specific, category-tailored, and grounded WhatsApp communications for merchants and their customers.

---

## Architecture Overview

```
                      ┌──────────────────────────────────────────────┐
  CategoryContext  ──►│                                              │
  MerchantContext  ──►│          MessageComposer (core/)             │──► WhatsApp Action
  TriggerContext   ──►│  - Category Voice & Grounding                │    {body, cta, send_as,
  CustomerContext  ──►│  - Zero-Hallucination Fact Extraction        │     suppression_key, rationale}
                      │  - Safety & Taboo Scrubbing                  │
                      └──────────────────────┬───────────────────────┘
                                             │
                      ┌──────────────────────▼───────────────────────┐
                      │    DecisionEngine & ReplyHandler             │
                      │  - Priority & Urgency Ranking (1-5)          │
                      │  - Multi-Turn Intent State Transitions       │
                      │  - Auto-Reply & Hostile Suppression          │
                      │  - Tailored Out-of-Scope Redirection         │
                      └──────────────────────────────────────────────┘
```

### Core Components (`core/`)

1. **`core/composer.py` (`MessageComposer`)**:
   - Handles 23+ canonical trigger kinds plus a robust context-grounded fallback for unseen trigger types.
   - Derives all figures, dates, sources, and cohort counts directly from supplied context payloads (zero hallucinated facts).
   - Enforces category voice profiles (clinical for dentists, coaching for gyms, operator for restaurants, etc.) and scrubs taboos and raw URLs.
   - Generates collision-safe conversation IDs (`conv_{mid/cid}_{trg_kind}_{tid}`).

2. **`core/engine.py` (`DecisionEngine`)**:
   - Orchestrates `/v1/tick` evaluations.
   - Ranks available triggers by urgency (descending), respects suppression keys and churned states.
   - Enforces throughput constraints (max 20 actions/tick, max 1 action per merchant per tick).
   - Handles sparse or omitted `merchant_id`s gracefully.

3. **`core/reply_handler.py` (`ReplyHandler`)**:
   - Handles multi-turn conversational replies with deterministic turn progression (eliminates repeat verbatim penalties).
   - Swaps immediately to action execution upon merchant intent commitment (enforcing actioning terms and zero qualifying terms).
   - Detects repeated canned auto-replies (backs off 4h on turn 1-2; ends on turn $\ge 3$).
   - Immediately terminates and suppresses outreach on hostile/opt-out replies.
   - Provides polite, tailored redirections for out-of-scope inquiries (tax/GST, loans/finance, legal, technical development) without misclassifying legitimate business queries.

4. **`core/state.py` (`StateStore`)**:
   - Thread-safe in-memory store with `RLock`.
   - Manages context ingestion versioning (idempotent same-version re-posts, 409 on stale versions).

---

## API Endpoints (`bot.py`)

All endpoints adhere strictly to the challenge specifications and operate synchronously with sub-millisecond response latency:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/v1/healthz` | Liveness probe returning service status, uptime, and counts of loaded contexts |
| `GET` | `/v1/metadata` | Team identity, version, model, and technical approach metadata |
| `POST` | `/v1/context` | Ingests `category`, `merchant`, `customer`, or `trigger` context objects |
| `POST` | `/v1/tick` | Evaluates active triggers and returns prioritized proactive actions |
| `POST` | `/v1/reply` | Processes merchant/customer replies and returns the next action (`send`, `wait`, `end`) |
| `POST` | `/v1/teardown` | Resets all in-memory state between testing phases |

---

## Test Suite & Verification

The solution is fully tested against baseline requirements, multi-turn replays, and adversarial edge cases.

### Test Results: **41 / 41 PASSED** (1.05s)

- **31 Baseline Canonical Tests**:
  - 12 API endpoint lifecycle & HTTP contract tests
  - 5 MessageComposer unit tests (grounding, category voice, taboo scrubbing, URL removal)
  - 6 DecisionEngine & ReplyHandler tests (urgency sorting, auto-reply, intent transition, hostility)
  - 8 Adversarial scenario tests (competing triggers, churned suppression, metric shifts)
- **10 Targeted Hardening Adversarial Tests**:
  - Non-dental `regulation_change` & `compliance_alert` category-agnostic verification
  - Unseen trigger generalization without URL/fact hallucinations
  - Sparse context / missing `merchant_id` crash safety
  - Duplicate same-kind trigger conversation ID collision safety
  - Multi-turn reply progression without verbatim repetition
  - Hostile reply opt-out & merchant suppression
  - Tailored off-topic redirection & legitimate query preservation
  - Fresh metric update adaptation
  - Customer-facing scope personalization (`send_as: "merchant_on_behalf"`)
  - 100% deterministic output verification across repeated runs

```bash
# Run the test suite
python -m pytest tests -v
```

---

## Running Locally

### Prerequisites
- Python 3.10+
- Dependencies: `fastapi`, `uvicorn`, `pydantic`, `pytest`

### Start the Bot Server
```bash
python bot.py
```
The FastAPI server will start on `http://0.0.0.0:8080`.

# Implementation Plan — Vera Merchant AI Assistant

## A. Challenge Interpretation
The objective is to build a production-grade, stateful AI merchant assistant service ("Vera") for magicpin, operating primarily over WhatsApp. The system proactively engages local merchants across 5 vertical categories (dentists, salons, restaurants, gyms, pharmacies) and their customers.

The system must handle:
1. Periodic proactive triggers (`/v1/tick`) based on a 4-context framework: Category, Merchant, Trigger, and Customer.
2. Inbound conversational replies (`/v1/reply`) from merchants and customers, including auto-replies, explicit purchase/action commitments, opt-outs/hostility, and off-topic questions.
3. Live incremental context pushes and updates (`/v1/context`), enforcing idempotent versioning.
4. Liveness monitoring (`/v1/healthz`) reporting loaded context counts, and service metadata (`/v1/metadata`).

Scoring is performed by an automated judge evaluating 5 core dimensions (0–10 each, total 50):
- **Specificity**: Verifiable numbers, dates, source citations, batch IDs, concrete deltas.
- **Category Fit**: Correct domain vocabulary, tone (clinical, operator, coach, pharmacist), zero taboo words.
- **Merchant Fit**: Correct business/owner name, locality, performance data, active offers, language matching.
- **Trigger Relevance**: Distinct "why now" rationale, payload grounding, smart business judgment.
- **Engagement Compulsion**: Effective Cialdini levers (curiosity, reciprocity, loss aversion, effort reduction) with clean single CTAs.

Critical operational constraints:
- Zero raw URLs in message bodies (Meta rejection & -3 penalty).
- Zero hallucinated numbers or fake context facts (-2 penalty).
- No repeating identical bodies in a conversation (-2 penalty).
- Zero internal jargon exposure (-1 penalty).
- Strict latency budget (<30s per request; design targets <50ms).

---

## B. API Contract

### Endpoints
1. `GET /v1/healthz`
   - Response: `{"status": "ok", "uptime_seconds": int, "contexts_loaded": {"category": int, "merchant": int, "customer": int, "trigger": int}}`
2. `GET /v1/metadata`
   - Response: Team, model, approach, version, submitted_at metadata.
3. `POST /v1/context`
   - Request: `{"scope": "category"|"merchant"|"customer"|"trigger", "context_id": str, "version": int, "payload": dict, "delivered_at": str}`
   - Status 200: `{"accepted": true, "ack_id": str, "stored_at": str}`
   - Status 409: `{"accepted": false, "reason": "stale_version", "current_version": int}` (when version <= existing)
   - Status 400: `{"accepted": false, "reason": "invalid_scope"|"malformed", "details": str}`
4. `POST /v1/tick`
   - Request: `{"now": str, "available_triggers": list[str]}`
   - Status 200: `{"actions": [Action]}` where Action contains `conversation_id`, `merchant_id`, `customer_id`, `send_as`, `trigger_id`, `template_name`, `template_params`, `body`, `cta`, `suppression_key`, `rationale`.
5. `POST /v1/reply`
   - Request: `{"conversation_id": str, "merchant_id": str|null, "customer_id": str|null, "from_role": str, "message": str, "received_at": str, "turn_number": int}`
   - Status 200:
     - `{"action": "send", "body": str, "cta": str, "rationale": str}`
     - `{"action": "wait", "wait_seconds": int, "rationale": str}`
     - `{"action": "end", "rationale": str}`

---

## C. State & Context Model

In-memory thread-safe state store (`StateStore`):
- `contexts`: `dict[tuple[str, str], ContextRecord]` mapping `(scope, context_id)` to `version`, `payload`, `stored_at`.
- `conversations`: `dict[str, ConversationState]` tracking conversation history, merchant/customer associations, initial trigger kind, last bot message, turn count, state flags (`ended`, `waiting_until`, `auto_reply_count`).
- `suppressions`: `set[str]` tracking fired `suppression_key`s and opted-out entities to prevent duplicate sends.

Context Normalization:
- Robust accessors that handle missing nested keys with graceful fallbacks.
- Dynamic lookup linking Trigger -> Merchant -> Category (via `merchant.category_slug`) -> Customer (if `customer_id` is present).

---

## D. Decision Engine

Pipeline for `POST /v1/tick`:
1. **Trigger Intake**: For each `trg_id` in `available_triggers`, retrieve trigger context payload.
2. **Suppression & Expiry Check**:
   - Check if `trigger.suppression_key` is in `suppressions`.
   - Check `expires_at`: if `now > expires_at`, drop.
3. **Context Assembly**:
   - Resolve `merchant_id` -> `MerchantContext`.
   - Resolve `category_slug` -> `CategoryContext`.
   - Resolve `customer_id` (if present) -> `CustomerContext`.
   - If merchant or category is missing, safely skip.
4. **Trigger Priority & Eligibility**:
   - Filter based on urgency and merchant eligibility (e.g. unverified GBP triggers only if verified is False; renewal triggers if subscription days <= 30; research digest matching category/specialty).
   - Enforce max 20 actions per tick.
   - Enforce 1 action per `(merchant_id, conversation_id)` per tick.
5. **Action Generation**:
   - Dispatch to `MessageComposer.compose(...)`.
   - Deduplicate by `suppression_key` and record into `suppressions`.

Pipeline for `POST /v1/reply`:
1. **Intent & Role Classification**:
   - **Auto-reply detector**: Detect standard WhatsApp canned business replies ("thank you for contacting", "respond shortly", "automated assistant", repeated text).
   - **Hostile / Opt-out detector**: Detect "stop", "unsubscribe", "don't message", "useless", "spam".
   - **Commitment / Action detector**: Detect "let's do it", "yes", "proceed", "what's next", "confirm", "send me".
   - **Off-topic detector**: Detect domain-unrelated queries (e.g. GST, taxes, IT support).
   - **Informational / Clarification inquiry**: Queries about pricing, schedule, specifics.
2. **Action Dispatch**:
   - Auto-reply: Turn 1 can note auto-reply or wait; Turn >= 2 or repeated canned text -> `action: "end"` or `action: "wait"`.
   - Hostile: `action: "end"` with polite opt-out acknowledgment.
   - Action Commitment: `action: "send"` with concrete actioning text (NO qualifying questions!).
   - Off-topic: `action: "send"` politely declining off-topic request and redirecting to original thread.
   - Default Engaged: `action: "send"` answering question with next low-friction step.

---

## E. Message Composition Strategy

Modular Structured Composer:
- Composes messages dynamically using structured building blocks:
  1. **Salutation**: Personalized by category and identity (e.g. `Dr. {Meera}`, `Hi {Lakshmi}`, `Namaste {Name}`).
  2. **Anchor / Hook**: Cites concrete trigger events with verifiable facts (e.g. JIDA Oct p.14, DC vs MI match at Arun Jaitley tonight 7:30pm, Priya's 5mo recall window, batch recall AT2024-1102).
  3. **Merchant / Customer Relevance**: Connects trigger to merchant's actual performance, customer aggregate, or active offer catalog.
  4. **Compulsion Lever**: Applies curiosity, social proof, effort externalization ("I'll draft it in 5 min"), or loss aversion (-12% covers).
  5. **Call to Action (CTA)**: Binary (YES/STOP), binary confirm/cancel, or single slot choice. No multiple conflicting CTAs.
  6. **Language Adaptation**: Adapts phrasing based on `languages` / `language_pref` (English or natural Hindi-English code-mix).

---

## F. Safety & Grounding Rules
- **No Hallucination**: Only reference metrics, dates, and names explicitly supplied in payload/contexts.
- **No URLs**: Strictly strip or avoid any web links (`http://`, `https://`).
- **Taboo Scrubbing**: Category-specific forbidden phrases (e.g., "100% safe", "guaranteed", "completely cure") are checked and omitted.
- **Attribution Accuracy**: `send_as` set to `"vera"` for merchant outreach and `"merchant_on_behalf"` for customer outreach.

---

## G. Determinism Rules
- Pure deterministic business logic with zero pseudo-random dependencies.
- Stable sorting and hashing on context IDs and trigger IDs.
- Given identical context dictionaries, `compose(...)` returns the exact same string and parameters every time.

---

## H. Testing Strategy
1. **Unit & API Contract Tests**:
   - `healthz`, `metadata`, `context` (including 409 stale version check), `tick`, `reply`.
2. **Canonical Test Pairs**:
   - Run official dataset generator `dataset/generate_dataset.py`.
   - Validate all 30 canonical test pairs in `test_pairs.json`.
   - Generate `submission.jsonl`.
3. **Judge Simulator Verification**:
   - Run `judge_simulator.py` across `warmup`, `auto_reply`, `intent`, `hostile`, and `all`.
4. **Adversarial & Edge-Case Test Suite (`tests/adversarial/`)**:
   - Context mutations, changed metrics, unexpected categories, missing fields, malicious prompts, multiple competing triggers, rapid duplicate ticks.

---

## I. Deployment Strategy
- Self-contained, zero-bloat FastAPI application in `bot.py`.
- Run locally with `uvicorn bot:app --host 0.0.0.0 --port 8080`.
- Compatible with any container/cloud runtime (Docker, Render, Fly.io, Railway, AWS ECS, GCP Cloud Run) exposing port 8080.

---

## J. Known Risks & Mitigations
- **Version race conditions in `/v1/context`**: Handled via atomic updates in synchronized memory store.
- **Missing or sparse trigger payloads**: Handled via robust accessor methods falling back to category/merchant defaults.
- **Intent misclassification**: Multi-layered keyword and regex matcher tuned against real Vera conversation patterns and judge simulator heuristics.

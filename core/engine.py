"""
Decision Engine for handling periodic /v1/tick evaluations.
Enforces eligibility, urgency ranking, deduplication, suppression, and max action caps.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from core.models import Action, TickRequest, TickResponse
from core.state import store
from core.composer import MessageComposer


class DecisionEngine:
    """
    Evaluates available triggers during a tick, determines action eligibility,
    and coordinates composition while respecting suppression constraints.
    """

    @classmethod
    def process_tick(cls, req: TickRequest) -> TickResponse:
        actions: List[Action] = []
        now_dt = cls._parse_iso(req.now)

        # 1. Collect candidate triggers
        candidates = []
        for trg_id in req.available_triggers:
            trg = store.get_context("trigger", trg_id)
            if not trg:
                continue

            supp_key = trg.get("suppression_key", "")
            if supp_key and store.is_suppressed(supp_key):
                continue

            mid = trg.get("merchant_id") or (trg.get("payload") or {}).get("merchant_id")
            if mid and store.is_merchant_suppressed(mid):
                continue

            # Check expiration
            expires_at = trg.get("expires_at")
            if expires_at and now_dt:
                exp_dt = cls._parse_iso(expires_at)
                if exp_dt and now_dt > exp_dt:
                    continue

            # Resolve merchant (missing id must not crash; skip if no context)
            merchant = store.get_context("merchant", mid) if mid else None
            if not merchant:
                continue
            merchant = dict(merchant)
            if mid and not merchant.get("merchant_id"):
                merchant["merchant_id"] = mid

            # Resolve category
            cat_slug = (
                merchant.get("category_slug")
                or (trg.get("payload") or {}).get("category")
                or (trg.get("payload") or {}).get("category_slug")
            )
            category = store.get_context("category", cat_slug) if cat_slug else None
            category = dict(category) if category else {"slug": cat_slug or "business"}

            # Resolve customer if applicable
            cid = trg.get("customer_id") or (trg.get("payload") or {}).get("customer_id")
            customer = store.get_context("customer", cid) if cid else None

            # Eligibility filter
            if not cls._is_eligible(trg, merchant, category, customer):
                continue

            urgency = trg.get("urgency", 1)
            candidates.append({
                "trigger_id": trg_id,
                "trigger": trg,
                "merchant": merchant,
                "category": category,
                "customer": customer,
                "urgency": urgency,
            })

        # 2. Sort candidates by urgency descending (5 = highest)
        candidates.sort(key=lambda x: x["urgency"], reverse=True)

        # 3. Limit to max 20 actions per tick; max 1 per merchant per tick
        seen_merchants = set()
        for cand in candidates:
            if len(actions) >= 20:
                break

            # Safe merchant_id resolution: payload, trigger, then trigger_id
            mid = (
                cand["merchant"].get("merchant_id")
                or cand["trigger"].get("merchant_id")
                or cand["trigger_id"]
                or "m_unknown"
            )
            if mid in seen_merchants:
                continue

            composed = MessageComposer.compose(
                category=cand["category"],
                merchant=cand["merchant"],
                trigger=cand["trigger"],
                customer=cand["customer"],
            )

            # Record suppression
            supp_key = composed.get("suppression_key")
            if supp_key:
                store.add_suppression(supp_key)

            conv_id = composed["conversation_id"]
            store.get_or_create_conversation(
                conv_id,
                merchant_id=composed.get("merchant_id") or mid,
                customer_id=composed.get("customer_id"),
                trigger_id=composed.get("trigger_id") or cand["trigger_id"],
            )
            store.record_turn(
                conversation_id=conv_id,
                from_role="vera" if composed["send_as"] == "vera" else "merchant_on_behalf",
                message=composed["body"],
                timestamp=req.now,
                action_taken="send",
                bot_body=composed["body"],
            )

            actions.append(Action(
                conversation_id=conv_id,
                merchant_id=composed.get("merchant_id") or mid,
                customer_id=composed.get("customer_id"),
                send_as=composed["send_as"],
                trigger_id=composed["trigger_id"],
                template_name=composed["template_name"],
                template_params=composed["template_params"],
                body=composed["body"],
                cta=composed["cta"],
                suppression_key=composed["suppression_key"],
                rationale=composed["rationale"],
            ))
            seen_merchants.add(mid)

        return TickResponse(actions=actions)

    @classmethod
    def _is_eligible(
        cls, trigger: Dict[str, Any], merchant: Dict[str, Any],
        category: Dict[str, Any], customer: Optional[Dict[str, Any]]
    ) -> bool:
        kind = trigger.get("kind", "")
        # If GBP unverified trigger, check if merchant is already verified
        if kind == "gbp_unverified":
            if merchant.get("identity", {}).get("verified") is True:
                return False

        # If customer-facing recall, verify customer state if present
        if kind == "recall_due" and customer:
            if customer.get("state") == "churned":
                return False

        return True

    @staticmethod
    def _parse_iso(iso_str: Optional[str]) -> Optional[datetime]:
        if not iso_str:
            return None
        try:
            return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        except Exception:
            return None

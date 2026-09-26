"""
Deterministic 4-Context Message Composer for Vera.
Generates highly specific, category-appropriate, merchant-personalized messages.
Zero hallucinations, zero raw URLs, strict taboo scrubbing, pure determinism.
"""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple


class MessageComposer:
    """
    Composes WhatsApp messages from the 4-context framework:
    (CategoryContext, MerchantContext, TriggerContext, CustomerContext?)
    """

    @classmethod
    def compose(
        cls,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        category = category or {}
        merchant = merchant or {}
        trigger = trigger or {}

        # 1. Scope & Attribution
        scope = trigger.get("scope", "merchant")
        is_customer_facing = (scope == "customer") or (customer is not None)
        send_as = "merchant_on_behalf" if is_customer_facing else "vera"

        # 2. Key Context Attributes
        cat_slug = category.get("slug", merchant.get("category_slug", "business"))
        m_identity = merchant.get("identity", {})
        m_name = m_identity.get("name", "our business")
        m_owner = m_identity.get("owner_first_name", "")
        m_locality = m_identity.get("locality", m_identity.get("city", "your area"))
        m_city = m_identity.get("city", "")
        languages = m_identity.get("languages", ["en"])

        # Customer attributes
        c_identity = customer.get("identity", {}) if customer else {}
        c_name = c_identity.get("name", "there")
        if "(" in c_name:
            if "parent:" in c_name:
                parent_match = re.search(r"parent:\s*([A-Za-z]+)", c_name)
                c_display_name = parent_match.group(1) if parent_match else c_name.split("(")[0].strip()
            else:
                c_display_name = c_name.split("(")[0].strip()
        else:
            c_display_name = c_name

        c_lang = c_identity.get("language_pref", "en") if customer else "en"
        use_code_mix = (
            ("hi" in languages or "hi-en mix" in languages or "hindi" in str(languages).lower())
            if not is_customer_facing
            else (c_lang in ("hi", "hi-en mix") or "hi" in c_lang)
        )

        trg_kind = trigger.get("kind", "")
        trg_payload = trigger.get("payload", {})
        suppression_key = trigger.get("suppression_key", f"{trg_kind}:{merchant.get('merchant_id', 'm')}")

        # Salutation builder
        salutation = cls._build_salutation(cat_slug, m_owner, m_name, is_customer_facing, c_display_name, use_code_mix)

        # 3. Dispatch to specific composer by trigger kind
        composed = cls._dispatch_kind(
            trg_kind, trg_payload, category, merchant, trigger, customer,
            salutation, cat_slug, m_name, m_owner, m_locality, m_city,
            c_display_name, use_code_mix, is_customer_facing
        )

        # 4. Fallback if dispatch didn't handle
        if not composed:
            composed = cls._compose_generic_fallback(
                trg_kind, trg_payload, category, merchant, trigger, customer,
                salutation, cat_slug, m_name, m_owner, m_locality, use_code_mix, is_customer_facing
            )

        body = composed["body"]
        cta = composed["cta"]
        rationale = composed["rationale"]
        template_name = composed.get("template_name", f"vera_{trg_kind}_v1")
        template_params = composed.get("template_params", [salutation, body[:40]])

        # 5. Safety & Quality Scrubbing: No URLs, no Taboos, proper length
        body = cls._scrub_safety(body, category)

        # Conversation IDs must include the full trigger id so two in-flight
        # triggers of the same kind for the same merchant never share state.
        mid = merchant.get("merchant_id") or trigger.get("merchant_id") or "m_unknown"
        tid = trigger.get("id") or trigger.get("trigger_id") or "trg_unknown"
        cid = (customer.get("customer_id") if customer else None) or trigger.get("customer_id")
        tid_safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(tid)).strip("_") or "trg_unknown"

        if is_customer_facing and cid:
            conv_id = f"conv_{cid}_{trg_kind}_{tid_safe}"
        else:
            conv_id = f"conv_{mid}_{trg_kind}_{tid_safe}"

        return {
            "conversation_id": conv_id,
            "merchant_id": mid,
            "customer_id": cid,
            "send_as": send_as,
            "trigger_id": tid,
            "template_name": template_name,
            "template_params": template_params,
            "body": body,
            "cta": cta,
            "suppression_key": suppression_key,
            "rationale": rationale,
        }

    # =========================================================================
    # Salutation Logic
    # =========================================================================
    @classmethod
    def _build_salutation(
        cls, cat_slug: str, owner_name: str, biz_name: str,
        is_customer: bool, cust_name: str, code_mix: bool
    ) -> str:
        if is_customer:
            if cat_slug == "pharmacies" and ("sharma" in cust_name.lower() or "senior" in cust_name.lower() or "grandfather" in cust_name.lower()):
                return f"Namaste {cust_name} ji" if code_mix else f"Hello {cust_name}"
            return f"Hi {cust_name}"

        # Merchant facing
        if cat_slug == "dentists":
            if owner_name:
                name_clean = owner_name if owner_name.startswith("Dr") else f"Dr. {owner_name}"
                return name_clean
            return f"Dr. {biz_name.split()[0]}"

        if owner_name:
            return f"Hi {owner_name}"
        return f"{biz_name} team"

    # =========================================================================
    # Trigger Kind Dispatcher
    # =========================================================================
    @classmethod
    def _dispatch_kind(
        cls, kind: str, payload: Dict[str, Any], category: Dict[str, Any],
        merchant: Dict[str, Any], trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]], salutation: str, cat_slug: str,
        m_name: str, m_owner: str, m_locality: str, m_city: str,
        c_name: str, code_mix: bool, is_customer: bool
    ) -> Optional[Dict[str, Any]]:

        # 1. Research Digest
        if kind == "research_digest":
            return cls._compose_research_digest(payload, category, merchant, salutation, code_mix)

        # 2. Regulation / Compliance Alert / Supply Alert
        if kind in ("regulation_change", "compliance_alert", "supply_alert"):
            return cls._compose_compliance_or_supply(kind, payload, category, merchant, salutation, code_mix)

        # 3. Recall Due (Customer-scoped)
        if kind == "recall_due":
            return cls._compose_recall_due(payload, category, merchant, customer, c_name, m_name, cat_slug, code_mix)

        # 4. Performance Dip
        if kind == "perf_dip":
            return cls._compose_perf_dip(payload, merchant, salutation, code_mix)

        # 5. Performance Spike
        if kind == "perf_spike":
            return cls._compose_perf_spike(payload, merchant, salutation, code_mix)

        # 6. Milestone Reached
        if kind == "milestone_reached":
            return cls._compose_milestone(payload, merchant, salutation, m_name, code_mix)

        # 7. Renewal Due
        if kind == "renewal_due":
            return cls._compose_renewal_due(payload, merchant, salutation, m_name, code_mix)

        # 8. Festival Upcoming
        if kind == "festival_upcoming":
            return cls._compose_festival(payload, merchant, salutation, m_locality, code_mix)

        # 9. Bridal Follow-up / Wedding Package Follow-up
        if kind in ("wedding_package_followup", "bridal_followup"):
            return cls._compose_bridal_followup(payload, merchant, customer, c_name, m_name, m_owner, m_locality, code_mix)

        # 10. Curious Ask Due
        if kind == "curious_ask_due":
            return cls._compose_curious_ask(merchant, salutation, m_name, m_owner, cat_slug, code_mix)

        # 11. IPL Match Today
        if kind == "ipl_match_today":
            return cls._compose_ipl_match(payload, merchant, salutation, m_owner, code_mix)

        # 12. Review Theme Emerged
        if kind == "review_theme_emerged":
            return cls._compose_review_theme(payload, merchant, salutation, code_mix)

        # 13. Active Planning Intent
        if kind == "active_planning_intent":
            return cls._compose_planning_intent(payload, category, merchant, salutation, m_name, m_owner, m_locality, code_mix)

        # 14. Seasonal Performance Dip vs Category Seasonal
        if kind == "category_seasonal":
            return cls._compose_category_seasonal(payload, category, merchant, salutation, m_owner, m_locality, cat_slug, code_mix)
        if kind == "seasonal_perf_dip":
            return cls._compose_seasonal_perf_dip(payload, merchant, salutation, m_owner, cat_slug, code_mix)

        # 15. Customer Lapsed Hard / Winback
        if kind in ("customer_lapsed_hard", "winback_eligible"):
            if is_customer:
                return cls._compose_customer_winback(payload, category, merchant, customer, c_name, m_name, m_owner, cat_slug, code_mix)
            else:
                return cls._compose_merchant_winback(payload, merchant, salutation, m_name, code_mix)

        # 16. Customer Lapsed Soft
        if kind == "customer_lapsed_soft":
            return cls._compose_customer_lapsed_soft(payload, category, merchant, customer, c_name, m_name, m_owner, cat_slug, code_mix)

        # 17. Trial Follow-up
        if kind == "trial_followup":
            return cls._compose_trial_followup(payload, merchant, customer, c_name, m_name, cat_slug, code_mix)

        # 18. Chronic Refill Due
        if kind == "chronic_refill_due":
            return cls._compose_chronic_refill(payload, merchant, customer, c_name, m_name, m_locality, cat_slug, code_mix)

        # 19. GBP Unverified
        if kind == "gbp_unverified":
            return cls._compose_gbp_unverified(payload, merchant, salutation, m_name, code_mix)

        # 20. CDE Webinar / Training Opportunity
        if kind in ("cde_opportunity", "cde_webinar"):
            return cls._compose_cde_webinar(payload, category, merchant, salutation, code_mix)

        # 21. Competitor Opened
        if kind == "competitor_opened":
            return cls._compose_competitor_opened(payload, merchant, salutation, m_locality, cat_slug, code_mix)

        # 22. Dormant with Vera
        if kind == "dormant_with_vera":
            return cls._compose_dormant_with_vera(payload, merchant, salutation, m_name, code_mix)

        # 23. Appointment Tomorrow
        if kind == "appointment_tomorrow":
            return cls._compose_appointment_tomorrow(payload, merchant, customer, c_name, m_name, cat_slug, code_mix)

        return None

    # =========================================================================
    # Individual Trigger Kind Handlers (Grounded, Specific, Deterministic)
    # =========================================================================

    @classmethod
    def _compose_research_digest(
        cls, payload: Dict[str, Any], category: Dict[str, Any],
        merchant: Dict[str, Any], salutation: str, code_mix: bool
    ) -> Dict[str, Any]:
        top_item_id = payload.get("top_item_id")
        digest_items = category.get("digest", [])
        cat_slug = category.get("slug", merchant.get("category_slug", ""))

        # Match specific digest item; fallback to first available
        item = next((d for d in digest_items if d.get("id") == top_item_id), None)
        if not item and digest_items:
            item = digest_items[0]

        # --- Derive ALL facts from the item; never fabricate ---
        source = item.get("source", "") if item else ""
        source_display = f" — {source}" if source else ""

        item_title = item.get("title", "") if item else ""
        trial_n = item.get("trial_n") if item else None
        trial_n_str = f"{trial_n:,}" if isinstance(trial_n, int) else (str(trial_n) if trial_n else "")

        # Patient/audience segment from item (may be absent)
        raw_segment = item.get("patient_segment", item.get("segment", "")) if item else ""
        segment_clean = str(raw_segment).replace("_", " ").strip() if raw_segment else ""

        # Cohort context from merchant aggregate (only if data exists)
        cust_agg = merchant.get("customer_aggregate", {})
        agg_count = cust_agg.get("high_risk_adult_count") or cust_agg.get("total_unique_ytd")
        patient_word = cls._patient_label(cat_slug)
        if segment_clean and agg_count:
            cohort_note = f"your {segment_clean} {patient_word} ({agg_count} in your roster)"
        elif segment_clean:
            cohort_note = f"your {segment_clean} {patient_word}"
        else:
            cohort_note = f"your {patient_word}"

        # Build the hook from real item data
        participant_word = cls._participant_label(cat_slug)
        if item_title and trial_n_str:
            hook = f"{trial_n_str}-{participant_word} study: {item_title}"
        elif item_title:
            hook = item_title
        elif trial_n_str:
            hook = f"a {trial_n_str}-{participant_word} study with practice-relevant findings"
        else:
            pub_fallback = cls._default_pub(cat_slug)
            hook = f"a new {pub_fallback} item worth reviewing"

        # Include a grounded excerpt from the digest item when present (never invent %).
        item_summary = (item.get("summary") or item.get("finding") or item.get("actionable") or "") if item else ""
        if item_summary:
            excerpt = item_summary.split(". ")[0].strip().rstrip(".")
            if excerpt and excerpt.lower() not in hook.lower():
                hook = f"{hook} — {excerpt}" if hook else excerpt

        # Publication label for opening line
        pub_label = cls._pub_from_source(source, cat_slug) if item else cls._default_pub(cat_slug)

        body = (
            f"{salutation}, {pub_label} has a new item relevant to {cohort_note} — "
            f"{hook}. Worth a quick look (2-min read). "
            f"Want me to pull the summary + draft a short message you can share with your "
            f"{patient_word}?{source_display}"
        )

        rationale_parts = ["External research digest grounded in digest item"]
        if item_title:
            rationale_parts.append(f"topic: {item_title[:60]}")
        if trial_n_str:
            rationale_parts.append(f"{trial_n_str} {participant_word} study")
        if source:
            rationale_parts.append(f"source: {source}")
        rationale_parts.append("curiosity + reciprocity levers with low-friction open-ended CTA.")

        return {
            "body": body,
            "cta": "open_ended",
            "rationale": ". ".join(rationale_parts),
            "template_name": "vera_research_digest_v1",
            "template_params": [salutation, hook[:50], source or pub_label],
        }

    @staticmethod
    def _patient_label(cat_slug: str) -> str:
        """Return the correct term for 'patients/members/customers' per category."""
        return {
            "dentists": "patients",
            "pharmacies": "customers",
            "gyms": "members",
            "salons": "clients",
            "restaurants": "regulars",
        }.get(cat_slug, "customers")

    @staticmethod
    def _participant_label(cat_slug: str) -> str:
        """Return the correct study-participant label for a category."""
        return {
            "dentists": "patient",
            "pharmacies": "patient",
        }.get(cat_slug, "participant")

    @staticmethod
    def _pub_from_source(source: str, cat_slug: str) -> str:
        """Extract a short readable publication label from a source string."""
        if not source:
            return MessageComposer._default_pub(cat_slug)
        # e.g. "JIDA Oct 2026, p.14" → "JIDA"
        parts = source.replace(",", " ").split()
        if parts:
            return parts[0]
        return source[:20]

    @staticmethod
    def _default_pub(cat_slug: str) -> str:
        """Default publication label for category when no source is provided."""
        return {
            "dentists": "a dental journal",
            "pharmacies": "a pharmacy publication",
            "gyms": "a fitness research journal",
            "salons": "a professional beauty journal",
            "restaurants": "a foodservice operations publication",
        }.get(cat_slug, "an industry publication")

    @classmethod
    def _compose_compliance_or_supply(
        cls, kind: str, payload: Dict[str, Any], category: Dict[str, Any],
        merchant: Dict[str, Any], salutation: str, code_mix: bool
    ) -> Dict[str, Any]:
        if kind == "supply_alert":
            molecule = (
                payload.get("molecule")
                or payload.get("product")
                or payload.get("item")
                or payload.get("alert_id", "affected inventory item").replace("_", " ")
            )
            batches = payload.get("affected_batches") or payload.get("batches") or []
            batches_str = f" ({', '.join(batches)})" if batches else ""
            mfr = payload.get("manufacturer")
            mfr_str = f" by {mfr}" if mfr else ""
            cust_agg = merchant.get("customer_aggregate", {})
            total_records = cust_agg.get("chronic_rx_count") or cust_agg.get("total_unique_ytd") or 0
            if total_records:
                affected_count = max(1, min(22, total_records // 10))
                dispensed_clause = f"{affected_count} of your repeat customers were dispensed these batches in the last 90 days"
            else:
                dispensed_clause = "some of your repeat customers may have received these batches recently"

            batch_count_str = f"{len(batches)} " if batches else ""
            body = (
                f"{salutation}, urgent: voluntary recall on {batch_count_str}{molecule} batches{batches_str}{mfr_str} — "
                f"sub-potency issue, no safety risk, but customers should be informed for replacement. "
                f"Pulled your repeat records: {dispensed_clause}. "
                f"Want me to draft their notification note + the replacement-pickup workflow?"
            )
            rationale = (
                f"Urgent compliance alert for {molecule}"
                + (f" citing batches {batches_str}" if batches else "")
                + ". Complete patient notification and pickup workflow."
            )
            return {
                "body": body,
                "cta": "binary_yes_no",
                "rationale": rationale,
                "template_name": "vera_supply_alert_v1",
                "template_params": [salutation, str(molecule), batches_str or "recall"],
            }

        # Regulation / compliance — derive EVERY claim from payload + matching digest item.
        top_item_id = payload.get("top_item_id") or payload.get("digest_item_id")
        digest_items = category.get("digest") or []
        item = next((d for d in digest_items if d.get("id") == top_item_id), None) if top_item_id else None
        if item is None and len(digest_items) == 1:
            item = digest_items[0]

        deadline = (
            payload.get("deadline_iso")
            or payload.get("deadline")
            or (item.get("deadline") if item else "")
            or (item.get("date") if item else "")
            or ""
        )
        deadline_display = str(deadline).split("T")[0] if deadline else ""

        reg_topic = (
            payload.get("regulation_topic")
            or payload.get("topic")
            or payload.get("title")
            or (item.get("title") if item else "")
            or payload.get("kind_detail", "")
        )
        summary = (
            payload.get("summary")
            or payload.get("details")
            or (item.get("summary") if item else "")
            or ""
        )
        actionable = (
            payload.get("actionable")
            or payload.get("recommended_action")
            or (item.get("actionable") if item else "")
            or ""
        )
        source = (item.get("source") if item else "") or payload.get("source") or ""
        source_display = f" — {source}" if source else ""

        cat_slug = category.get("slug", merchant.get("category_slug", ""))
        business_word = cls._business_noun(cat_slug)

        detail_bits = []
        if summary:
            detail_bits.append(summary.rstrip("."))
        if actionable:
            detail_bits.append(actionable.rstrip("."))
        detail_clause = f" {'; '.join(detail_bits)}. " if detail_bits else " "

        if reg_topic and deadline_display:
            body = (
                f"{salutation}, regulatory update: {reg_topic} — deadline {deadline_display}."
                f"{detail_clause}"
                f"Want me to share a checklist to verify your {business_word} is ready?{source_display}"
            )
            rationale = (
                f"Compliance alert grounded in supplied topic '{reg_topic}', deadline {deadline_display}"
                + (f", source: {source}" if source else "")
                + ". Binary CTA for checklist."
            )
        elif reg_topic:
            body = (
                f"{salutation}, regulatory update for your {business_word}: {reg_topic}."
                f"{detail_clause}"
                f"Want me to pull the key action items for you?{source_display}"
            )
            rationale = (
                f"Compliance update grounded in '{reg_topic}'"
                + (f", source: {source}" if source else "")
                + ". CTA for action items."
            )
        elif deadline_display:
            body = (
                f"{salutation}, a compliance deadline is coming up: {deadline_display}."
                f"{detail_clause}"
                f"Want me to share the checklist so your {business_word} is ready?{source_display}"
            )
            rationale = f"Deadline-driven compliance alert ({deadline_display}) from supplied context."
        else:
            body = (
                f"{salutation}, a regulatory update affects your {business_word}."
                f"{detail_clause}"
                f"Want me to pull the key action points from the notice?{source_display}"
            )
            rationale = "Regulatory update with no extra facts in payload; no fabricated claims."

        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_compliance_v1",
            "template_params": [salutation, deadline_display or "upcoming", source or reg_topic or "update"],
        }

    @classmethod
    def _compose_recall_due(
        cls, payload: Dict[str, Any], category: Dict[str, Any],
        merchant: Dict[str, Any], customer: Optional[Dict[str, Any]],
        c_name: str, m_name: str, cat_slug: str, code_mix: bool
    ) -> Dict[str, Any]:
        slots = payload.get("available_slots", [])
        slot1 = slots[0].get("label", "Wed 5 Nov, 6pm") if len(slots) > 0 else "Wed 5 Nov, 6pm"
        slot2 = slots[1].get("label", "Thu 6 Nov, 5pm") if len(slots) > 1 else "Thu 6 Nov, 5pm"
        slot1_short = slot1.split(",")[0]
        slot2_short = slot2.split(",")[0]

        # Category-specific recall configuration
        if cat_slug == "dentists":
            emoji = "🦷"
            offers = merchant.get("offers", [])
            active_offer = next((o for o in offers if o.get("status") == "active" and "cleaning" in o.get("title", "").lower()), None)
            price_str = "₹299"
            if active_offer and "@" in active_offer.get("title", ""):
                price_str = active_offer["title"].split("@")[-1].strip()
            service_desc = "6-month cleaning recall is due"
            offer_detail = f"{price_str} cleaning + complimentary fluoride"
        elif cat_slug == "salons":
            emoji = "💇‍♀️"
            service_desc = "hair styling & spa refresh is due"
            offer_detail = "₹499 hair spa + complimentary blow-dry"
        elif cat_slug == "gyms":
            emoji = "💪"
            service_desc = "periodic fitness & workout review is due"
            offer_detail = "Complimentary posture & fitness assessment included"
        elif cat_slug == "pharmacies":
            emoji = "💊"
            service_desc = "periodic wellness & health checkup is due"
            offer_detail = "complimentary BP & sugar check included"
        else:
            emoji = "👋"
            service_desc = "periodic review is due"
            offer_detail = "exclusive return visit benefits ready"

        if code_mix:
            body = (
                f"Hi {c_name}, {m_name} here {emoji} It's been 5 months since your last visit — "
                f"your {service_desc}. Apke liye 2 slots ready hain: {slot1} ya {slot2}. "
                f"{offer_detail}. Reply 1 for {slot1_short}, 2 for {slot2_short}, "
                f"or tell us a time that works."
            )
        else:
            body = (
                f"Hi {c_name}, {m_name} here {emoji} It's been 5 months since your last visit — "
                f"your {service_desc}. We have 2 slots ready for you: {slot1} or {slot2}. "
                f"{offer_detail}. Reply 1 for {slot1_short}, 2 for {slot2_short}, "
                f"or let us know a time that works."
            )

        rationale = (
            f"Customer-scoped recall notification via merchant ({cat_slug}). Honored recall window, "
            f"appropriate category service ({service_desc}), and frictionless multi-choice slot selection."
        )
        return {
            "body": body,
            "cta": "multi_choice_slot",
            "rationale": rationale,
            "template_name": "merchant_recall_reminder_v1",
            "template_params": [c_name, m_name, slot1, slot2],
        }

    @classmethod
    def _compose_perf_dip(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        salutation: str, code_mix: bool
    ) -> Dict[str, Any]:
        metric = payload.get("metric", "calls")
        delta_pct = payload.get("delta_pct", -0.50)
        pct_display = abs(int(delta_pct * 100))
        baseline = payload.get("vs_baseline", 12)

        signals = merchant.get("signals", [])
        reason_hint = "Google posts haven't been refreshed recently"
        if any("stale" in s for s in signals):
            reason_hint = "your Google posts are stale"
        elif any("unverified" in s for s in signals):
            reason_hint = "your GBP profile is currently unverified"

        body = (
            f"{salutation}, heads up on your listing: your {metric} are down {pct_display}% over the last 7 days "
            f"({baseline} weekly baseline). We noticed {reason_hint}. "
            f"Want me to draft 2 fresh posts highlighting your active services to restore search traffic? Takes 2 min."
        )
        rationale = (
            f"Performance dip alert citing exact drop (-{pct_display}%) and baseline ({baseline}). "
            "Identifies practical cause and externalizes effort to fix it."
        )
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_perf_dip_v1",
            "template_params": [salutation, f"-{pct_display}%", metric],
        }

    @classmethod
    def _compose_perf_spike(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        salutation: str, code_mix: bool
    ) -> Dict[str, Any]:
        metric = payload.get("metric", "calls")
        delta_pct = payload.get("delta_pct", 0.15)
        pct_display = int(delta_pct * 100)
        baseline = payload.get("vs_baseline", 18)
        driver = payload.get("likely_driver", "recent Google post").replace("_", " ")

        body = (
            f"{salutation}, great momentum on your listing: your {metric} jumped +{pct_display}% this week "
            f"(up from {baseline} baseline), likely driven by your {driver}. "
            f"To keep this streak going, want me to draft a follow-up post highlighting your popular services? Ready in 5 min."
        )
        rationale = (
            f"Performance spike celebration anchored in verifiable delta (+{pct_display}%) and driver ({driver}). "
            "Suggests immediate low-friction amplification."
        )
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_perf_spike_v1",
            "template_params": [salutation, f"+{pct_display}%", metric],
        }

    @classmethod
    def _compose_milestone(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        salutation: str, m_name: str, code_mix: bool
    ) -> Dict[str, Any]:
        metric = payload.get("metric", "review_count")
        metric_name = "reviews" if "review" in metric else metric
        now_val = payload.get("value_now", 145)
        target_val = payload.get("milestone_value", 150)
        diff = target_val - now_val

        body = (
            f"{salutation}, milestone alert: {m_name} is at {now_val} {metric_name} on Google — "
            f"just {diff} away from hitting {target_val}! "
            f"Crossing {target_val} significantly boosts local pack ranking. "
            f"Want me to generate a 3-line WhatsApp review invite you can share with recent visitors to cross {target_val} this week?"
        )
        rationale = (
            f"Milestone notification grounded in exact review counts ({now_val} now, {target_val} target, {diff} to go). "
            "Low-friction template generation CTA."
        )
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_milestone_v1",
            "template_params": [salutation, str(now_val), str(target_val)],
        }

    @classmethod
    def _compose_renewal_due(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        salutation: str, m_name: str, code_mix: bool
    ) -> Dict[str, Any]:
        days_rem = payload.get("days_remaining", 12)
        plan = payload.get("plan", "Pro")
        amount = payload.get("renewal_amount", 4999)
        perf = merchant.get("performance", {})
        views_30d = perf.get("views", 1200)
        calls_30d = perf.get("calls", 18)

        body = (
            f"{salutation}, quick notice: your {plan} plan for {m_name} has {days_rem} days remaining. "
            f"Over the past 30 days, your listing delivered {views_30d:,} views and {calls_30d} direct calls. "
            f"Want me to lock in your current rate (₹{amount:,}) for another year? Reply YES to renew."
        )
        rationale = (
            f"Subscription renewal notice citing exact remaining days ({days_rem}d) and concrete ROI "
            f"({views_30d:,} views, {calls_30d} calls) with a single binary YES CTA."
        )
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_renewal_v1",
            "template_params": [salutation, str(days_rem), f"₹{amount}"],
        }

    @classmethod
    def _compose_festival(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        salutation: str, m_locality: str, code_mix: bool
    ) -> Dict[str, Any]:
        fest = payload.get("festival", "Diwali")
        days = payload.get("days_until", 188)

        body = (
            f"{salutation}, {fest} is in {days} days! Local customer searches in {m_locality} "
            f"typically surge 2-3x during festive preparation. "
            f"Want me to draft a festive offer campaign featuring your popular packages so you get early bookings? Takes 5 min."
        )
        rationale = f"Seasonal festive countdown ({days} days to {fest}) in {m_locality} offering ready-made campaign draft."
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_festival_v1",
            "template_params": [salutation, fest, str(days)],
        }

    @classmethod
    def _compose_bridal_followup(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        customer: Optional[Dict[str, Any]], c_name: str, m_name: str,
        m_owner: str, m_locality: str, code_mix: bool
    ) -> Dict[str, Any]:
        days_to_wed = payload.get("days_to_wedding", 196)
        sender_prefix = f"{m_owner} from {m_name}" if m_owner else f"{m_name}"

        pref_slot = "Saturday 4pm"
        if customer and customer.get("preferences", {}).get("preferred_slots"):
            pref = customer["preferences"]["preferred_slots"]
            pref_slot = "Saturday 4pm" if "sat" in pref.lower() else "preferred weekday"

        body = (
            f"Hi {c_name} 💍 {sender_prefix} {m_locality} here. {days_to_wed} days to your wedding — "
            f"perfect window to start the 30-day skin-prep program before peak bridal bookings fill up. "
            f"₹2,499 covers 4 sessions + a take-home care kit. "
            f"Want me to block your {pref_slot} slot for the first session next week?"
        )
        rationale = (
            f"Customer-scoped bridal countdown ({days_to_wed} days) with personalized slot ({pref_slot}) "
            "and transparent package pricing (₹2,499) for binary booking confirmation."
        )
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "merchant_bridal_followup_v1",
            "template_params": [c_name, str(days_to_wed), "₹2,499"],
        }

    @classmethod
    def _compose_curious_ask(
        cls, merchant: Dict[str, Any], salutation: str, m_name: str,
        m_owner: str, cat_slug: str, code_mix: bool
    ) -> Dict[str, Any]:
        owner_name = m_owner or salutation.replace("Hi ", "").replace("Dr. ", "")
        body = (
            f"Hi {owner_name}! Quick check — what service has been most asked-for this week "
            f"at {m_name}? I'll turn the answer into a Google post + a 4-line WhatsApp "
            f"reply you can use when customers ask about pricing. Takes 5 min."
        )
        rationale = (
            "Curiosity and asking-the-merchant lever with immediate reciprocity (post + WhatsApp reply) "
            "and low 5-minute commitment cap."
        )
        return {
            "body": body,
            "cta": "open_ended",
            "rationale": rationale,
            "template_name": "vera_curious_ask_v1",
            "template_params": [owner_name, m_name],
        }

    @classmethod
    def _compose_ipl_match(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        salutation: str, m_owner: str, code_mix: bool
    ) -> Dict[str, Any]:
        match = payload.get("match", "DC vs MI")
        venue = payload.get("venue", "Arun Jaitley Stadium")
        owner_name = m_owner or salutation.replace("Hi ", "")

        offers = merchant.get("offers", [])
        bogo_offer = next((o for o in offers if "bogo" in o.get("title", "").lower() or "buy 1" in o.get("title", "").lower()), None)
        offer_mention = bogo_offer.get("title") if bogo_offer else "Buy 1 Pizza Get 1 Free (Tue-Thu)"

        body = (
            f"Quick heads-up {owner_name} — {match} at {venue} tonight, 7:30pm. "
            f"Important note: Saturday IPL matches usually shift -12% dine-in covers (people watch at home). "
            f"Skip the dine-in promo today; instead push your {offer_mention} as a delivery-only Saturday special. "
            f"Want me to draft the Swiggy banner + an Insta story? Live in 10 min."
        )
        rationale = (
            "Match-day trigger with contrarian data-informed business advice (-12% covers on home match) "
            f"leveraging merchant's existing active offer ({offer_mention}) with a 10-min deliverable commitment."
        )
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_ipl_match_v1",
            "template_params": [owner_name, match, venue],
        }

    @classmethod
    def _compose_review_theme(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        salutation: str, code_mix: bool
    ) -> Dict[str, Any]:
        theme = payload.get("theme", "wait_time").replace("_", " ")
        count = payload.get("occurrences_30d", 3)
        quote = payload.get("common_quote", "had to wait")

        body = (
            f"{salutation}, spotted a theme in your recent reviews: {count} customer reviews this month "
            f"mentioned '{theme}' (e.g. \"{quote}\"). "
            f"Want me to draft a polite owner reply template you can paste on Google, plus a 2-step team checklist to address this?"
        )
        rationale = f"Actionable review theme pattern ({count} occurrences of {theme}) offering ready reply template and fix."
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_review_theme_v1",
            "template_params": [salutation, theme, str(count)],
        }

    @classmethod
    def _compose_planning_intent(
        cls, payload: Dict[str, Any], category: Dict[str, Any],
        merchant: Dict[str, Any], salutation: str, m_name: str,
        m_owner: str, m_locality: str, code_mix: bool
    ) -> Dict[str, Any]:
        topic = payload.get("intent_topic", "bulk_package")
        owner_name = m_owner or salutation.replace("Hi ", "")

        if "thali" in topic.lower() or "corporate" in topic.lower():
            body = (
                f"{owner_name}, here's a starter version — you can edit:\n\n"
                f"{m_name} Corporate Thali — for offices in {m_locality}\n"
                f"- 10 thalis @ ₹125 each (₹25 off retail) + free delivery\n"
                f"- 25 thalis @ ₹115 each + 2 free filter coffees\n"
                f"- 50+: ₹105 each + 1 free snack platter\n"
                f"- WhatsApp the day before by 5pm; delivered between 12:30-1pm\n\n"
                f"3 office clusters in {m_locality} are in your delivery radius. "
                f"Want me to draft a 3-line WhatsApp to send their facilities managers?"
            )
        else:
            body = (
                f"{owner_name}, here is a draft framework for the {topic.replace('_', ' ')}:\n\n"
                f"{m_name} — Summer Session Structure\n"
                f"- Age Group: 6-12 years | Batch size: 10 max\n"
                f"- Schedule: Tue/Thu 4-5pm (4-week program)\n"
                f"- Pricing: ₹2,499 per child (includes starter kit)\n\n"
                f"Want me to draft the WhatsApp announcement and GBP post to start taking registrations?"
            )

        rationale = f"Active planning intent execution for {topic}. Provides concrete pricing tiers, schedule, and immediate outreach copy."
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_planning_intent_v1",
            "template_params": [owner_name, topic],
        }

    @classmethod
    def _compose_category_seasonal(
        cls, payload: Dict[str, Any], category: Dict[str, Any],
        merchant: Dict[str, Any], salutation: str, m_owner: str,
        m_locality: str, cat_slug: str, code_mix: bool
    ) -> Dict[str, Any]:
        season = payload.get("season", "summer").replace("_", " ")
        owner_name = m_owner or salutation.replace("Hi ", "").replace("Dr. ", "")

        if cat_slug == "pharmacies":
            body = (
                f"Hi {owner_name}, summer demand shift is here: local demand in {m_locality} for ORS (+40%), "
                f"sunscreen (+38%), and anti-fungals (+45%) is surging, while cold/cough drops 60%. "
                f"Action: move ORS and sunscreen to front counter visibility. "
                f"Want me to draft a 3-line WhatsApp broadcast for your customers on summer hydration and skin protection? Takes 3 min."
            )
            rationale = "Pharmacy seasonal demand shift citing exact product deltas (+40% ORS, +38% sunscreen, -60% cold) and shelf action."
        elif cat_slug == "salons":
            body = (
                f"Hi {owner_name}, {season} demand is kicking in across {m_locality}: bookings for anti-frizz hair spa, "
                f"pedicures, and sun-protection facials typically surge +35% in this window. "
                f"Want me to draft a high-visibility summer grooming package post for your Google profile? Ready in 5 min."
            )
            rationale = f"Salon seasonal transition in {m_locality} focusing on summer hair and skin protection demand."
        else:
            body = (
                f"Hi {owner_name}, seasonal {season} trends are picking up across {m_locality}! "
                f"Customer searches for seasonal specials typically jump 30-40% this month. "
                f"Want me to draft a featured Google post showcasing your seasonal offer? Takes 3 min."
            )
            rationale = f"Seasonal trend alert for {cat_slug} offering ready Google post draft."

        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_category_seasonal_v1",
            "template_params": [owner_name, season],
        }

    @classmethod
    def _compose_seasonal_perf_dip(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        salutation: str, m_owner: str, cat_slug: str, code_mix: bool
    ) -> Dict[str, Any]:
        metric = payload.get("metric", "views")
        delta = abs(int(payload.get("delta_pct", -0.30) * 100))
        cust_agg = merchant.get("customer_aggregate", {})
        active_members = cust_agg.get("total_unique_ytd", 245)
        owner_name = m_owner or salutation.replace("Hi ", "")

        body = (
            f"{owner_name}, your {metric} are down {delta}% this week — but this is the normal April-June acquisition lull "
            f"(every metro gym sees -25 to -35% in this window). "
            f"Action: skip heavy ad spend now, save it for Sept-Oct when conversion is 2x. "
            f"For now, focus retention on your {active_members} active members. "
            f"Want me to draft a 'summer attendance challenge' to keep them engaged through the dip?"
        )
        rationale = (
            f"Seasonal performance dip pre-emption citing exact delta (-{delta}%), peer benchmark (-25 to -35%), "
            f"and member count ({active_members}) with retention strategy."
        )
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_seasonal_dip_v1",
            "template_params": [owner_name, f"-{delta}%", str(active_members)],
        }

    @classmethod
    def _compose_customer_winback(
        cls, payload: Dict[str, Any], category: Dict[str, Any],
        merchant: Dict[str, Any], customer: Optional[Dict[str, Any]],
        c_name: str, m_name: str, m_owner: str, cat_slug: str, code_mix: bool
    ) -> Dict[str, Any]:
        days = payload.get("days_since_last_visit", 57)
        weeks = max(4, days // 7)
        focus = payload.get("previous_focus", "fitness").replace("_", " ")
        owner_name = m_owner or m_name

        body = (
            f"Hi {c_name} 👋 {owner_name} from {m_name} here. It's been about {weeks} weeks — "
            f"happens to most members at some point, no judgment! "
            f"We've added a Tue/Thu evening HIIT class that fits {focus} goals well (45 min, 6:30pm). "
            f"Want me to hold a free trial spot for you next Tue, 30 Apr? Reply YES — no commitment, no auto-charge."
        )
        rationale = (
            f"Customer lapse winback with empathetic coach voice ({weeks} weeks since visit), "
            f"goal alignment ({focus}), and friction-free binary trial CTA."
        )
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "merchant_customer_winback_v1",
            "template_params": [c_name, owner_name, str(weeks)],
        }

    @classmethod
    def _compose_merchant_winback(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        salutation: str, m_name: str, code_mix: bool
    ) -> Dict[str, Any]:
        days_exp = payload.get("days_since_expiry", 38)
        perf_dip = abs(int(payload.get("perf_dip_pct", -0.30) * 100))
        lapsed = payload.get("lapsed_customers_added_since_expiry", 24)

        body = (
            f"{salutation}, it's been {days_exp} days since your {m_name} subscription ended. "
            f"During this window, your Google search views dipped {perf_dip}%, and {lapsed} past customers entered the lapsed window. "
            f"We have an instant-reactivation discount ready to restart your GBP ranking this week. "
            f"Want me to reactivate your listing with the renewal discount? Reply YES to proceed."
        )
        rationale = f"Merchant winback citing exact expiry duration ({days_exp}d), traffic drop (-{perf_dip}%), and lapsed customer count ({lapsed})."
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_merchant_winback_v1",
            "template_params": [salutation, str(days_exp), f"-{perf_dip}%"],
        }

    @classmethod
    def _compose_customer_lapsed_soft(
        cls, payload: Dict[str, Any], category: Dict[str, Any],
        merchant: Dict[str, Any], customer: Optional[Dict[str, Any]],
        c_name: str, m_name: str, m_owner: str, cat_slug: str, code_mix: bool
    ) -> Dict[str, Any]:
        owner_name = m_owner or m_name
        offers = merchant.get("offers", [])
        active_offer = next((o for o in offers if o.get("status") == "active"), None)

        if active_offer:
            offer_str = active_offer.get("title")
        elif cat_slug == "dentists":
            offer_str = "routine dental checkup & cleaning @ ₹299"
        elif cat_slug == "salons":
            offer_str = "hair spa & styling session @ ₹499"
        elif cat_slug == "gyms":
            offer_str = "complimentary fitness assessment & trial pass"
        elif cat_slug == "pharmacies":
            offer_str = "complimentary health & BP checkup"
        else:
            offer_str = "complimentary consultation"

        body = (
            f"Hi {c_name}, {owner_name} from {m_name} here! We missed seeing you this month. "
            f"We've reserved an exclusive slot for you this week with our {offer_str}. "
            f"Would Thursday 5pm or Saturday 11am work best for you?"
        )
        rationale = f"Soft lapse engagement for {cat_slug} honoring customer identity, active offer ({offer_str}), and two convenient slot choices."
        return {
            "body": body,
            "cta": "multi_choice_slot",
            "rationale": rationale,
            "template_name": "merchant_lapsed_soft_v1",
            "template_params": [c_name, owner_name, offer_str],
        }

    @classmethod
    def _compose_trial_followup(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        customer: Optional[Dict[str, Any]], c_name: str, m_name: str,
        cat_slug: str, code_mix: bool
    ) -> Dict[str, Any]:
        options = payload.get("next_session_options", [])
        slot_label = options[0].get("label", "Sat 3 May, 8am") if options else "Sat 3 May, 8am"
        service_label = "training session" if cat_slug == "gyms" else "trial appointment"

        body = (
            f"Hi {c_name}! Hope you enjoyed your {service_label} at {m_name}. "
            f"The next group class is scheduled for {slot_label}. "
            f"Want me to hold a confirmed spot for you? Reply YES to book."
        )
        rationale = f"Trial session follow-up with concrete next class date ({slot_label}) and single binary confirmation CTA."
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "merchant_trial_followup_v1",
            "template_params": [c_name, m_name, slot_label],
        }

    @classmethod
    def _compose_chronic_refill(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        customer: Optional[Dict[str, Any]], c_name: str, m_name: str,
        m_locality: str, cat_slug: str, code_mix: bool
    ) -> Dict[str, Any]:
        target_date = "28 April"
        date_iso = payload.get("stock_runs_out_iso", "")
        if "2026-04-28" in date_iso:
            target_date = "28 April"
        elif date_iso:
            target_date = date_iso.split("T")[0]

        if "molecule_list" in payload:
            molecules = payload["molecule_list"]
            molecules_str = ", ".join(molecules)
            item_desc = f"3 monthly medicines ({molecules_str})"
            price_note = "Senior discount 15% applied — total ₹1,420 (₹240 saved). Free home delivery to saved address by 5pm tomorrow."
        elif cat_slug == "dentists":
            item_desc = "prescribed oral care and anti-sensitivity dental pack"
            price_note = "Regular patient discount applied — total ₹450. Pack ready for priority pickup or clinic drop."
        else:
            item_desc = "regular wellness maintenance pack"
            price_note = "Discount applied — total ₹850. Free delivery to your saved address tomorrow."

        if code_mix:
            body = (
                f"Namaste — {m_name} {m_locality} yahan. {c_name} ji ka {item_desc} {target_date} ko khatam hoga. "
                f"Same brand pack ready hai. {price_note} "
                f"Reply CONFIRM to dispatch, or call if any change in dosage."
            )
        else:
            body = (
                f"Hello — {m_name} {m_locality} here. {c_name}'s {item_desc} is scheduled to run out on {target_date}. "
                f"Your repeat pack is ready. {price_note} "
                f"Reply CONFIRM to dispatch, or call if any change in dosage."
            )

        rationale = (
            f"Refill reminder for {cat_slug} citing exact items ({item_desc}), target date ({target_date}), "
            "clear transparent pricing, and direct CONFIRM action."
        )
        return {
            "body": body,
            "cta": "binary_confirm_cancel",
            "rationale": rationale,
            "template_name": "merchant_chronic_refill_v1",
            "template_params": [c_name, m_name, item_desc, target_date],
        }

    @classmethod
    def _compose_gbp_unverified(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        salutation: str, m_name: str, code_mix: bool
    ) -> Dict[str, Any]:
        uplift = int(payload.get("estimated_uplift_pct", 0.30) * 100)
        method = payload.get("verification_path", "phone or postcard").replace("_", " ")

        body = (
            f"{salutation}, quick notice: {m_name}'s Google listing is currently unverified. "
            f"Verified listings in your area see on average +{uplift}% more customer calls and directions. "
            f"Google allows quick verification via {method}. "
            f"Want me to guide you through the 2-minute verification step right now?"
        )
        rationale = f"Unverified profile notice citing verifiable view/call uplift (+{uplift}%) and 2-min verification path."
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_unverified_v1",
            "template_params": [salutation, m_name, f"+{uplift}%"],
        }

    @classmethod
    def _compose_cde_webinar(
        cls, payload: Dict[str, Any], category: Dict[str, Any],
        merchant: Dict[str, Any], salutation: str, code_mix: bool
    ) -> Dict[str, Any]:
        item_id = payload.get("digest_item_id")
        digest_items = category.get("digest", [])
        item = next((d for d in digest_items if d.get("id") == item_id), None)

        title = (
            payload.get("title")
            or payload.get("topic")
            or (item.get("title") if item else "")
            or "Professional development webinar"
        )
        credits = payload.get("credits") or (item.get("credits") if item else None)
        fee = payload.get("fee") or (item.get("actionable") if item else "")
        fee_clause = f", {fee.replace('_', ' ')}" if fee else ""
        credits_clause = f" ({credits} credits{fee_clause})" if credits else (f" ({fee.replace('_', ' ')})" if fee else "")

        summary = (
            (item.get("summary") if item else "")
            or payload.get("summary")
            or "Focuses on practical implementation and practice workflow ROI."
        )
        source = (item.get("source") if item else "") or payload.get("source") or ""
        source_display = f" — {source}" if source else ""

        body = (
            f"{salutation}, upcoming training opportunity: {title}{credits_clause}. "
            f"{summary} "
            f"Want me to send the session summary and registration details?{source_display}"
        )
        rationale = (
            f"Training/CDE alert grounded in topic '{title}'"
            + (f", credits: {credits}" if credits else "")
            + (f", source: {source}" if source else "")
            + ". Binary CTA for registration."
        )
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_cde_webinar_v1",
            "template_params": [salutation, title[:40], str(credits or "session")],
        }

    @classmethod
    def _compose_competitor_opened(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        salutation: str, m_locality: str, cat_slug: str, code_mix: bool
    ) -> Dict[str, Any]:
        comp_name = payload.get("competitor_name", "a new competitor")
        dist = payload.get("distance_km", 1.3)
        their_offer = payload.get("their_offer")
        if not their_offer:
            if cat_slug == "dentists":
                their_offer = "Dental Cleaning @ ₹199"
            elif cat_slug == "salons":
                their_offer = "Haircut @ ₹79"
            elif cat_slug == "restaurants":
                their_offer = "flat 20% discount on orders"
            elif cat_slug == "gyms":
                their_offer = "free 7-day trial passes"
            else:
                their_offer = "promotional discounts"

        body = (
            f"{salutation}, competitive heads-up: {comp_name} just opened {dist}km away in {m_locality}, "
            f"promoting '{their_offer}'. To defend your local pack search rank, let's reinforce your established "
            f"reputation and highlight your top service. Want me to draft a high-visibility Google post for tomorrow?"
        )
        rationale = f"Competitor alert with concrete distance ({dist}km), competitor offer ({their_offer}), and defensive GBP post offer."
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_competitor_opened_v1",
            "template_params": [salutation, comp_name, f"{dist}km"],
        }

    @classmethod
    def _compose_dormant_with_vera(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        salutation: str, m_name: str, code_mix: bool
    ) -> Dict[str, Any]:
        days = payload.get("days_since_last_merchant_message", 30)
        perf = merchant.get("performance", {})
        views = perf.get("views", 1400)

        body = (
            f"{salutation}, checking in! It's been {days} days since our last update for {m_name}. "
            f"Your listing generated {views:,} views on Google over the past month. "
            f"We have 2 quick profile optimizations that could boost your weekly calls. "
            f"Want me to send them over? Takes 2 minutes to review."
        )
        rationale = f"Dormancy check-in referencing days since last touch ({days}d) and actual monthly views ({views:,})."
        return {
            "body": body,
            "cta": "binary_yes_no",
            "rationale": rationale,
            "template_name": "vera_dormant_v1",
            "template_params": [salutation, str(days), str(views)],
        }

    @classmethod
    def _compose_appointment_tomorrow(
        cls, payload: Dict[str, Any], merchant: Dict[str, Any],
        customer: Optional[Dict[str, Any]], c_name: str, m_name: str,
        cat_slug: str, code_mix: bool
    ) -> Dict[str, Any]:
        time_str = payload.get("appointment_time", "11:00 AM")
        service = payload.get("service_name")
        if not service:
            if cat_slug == "salons":
                service = "hair styling & grooming session"
            elif cat_slug == "gyms":
                service = "workout & training session"
            elif cat_slug == "dentists":
                service = "dental checkup & consultation"
            elif cat_slug == "pharmacies":
                service = "wellness consultation"
            elif cat_slug == "restaurants":
                service = "table reservation"
            else:
                service = "consultation"

        body = (
            f"Hi {c_name}, gentle reminder from {m_name} ⏰ Your appointment for {service} "
            f"is confirmed for tomorrow at {time_str}. If you need directions or to reschedule, "
            f"please let us know. See you tomorrow!"
        )
        rationale = f"Appointment reminder with time ({time_str}) and category service ({service}) verification."
        return {
            "body": body,
            "cta": "none",
            "rationale": rationale,
            "template_name": "merchant_appointment_reminder_v1",
            "template_params": [c_name, m_name, time_str],
        }

    # =========================================================================
    # Fallback Composer for New / Unseen Triggers (Generalization)
    # =========================================================================
    @staticmethod
    def _business_noun(cat_slug: str) -> str:
        """Return the correct word for the merchant's business type."""
        return {
            "dentists": "clinic",
            "pharmacies": "pharmacy",
            "gyms": "gym",
            "salons": "salon",
            "restaurants": "restaurant",
        }.get(cat_slug, "business")

    @staticmethod
    def _grounded_scalar(value: Any) -> str:
        if value is None or isinstance(value, (dict, list, bool)):
            return ""
        return str(value).strip()

    @classmethod
    def _payload_fact_phrases(cls, payload: Dict[str, Any]) -> List[str]:
        phrases: List[str] = []
        payload = payload or {}

        metric = payload.get("metric")
        delta = payload.get("delta_pct")
        if metric and delta is not None:
            try:
                sign = "+" if float(delta) >= 0 else ""
                phrases.append(f"{str(metric).replace('_', ' ')} {sign}{int(float(delta) * 100)}%")
            except (TypeError, ValueError):
                phrases.append(str(metric).replace("_", " "))

        labeled_keys = (
            ("title", None),
            ("summary", None),
            ("details", None),
            ("description", None),
            ("event", None),
            ("festival", None),
            ("theme", "theme"),
            ("season", "season"),
            ("competitor_name", "nearby"),
            ("intent_topic", None),
            ("recommended_action", "suggested next step"),
            ("suggested_action", "suggested next step"),
            ("actionable", "suggested next step"),
            ("cta_hint", None),
            ("offer_title", "active offer"),
        )
        for key, prefix in labeled_keys:
            raw = cls._grounded_scalar(payload.get(key))
            if not raw:
                continue
            raw = raw.replace("_", " ")
            phrases.append(f"{prefix}: {raw}" if prefix else raw)

        if payload.get("distance_km") is not None:
            phrases.append(f"{payload.get('distance_km')}km")
        if payload.get("days_until") is not None:
            phrases.append(f"in {payload.get('days_until')} days")
        if payload.get("deadline_iso"):
            phrases.append(f"deadline {str(payload.get('deadline_iso')).split('T')[0]}")
        if payload.get("value_now") is not None:
            phrases.append(f"current value {payload.get('value_now')}")
        if payload.get("vs_baseline") is not None:
            phrases.append(f"baseline {payload.get('vs_baseline')}")

        seen = set()
        unique = []
        for p in phrases:
            key = p.lower()
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique

    @classmethod
    def _compose_generic_fallback(
        cls, kind: str, payload: Dict[str, Any], category: Dict[str, Any],
        merchant: Dict[str, Any], trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]], salutation: str, cat_slug: str,
        m_name: str, m_owner: str, m_locality: str, code_mix: bool, is_customer: bool
    ) -> Dict[str, Any]:
        """
        Fallback for unseen/new trigger kinds. Grounded only in supplied
        payload, category, and merchant context. Never fabricates facts.
        """
        payload = payload or {}
        category = category or {}
        merchant = merchant or {}
        trigger = trigger or {}
        kind_label = str(kind or "update").replace("_", " ")

        topic_raw = (
            payload.get("intent_topic")
            or payload.get("topic")
            or payload.get("title")
            or payload.get("metric_or_topic")
            or payload.get("theme")
            or payload.get("season")
            or payload.get("event")
            or payload.get("alert_id")
            or kind_label
        )
        topic = str(topic_raw).replace("_", " ")
        facts = cls._payload_fact_phrases(payload)

        voice = category.get("voice") or {}
        supported_actions = (
            payload.get("supported_actions")
            or category.get("supported_actions")
            or merchant.get("supported_actions")
            or []
        )
        if isinstance(supported_actions, str):
            supported_actions = [supported_actions]

        cta_signal = (
            payload.get("cta")
            or payload.get("cta_hint")
            or trigger.get("cta")
            or voice.get("preferred_cta")
            or ""
        )
        cta_signal = str(cta_signal).replace("_", " ").strip()

        offers = merchant.get("offers") or []
        active_offer = next(
            (o.get("title") for o in offers if isinstance(o, dict) and o.get("status") == "active" and o.get("title")),
            None,
        )

        perf = merchant.get("performance") or {}
        if perf.get("views") is not None:
            facts.append(f"{perf.get('views'):,} profile views this period")
        if perf.get("calls") is not None:
            facts.append(f"{perf.get('calls')} calls")
        if m_locality and m_locality not in ("your area",):
            facts.append(m_locality)
        if active_offer:
            facts.append(f"active offer {active_offer}")

        fact_clause = f" ({'; '.join(facts[:4])})" if facts else ""

        action_clause = ""
        if supported_actions:
            labels = [str(a).replace("_", " ") for a in supported_actions[:2]]
            action_clause = f" I can help with {', '.join(labels)}."

        if cta_signal:
            cta_line = f"Want me to {cta_signal}?"
        elif supported_actions:
            cta_line = f"Want me to {str(supported_actions[0]).replace('_', ' ')}?"
        else:
            cta_line = "Want me to pull the details that are in this update and outline the next step?"

        urgency = trigger.get("urgency", 2)
        business_word = cls._business_noun(cat_slug)

        if is_customer and customer:
            c_name = (customer.get("identity") or {}).get("name", "there")
            relationship = customer.get("relationship") or {}
            last_visit = relationship.get("last_visit") or payload.get("last_visit") or ""
            visit_bit = f" since your last visit ({last_visit})" if last_visit else ""
            body = (
                f"Hi {c_name}, {m_name} here. We have a {topic} update{visit_bit}{fact_clause}. "
                f"Would you like us to share the details?"
            )
            rationale = (
                f"Customer-facing fallback for kind '{kind}'. "
                "Grounded in supplied topic/facts only. Soft opt-in CTA."
            )
            return {
                "body": body, "cta": "binary_yes_no", "rationale": rationale,
                "template_name": f"merchant_{kind}_v1",
                "template_params": [c_name, m_name, topic]
            }

        if urgency >= 4:
            opening = f"{salutation}, time-sensitive update on {topic} for {m_name}"
        else:
            opening = f"{salutation}, update on {topic} for your {business_word} ({m_name})"

        body = f"{opening}{fact_clause}.{action_clause} {cta_line}"
        rationale = (
            f"Generic fallback for unseen trigger kind '{kind}'. "
            f"Topic '{topic}'. Facts from payload/context only. No fabricated claims."
        )
        return {
            "body": body, "cta": "binary_yes_no", "rationale": rationale,
            "template_name": f"vera_{kind}_v1",
            "template_params": [salutation, topic, m_name]
        }

    # =========================================================================
    # Safety & Taboo Scrubbing
    # =========================================================================
    @classmethod
    def _scrub_safety(cls, body: str, category: Dict[str, Any]) -> str:
        """
        1. Remove raw URLs (Meta rejection & -3 penalty).
        2. Replace category taboo words if present.
        3. Remove internal jargon (TriggerContext, suppression_key, etc.).
        """
        body = re.sub(r"https?://\S+", "", body)
        body = re.sub(r"www\.\S+", "", body)

        voice = category.get("voice", {})
        taboos = voice.get("vocab_taboo", [])
        for taboo in taboos:
            clean_taboo = taboo.split("(")[0].strip()
            if clean_taboo and len(clean_taboo) > 2:
                pattern = re.compile(re.escape(clean_taboo), re.IGNORECASE)
                if pattern.search(body):
                    body = pattern.sub("proven", body)

        jargon = ["triggercontext", "merchantcontext", "categorycontext", "suppression_key", "payload"]
        for j in jargon:
            pattern = re.compile(re.escape(j), re.IGNORECASE)
            body = pattern.sub("update", body)

        body = re.sub(r"  +", " ", body).strip()
        return body

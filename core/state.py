"""
State store for contexts, conversations, and suppressions.
Thread-safe, in-memory, deterministic lifecycle.
"""

from __future__ import annotations
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set, Tuple
from core.models import ConversationState, ConversationTurn


class StateStore:
    def __init__(self):
        self._lock = threading.RLock()
        # (scope, context_id) -> {"version": int, "payload": dict, "stored_at": str}
        self._contexts: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # conversation_id -> ConversationState
        self._conversations: Dict[str, ConversationState] = {}
        # Set of suppression keys that have already been fired
        self._suppressions: Set[str] = set()
        # Set of merchant_ids that have opted out / been suppressed
        self._suppressed_merchants: Set[str] = set()
        # Merchant auto-reply count tracking across conversations if needed
        self._merchant_auto_replies: Dict[str, int] = {}
        self._start_time = datetime.now(timezone.utc)

    @property
    def uptime_seconds(self) -> int:
        return int((datetime.now(timezone.utc) - self._start_time).total_seconds())

    def get_counts(self) -> Dict[str, int]:
        counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        with self._lock:
            for (scope, _), _ in self._contexts.items():
                if scope in counts:
                    counts[scope] += 1
                else:
                    counts[scope] = 1
        return counts

    def push_context(
        self, scope: str, context_id: str, version: int, payload: Dict[str, Any], delivered_at: str
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Idempotent context push.
        If existing version >= requested version, returns (False, "stale_version", details).
        If new or version > existing version, atomically updates and returns (True, ack_id, details).
        """
        valid_scopes = {"category", "merchant", "customer", "trigger"}
        if scope not in valid_scopes:
            return False, "invalid_scope", {"details": f"Scope must be one of {valid_scopes}"}

        now_iso = datetime.now(timezone.utc).isoformat() + "Z"
        key = (scope, context_id)

        with self._lock:
            current = self._contexts.get(key)
            if current is not None:
                cur_v = current["version"]
                if version <= cur_v:
                    return False, "stale_version", {"current_version": cur_v}

            # Atomically insert or replace
            ack_id = f"ack_{context_id}_v{version}"
            self._contexts[key] = {
                "version": version,
                "payload": payload,
                "stored_at": now_iso,
                "delivered_at": delivered_at,
            }
            return True, ack_id, {"stored_at": now_iso}

    def get_context(self, scope: str, context_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._contexts.get((scope, context_id))
            return record["payload"] if record else None

    def get_all_contexts_by_scope(self, scope: str) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            res = {}
            for (sc, cid), record in self._contexts.items():
                if sc == scope:
                    res[cid] = record["payload"]
            return res

    def is_suppressed(self, suppression_key: str) -> bool:
        if not suppression_key:
            return False
        with self._lock:
            return suppression_key in self._suppressions

    def add_suppression(self, suppression_key: str):
        if suppression_key:
            with self._lock:
                self._suppressions.add(suppression_key)

    def is_merchant_suppressed(self, merchant_id: str) -> bool:
        if not merchant_id:
            return False
        with self._lock:
            return merchant_id in self._suppressed_merchants

    def suppress_merchant(self, merchant_id: str):
        if merchant_id:
            with self._lock:
                self._suppressed_merchants.add(merchant_id)

    def get_or_create_conversation(
        self,
        conversation_id: str,
        merchant_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        trigger_id: Optional[str] = None,
    ) -> ConversationState:
        with self._lock:
            if conversation_id not in self._conversations:
                self._conversations[conversation_id] = ConversationState(
                    conversation_id=conversation_id,
                    merchant_id=merchant_id,
                    customer_id=customer_id,
                    trigger_id=trigger_id,
                )
            conv = self._conversations[conversation_id]
            if merchant_id and not conv.merchant_id:
                conv.merchant_id = merchant_id
            if customer_id and not conv.customer_id:
                conv.customer_id = customer_id
            if trigger_id and not conv.trigger_id:
                conv.trigger_id = trigger_id
            return conv

    def record_turn(
        self,
        conversation_id: str,
        from_role: str,
        message: str,
        timestamp: str,
        action_taken: Optional[str] = None,
        bot_body: Optional[str] = None,
    ):
        with self._lock:
            conv = self.get_or_create_conversation(conversation_id)
            conv.turns.append(
                ConversationTurn(
                    from_role=from_role,
                    message=message,
                    timestamp=timestamp,
                    action_taken=action_taken,
                )
            )
            if bot_body:
                conv.last_bot_body = bot_body

    def record_auto_reply(self, merchant_id: Optional[str]) -> int:
        if not merchant_id:
            return 1
        with self._lock:
            count = self._merchant_auto_replies.get(merchant_id, 0) + 1
            self._merchant_auto_replies[merchant_id] = count
            return count

    def reset(self):
        with self._lock:
            self._contexts.clear()
            self._conversations.clear()
            self._suppressions.clear()
            self._suppressed_merchants.clear()
            self._merchant_auto_replies.clear()
            self._start_time = datetime.now(timezone.utc)


# Global singleton state store
store = StateStore()

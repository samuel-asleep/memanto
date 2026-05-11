"""A LangGraph customer support workflow backed by Memanto long-term memory.

The graph state models only the active turn. Durable user facts and preferences
are written to and recalled from Memanto, so they survive new LangGraph graph
instances, new thread ids, and disjoint sessions.
"""

from __future__ import annotations

import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from memanto_memory import MemantoLongTermMemory


class SupportState(TypedDict, total=False):
    """Transient LangGraph state for one support turn."""

    customer_id: str
    user_message: str
    recalled_memories: list[str]
    stored_memory_ids: list[str]
    response: str


_NAME_RE = re.compile(r"(?:i am|i'm|my name is)\s+([A-Z][a-z]+)", re.IGNORECASE)
_PLAN_RE = re.compile(r"\b(?:plan|tier)\s+(?:is\s+)?(free|pro|team|enterprise)\b", re.IGNORECASE)
_INVOICE_RE = re.compile(r"\b(?:invoice|inv)[-\s#:]*(INV[-\s]?\d+)\b", re.IGNORECASE)
_REFUND_RE = re.compile(r"prefer\s+refunds?\s+(?:as|to|via)\s+([^.;,]+)", re.IGNORECASE)


def build_support_graph(memory: MemantoLongTermMemory):
    """Compile the support graph with a Memanto memory adapter injected."""

    def recall_customer_context(state: SupportState) -> SupportState:
        """Pull cross-session memories before generating the response."""
        customer_id = state["customer_id"]
        user_message = state["user_message"]
        query = (
            f"Customer {customer_id} preferences, subscription plan, billing "
            f"history, refund method, and issue context relevant to: {user_message}"
        )
        recalled = memory.recall(query, limit=5)
        return {"recalled_memories": [item.as_bullet() for item in recalled]}

    def capture_new_memories(state: SupportState) -> SupportState:
        """Extract explicit user facts from this turn and persist them in Memanto."""
        stored_ids: list[str] = []
        for candidate in _extract_candidate_memories(
            customer_id=state["customer_id"],
            message=state["user_message"],
        ):
            stored_ids.append(memory.remember(**candidate))
        return {"stored_memory_ids": stored_ids}

    def draft_support_reply(state: SupportState) -> SupportState:
        """Create a support response grounded in recalled Memanto memories."""
        memories = state.get("recalled_memories", [])
        if memories:
            memory_context = "\n".join(memories)
            response = (
                "I found cross-session context in Memanto and will use it here:\n"
                f"{memory_context}\n\n"
                "Recommended action: acknowledge the billing issue, apply the "
                "customer's remembered preferences, and avoid asking for details "
                "that Memanto already recalled."
            )
        else:
            response = (
                "I do not have prior Memanto memories for this request yet. "
                "I will handle the current message and store any explicit facts "
                "the customer shared for future sessions."
            )

        stored_ids = state.get("stored_memory_ids", [])
        if stored_ids:
            response += f"\n\nStored {len(stored_ids)} new memory item(s) in Memanto."

        return {"response": response}

    builder = StateGraph(SupportState)
    builder.add_node("recall_customer_context", recall_customer_context)
    builder.add_node("capture_new_memories", capture_new_memories)
    builder.add_node("draft_support_reply", draft_support_reply)

    builder.add_edge(START, "recall_customer_context")
    builder.add_edge("recall_customer_context", "capture_new_memories")
    builder.add_edge("capture_new_memories", "draft_support_reply")
    builder.add_edge("draft_support_reply", END)
    return builder.compile()


def _extract_candidate_memories(customer_id: str, message: str) -> list[dict]:
    """Small deterministic extractor for demo purposes.

    Production agents can replace this with an LLM extraction node while keeping
    the same Memanto ``remember`` calls.
    """
    candidates: list[dict] = []

    if match := _NAME_RE.search(message):
        name = match.group(1).title()
        candidates.append(
            {
                "memory_type": "fact",
                "title": f"{customer_id} name",
                "content": f"Customer {customer_id}'s first name is {name}.",
                "confidence": 0.98,
                "tags": ["customer-profile", customer_id],
            }
        )

    if match := _PLAN_RE.search(message):
        plan = match.group(1).title()
        candidates.append(
            {
                "memory_type": "fact",
                "title": f"{customer_id} plan",
                "content": f"Customer {customer_id} is on the {plan} plan.",
                "confidence": 0.95,
                "tags": ["subscription", customer_id],
            }
        )

    if match := _INVOICE_RE.search(message):
        invoice = match.group(1).upper().replace(" ", "-")
        candidates.append(
            {
                "memory_type": "event",
                "title": f"{customer_id} billing issue {invoice}",
                "content": f"Customer {customer_id} reported a billing issue with invoice {invoice}.",
                "confidence": 0.92,
                "tags": ["billing", "invoice", customer_id],
            }
        )

    if match := _REFUND_RE.search(message):
        refund_method = match.group(1).strip().rstrip(".")
        candidates.append(
            {
                "memory_type": "preference",
                "title": f"{customer_id} refund preference",
                "content": f"Customer {customer_id} prefers refunds as {refund_method}.",
                "confidence": 0.96,
                "tags": ["refund", "preference", customer_id],
            }
        )

    return candidates

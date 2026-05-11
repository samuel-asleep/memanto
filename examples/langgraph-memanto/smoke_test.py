"""Offline acceptance test for the LangGraph + Memanto example.

This test uses a tiny in-memory stand-in for Memanto so reviewers can validate
LangGraph wiring and the cross-session contract without a Moorcheh API key. Run
``python smoke_test.py`` from this directory or from the repository root.
"""

from __future__ import annotations

from dataclasses import dataclass

from workflow import build_support_graph

CUSTOMER_ID = "cust-maya-042"
YESTERDAY_MESSAGE = (
    "Hi, I'm Maya. My plan is Pro. I prefer refunds as account credit, "
    "and I have a billing issue with invoice INV-4421."
)
TODAY_MESSAGE = "Can you help with my invoice? Please use my usual refund method."


@dataclass(frozen=True)
class FakeRetrievedMemory:
    """Small object matching the ``RetrievedMemory.as_bullet`` protocol."""

    memory_type: str
    title: str
    content: str
    confidence: float
    tags: list[str]

    def as_bullet(self) -> str:
        return (
            f"- [{self.memory_type}] {self.title}: {self.content} "
            f"(confidence={self.confidence} tags={','.join(self.tags)})"
        )


class FakePersistentMemory:
    """Persistent fake that stores memories outside any LangGraph state."""

    def __init__(self) -> None:
        self._items: list[dict] = []

    def remember(self, **candidate: object) -> str:
        self._items.append(dict(candidate))
        return f"fake-memory-{len(self._items)}"

    def recall(
        self,
        query: str,
        *,
        limit: int = 5,
        memory_types: list[str] | None = None,
    ) -> list[FakeRetrievedMemory]:
        del query, memory_types
        return [
            FakeRetrievedMemory(
                memory_type=str(item["memory_type"]),
                title=str(item["title"]),
                content=str(item["content"]),
                confidence=float(item["confidence"]),
                tags=list(item["tags"]),
            )
            for item in self._items[:limit]
        ]


def test_cross_session_recall_contract() -> None:
    """Prove yesterday's facts are recalled by a fresh graph today."""
    persistent_memory = FakePersistentMemory()

    yesterday_graph = build_support_graph(persistent_memory)  # type: ignore[arg-type]
    yesterday_state = {
        "customer_id": CUSTOMER_ID,
        "user_message": YESTERDAY_MESSAGE,
    }
    yesterday_result = yesterday_graph.invoke(
        yesterday_state,
        config={"configurable": {"thread_id": "offline-yesterday"}},
    )

    assert yesterday_state.keys() == {"customer_id", "user_message"}
    assert yesterday_result["recalled_memories"] == []
    assert len(yesterday_result["stored_memory_ids"]) == 4

    today_graph = build_support_graph(persistent_memory)  # type: ignore[arg-type]
    today_state = {
        "customer_id": CUSTOMER_ID,
        "user_message": TODAY_MESSAGE,
    }
    today_result = today_graph.invoke(
        today_state,
        config={"configurable": {"thread_id": "offline-today"}},
    )

    recalled_text = "\n".join(today_result["recalled_memories"])
    assert today_state.keys() == {"customer_id", "user_message"}
    assert "first name is Maya" in recalled_text
    assert "Pro plan" in recalled_text
    assert "invoice INV-4421" in recalled_text
    assert "prefers refunds as account credit" in recalled_text
    assert today_result["stored_memory_ids"] == []
    assert "cross-session context in Memanto" in today_result["response"]


if __name__ == "__main__":
    test_cross_session_recall_contract()
    print("✅ Offline cross-session recall contract passed.")

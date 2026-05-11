"""Run the LangGraph + Memanto cross-session recall demo.

Session 1 simulates yesterday: the graph stores durable customer facts in
Memanto. Session 2 simulates today: a new graph instance and new thread id start
with no prior LangGraph state, then recall yesterday's memories from Memanto.
"""

from __future__ import annotations

import os
import time

from dotenv import load_dotenv
from memanto_memory import MemantoLongTermMemory
from workflow import build_support_graph

CUSTOMER_ID = "cust-maya-042"
YESTERDAY_THREAD = "support-thread-yesterday"
TODAY_THREAD = "support-thread-today"


def main() -> None:
    load_dotenv()
    api_key = os.getenv("MOORCHEH_API_KEY")
    if not api_key:
        raise RuntimeError(
            "MOORCHEH_API_KEY is required. Copy .env.example to .env and add "
            "your key, or export MOORCHEH_API_KEY before running this demo."
        )

    agent_id = os.getenv("MEMANTO_LANGGRAPH_AGENT_ID", "langgraph-support-demo")
    wait_seconds = float(os.getenv("MEMANTO_INDEX_WAIT_SECONDS", "2"))

    memory = MemantoLongTermMemory(api_key=api_key, agent_id=agent_id)

    print("\n=== Session 1: yesterday, empty LangGraph state ===")
    yesterday_graph = build_support_graph(memory)
    yesterday_result = yesterday_graph.invoke(
        {
            "customer_id": CUSTOMER_ID,
            "user_message": (
                "Hi, I'm Maya. My plan is Pro. I prefer refunds as account "
                "credit, and I have a billing issue with invoice INV-4421."
            ),
        },
        config={"configurable": {"thread_id": YESTERDAY_THREAD}},
    )
    print(yesterday_result["response"])
    print(f"Stored memory ids: {yesterday_result.get('stored_memory_ids', [])}")

    if wait_seconds > 0:
        print(f"\nWaiting {wait_seconds:g}s for the remote memory index...")
        time.sleep(wait_seconds)

    print("\n=== Session 2: today, new graph + new thread id ===")
    print(
        "Initial state only contains customer_id and user_message; no prior "
        "LangGraph messages or checkpoints are supplied."
    )
    today_graph = build_support_graph(memory)
    today_result = today_graph.invoke(
        {
            "customer_id": CUSTOMER_ID,
            "user_message": "Can you help with my invoice? Please use my usual refund method.",
        },
        config={"configurable": {"thread_id": TODAY_THREAD}},
    )
    print(today_result["response"])
    print("\nRecalled memories from Memanto:")
    for item in today_result.get("recalled_memories", []):
        print(item)


if __name__ == "__main__":
    main()

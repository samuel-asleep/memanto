"""Run a two-session LangGraph + Memanto continuity demo."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

from dotenv import load_dotenv
from memory_graph import MemantoSessionManager, MemoryAwareSupportAssistant


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Demonstrate LangGraph + Memanto cross-session continuity"
    )
    parser.add_argument(
        "--agent-id",
        default="langgraph-support-demo",
        help="Memanto agent ID (shared memory namespace)",
    )
    parser.add_argument(
        "--user-id",
        default="sam-user",
        help="Synthetic user ID used for demo",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    api_key = os.getenv("MOORCHEH_API_KEY")
    if not api_key or not api_key.strip():
        print("ERROR: Set MOORCHEH_API_KEY in your environment or .env file.", file=sys.stderr)
        return 1

    args = parse_args()

    # Session A: store a memory from explicit user preference
    manager_a = MemantoSessionManager(api_key=api_key, agent_id=args.agent_id)
    client_a = manager_a.setup()
    assistant_a = MemoryAwareSupportAssistant(client=client_a, agent_id=args.agent_id)

    thread_a = f"thread-{uuid.uuid4().hex[:8]}"
    try:
        turn_a = assistant_a.run(
            user_id=args.user_id,
            thread_id=thread_a,
            message=(
                "I prefer concise bullet-point updates. Call me Sam in future replies."
            ),
        )
    finally:
        manager_a.teardown()

    # Session B: fresh session and thread, retrieve memory from session A
    manager_b = MemantoSessionManager(api_key=api_key, agent_id=args.agent_id)
    client_b = manager_b.setup()
    assistant_b = MemoryAwareSupportAssistant(client=client_b, agent_id=args.agent_id)

    thread_b = f"thread-{uuid.uuid4().hex[:8]}"
    try:
        turn_b = assistant_b.run(
            user_id=args.user_id,
            thread_id=thread_b,
            message="Can you summarize this week's customer support metrics?",
        )
    finally:
        manager_b.teardown()

    payload = {
        "session_a": {
            "thread_id": thread_a,
            "response": turn_a.get("response"),
            "stored_memory": bool(turn_a.get("memory_to_store")),
        },
        "session_b": {
            "thread_id": thread_b,
            "response": turn_b.get("response"),
            "retrieved_count": len(turn_b.get("recalled_memories", [])),
            "retrieved_preview": [
                {
                    "type": item.get("type"),
                    "content": item.get("content"),
                }
                for item in turn_b.get("recalled_memories", [])[:3]
            ],
        },
    }

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

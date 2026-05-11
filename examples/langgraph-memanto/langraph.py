#!/usr/bin/env python3
"""LangGraph + Memanto cross-session customer support memory demo."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from memanto.cli.client.sdk_client import SdkClient
from dotenv import load_dotenv


class SupportState(TypedDict, total=False):
    user_message: str
    session_label: str
    recalled_memories: list[dict[str, Any]]
    recalled_summary: str
    response: str
    write_memory: bool
    memory_candidates: list[dict[str, Any]]
    stored_memory_ids: list[str]


def _truncate(text: str, max_len: int = 90) -> str:
    return text if len(text) <= max_len else f"{text[: max_len - 3]}..."


def _extract_name(text: str) -> str | None:
    match = re.search(r"\bmy name is\s+([a-zA-Z][a-zA-Z\s\-']{0,40})", text, re.I)
    if not match:
        return None
    return match.group(1).strip().title()


def _extract_urgent_channel(text: str) -> str | None:
    lowered = text.lower()
    if "urgent" not in lowered and "update" not in lowered:
        return None
    if "sms" in lowered or "text" in lowered:
        return "SMS"
    if "email" in lowered:
        return "email"
    if "phone" in lowered or "call" in lowered:
        return "phone call"
    return None


def _format_memories(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return "No relevant long-term memories found."

    lines = [f"Found {len(memories)} relevant memory item(s):"]
    for idx, memory in enumerate(memories[:5], start=1):
        mem_type = memory.get("type", "unknown")
        title = memory.get("title", "Untitled")
        content = memory.get("content", "")
        lines.append(f"  {idx}. [{mem_type}] {title} — {_truncate(content)}")
    return "\n".join(lines)


def _infer_urgent_channel(memories: list[dict[str, Any]]) -> str | None:
    for memory in memories:
        joined = f"{memory.get('title', '')} {memory.get('content', '')}".lower()
        if "sms" in joined or "text" in joined:
            return "SMS"
        if "email" in joined:
            return "email"
        if "phone" in joined or "call" in joined:
            return "phone call"
    return None


def _build_memory_candidates(message: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    name = _extract_name(message)
    if name:
        candidates.append(
            {
                "memory_type": "fact",
                "title": "Customer name",
                "content": f"Customer name is {name}.",
                "confidence": 0.99,
                "tags": ["customer", "identity"],
            }
        )

    channel = _extract_urgent_channel(message)
    if channel:
        candidates.append(
            {
                "memory_type": "preference",
                "title": "Urgent contact preference",
                "content": f"Customer prefers {channel} for urgent updates.",
                "confidence": 0.95,
                "tags": ["customer", "preference", "urgent-updates"],
            }
        )

    return candidates


def _needs_memory_write(state: SupportState) -> Literal["write", "done"]:
    return "write" if state.get("write_memory") else "done"


class MemantoMemoryLayer:
    """Small wrapper around Memanto SDK for this LangGraph demo."""

    def __init__(self, api_key: str, agent_id: str) -> None:
        self.agent_id = agent_id
        self.client = SdkClient(api_key=api_key)

    def setup_session(self) -> None:
        try:
            self.client.create_agent(
                agent_id=self.agent_id,
                pattern="support",
                description="LangGraph support agent demo with persistent memory",
            )
            print(f"Created Memanto agent: {self.agent_id}")
        except Exception:
            print(f"Reusing existing Memanto agent: {self.agent_id}")

        self.client.activate_agent(self.agent_id, duration_hours=6)
        print(f"Activated session for agent: {self.agent_id}")

    def close_session(self) -> None:
        try:
            self.client.deactivate_agent(self.agent_id)
            print(f"Closed session for agent: {self.agent_id}")
        except Exception as exc:
            print(f"Warning: failed to close session cleanly: {exc}")

    def recall(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        result = self.client.recall(agent_id=self.agent_id, query=query, limit=limit)
        memories = result.get("memories", [])
        if not isinstance(memories, list):
            return []
        return [memory for memory in memories if isinstance(memory, dict)]

    def remember(self, memory: dict[str, Any]) -> str:
        result = self.client.remember(
            agent_id=self.agent_id,
            memory_type=memory["memory_type"],
            title=memory["title"],
            content=memory["content"],
            confidence=memory.get("confidence", 0.85),
            tags=memory.get("tags", []),
            source="langgraph-support-agent",
            provenance="explicit_statement",
        )
        return str(result.get("memory_id", ""))


def build_graph(memory_layer: MemantoMemoryLayer):
    def recall_node(state: SupportState) -> SupportState:
        message = state["user_message"]
        query = (
            "customer preferences, identity, communication channels, urgent updates "
            f"related to: {message}"
        )
        memories = memory_layer.recall(query=query, limit=5)
        return {
            "recalled_memories": memories,
            "recalled_summary": _format_memories(memories),
        }

    def respond_node(state: SupportState) -> SupportState:
        message = state["user_message"]
        memories = state.get("recalled_memories", [])

        lowered = message.lower()
        asks_for_past_pref = (
            "remind" in lowered
            or "yesterday" in lowered
            or "preference" in lowered
            or "prefer" in lowered
        )

        if asks_for_past_pref:
            channel = _infer_urgent_channel(memories)
            if channel:
                response = (
                    "From long-term memory (outside this thread), "
                    f"you prefer {channel} for urgent updates."
                )
            else:
                response = (
                    "I could not find a stored urgent-contact preference yet. "
                    "Tell me your preference and I will store it for future sessions."
                )
            return {
                "response": response,
                "write_memory": False,
                "memory_candidates": [],
            }

        candidates = _build_memory_candidates(message)
        if candidates:
            response = (
                "Got it — I stored your details in Memanto long-term memory so "
                "I can recall them in a future session."
            )
            return {
                "response": response,
                "write_memory": True,
                "memory_candidates": candidates,
            }

        response = (
            "I can help with support questions. If you share your preferences "
            "or profile details, I will store them for cross-session recall."
        )
        return {"response": response, "write_memory": False, "memory_candidates": []}

    def write_memory_node(state: SupportState) -> SupportState:
        stored_ids: list[str] = []
        for candidate in state.get("memory_candidates", []):
            memory_id = memory_layer.remember(candidate)
            if memory_id:
                stored_ids.append(memory_id)
        return {"stored_memory_ids": stored_ids}

    workflow = StateGraph(SupportState)
    workflow.add_node("recall", recall_node)
    workflow.add_node("respond", respond_node)
    workflow.add_node("write_memory", write_memory_node)

    workflow.add_edge(START, "recall")
    workflow.add_edge("recall", "respond")
    workflow.add_conditional_edges(
        "respond",
        _needs_memory_write,
        {
            "write": "write_memory",
            "done": END,
        },
    )
    workflow.add_edge("write_memory", END)

    return workflow.compile()


def _scenario_message(scenario: str, custom_message: str | None) -> tuple[str, str]:
    if custom_message:
        return custom_message, "custom"

    if scenario == "day1":
        return (
            "Hi, my name is Sarah. For urgent updates, I prefer SMS instead of email.",
            "day1",
        )
    if scenario == "day2":
        return (
            "Can you remind me from yesterday what channel I prefer for urgent updates?",
            "day2",
        )
    raise ValueError(f"Unsupported scenario: {scenario}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LangGraph + Memanto demo for cross-session memory recall."
    )
    parser.add_argument(
        "--agent-id",
        default="langgraph-support-demo",
        help="Memanto agent id used as the persistent memory namespace.",
    )
    parser.add_argument(
        "--scenario",
        choices=["day1", "day2"],
        default="day1",
        help="Preset conversation turn to run. Execute day1 first, day2 second.",
    )
    parser.add_argument(
        "--message",
        help="Custom user message. If provided, it overrides --scenario text.",
    )
    return parser.parse_args()


def _load_local_env() -> None:
    script_dir = Path(__file__).resolve().parent
    load_dotenv(script_dir / ".env")
    load_dotenv()


def _print_next_step_hint(agent_id: str, scenario: str) -> None:
    if scenario == "day1":
        print("\nTip: run day2 next to verify cross-session recall:")
        print(f"python examples/langgraph-memanto/langraph.py --scenario day2 --agent-id {agent_id}")


def main() -> None:
    _load_local_env()
    args = _parse_args()
    api_key = os.environ.get("MOORCHEH_API_KEY") or os.environ.get("MEMANTO_API_KEY")
    if not api_key:
        print("Error: MOORCHEH_API_KEY or MEMANTO_API_KEY is not set.")
        print(
            "Create /home/runner/work/memanto/memanto/examples/langgraph-memanto/.env "
            "with MOORCHEH_API_KEY=<your-key> (or MEMANTO_API_KEY=<your-key>)."
        )
        sys.exit(1)

    user_message, session_label = _scenario_message(args.scenario, args.message)

    memory_layer = MemantoMemoryLayer(api_key=api_key, agent_id=args.agent_id)
    memory_layer.setup_session()

    try:
        app = build_graph(memory_layer)
        result = app.invoke(
            {
                "user_message": user_message,
                "session_label": session_label,
            }
        )

        print("\n=== LangGraph Turn ===")
        print(f"Session label: {session_label}")
        print(f"User message: {user_message}")
        print("\n=== Recall Step ===")
        print(result.get("recalled_summary", "No recall summary available."))
        print("\n=== Agent Response ===")
        print(result.get("response", "No response generated."))

        stored = result.get("stored_memory_ids", [])
        if stored:
            print("\n=== Stored Memory IDs ===")
            for memory_id in stored:
                print(f"- {memory_id}")
        _print_next_step_hint(args.agent_id, args.scenario)
    finally:
        memory_layer.close_session()


if __name__ == "__main__":
    main()

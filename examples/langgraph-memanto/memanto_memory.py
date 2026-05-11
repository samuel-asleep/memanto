"""Memanto adapter used by the LangGraph example.

This module intentionally keeps Memanto calls outside the LangGraph state object.
The graph only receives transient recall snippets; the durable memory layer is the
Memanto namespace associated with ``agent_id``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memanto.app.utils.errors import AgentAlreadyExistsError, AgentNotFoundError
from memanto.cli.client.sdk_client import SdkClient


@dataclass(frozen=True)
class RetrievedMemory:
    """A normalized memory returned from Memanto semantic search."""

    title: str
    content: str
    memory_type: str
    confidence: float | str
    tags: list[str]

    def as_bullet(self) -> str:
        """Render the memory as a compact prompt/context bullet."""
        tag_suffix = f" tags={','.join(self.tags)}" if self.tags else ""
        return (
            f"- [{self.memory_type}] {self.title}: {self.content} "
            f"(confidence={self.confidence}{tag_suffix})"
        )


class MemantoLongTermMemory:
    """Thin wrapper around Memanto's SDK client for LangGraph nodes."""

    def __init__(self, api_key: str, agent_id: str) -> None:
        self.agent_id = agent_id
        self._client = SdkClient(api_key=api_key)
        self._ensure_agent_session(agent_id)

    def remember(
        self,
        *,
        memory_type: str,
        title: str,
        content: str,
        confidence: float = 0.9,
        tags: list[str] | None = None,
        source: str = "langgraph-support-agent",
    ) -> str:
        """Persist a single long-term memory and return its Memanto id."""
        result = self._client.remember(
            agent_id=self.agent_id,
            memory_type=memory_type,
            title=title,
            content=content,
            confidence=confidence,
            tags=tags or [],
            source=source,
            provenance="explicit_statement",
        )
        return str(result["memory_id"])

    def recall(
        self,
        query: str,
        *,
        limit: int = 5,
        memory_types: list[str] | None = None,
    ) -> list[RetrievedMemory]:
        """Retrieve semantically relevant memories from Memanto."""
        result = self._client.recall(
            agent_id=self.agent_id,
            query=query,
            limit=limit,
            type=memory_types,
        )
        return [self._normalize_memory(raw) for raw in result.get("memories", [])]

    def _ensure_agent_session(self, agent_id: str) -> None:
        """Create the Memanto agent if needed, then activate a fresh session."""
        try:
            self._client.create_agent(
                agent_id=agent_id,
                pattern="support",
                description=(
                    "LangGraph customer support demo that stores durable "
                    "customer preferences and issue context in Memanto."
                ),
            )
        except AgentAlreadyExistsError:
            pass
        except Exception as exc:
            # Some older Memanto builds raise a generic error for duplicates.
            # Only fall through when the agent already exists; otherwise re-raise.
            if "already exists" not in str(exc).lower():
                raise

        try:
            self._client.activate_agent(agent_id)
        except AgentNotFoundError:
            self._client.create_agent(agent_id=agent_id, pattern="support")
            self._client.activate_agent(agent_id)

    @staticmethod
    def _normalize_memory(raw: dict[str, Any]) -> RetrievedMemory:
        tags = raw.get("tags") or []
        if isinstance(tags, str):
            tags = [tag.strip() for tag in tags.split(",") if tag.strip()]

        return RetrievedMemory(
            title=str(raw.get("title") or "Untitled"),
            content=str(raw.get("content") or ""),
            memory_type=str(raw.get("type") or raw.get("memory_type") or "unknown"),
            confidence=raw.get("confidence", "n/a"),
            tags=list(tags),
        )

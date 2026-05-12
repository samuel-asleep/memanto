"""LangGraph + Memanto long-term memory example."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from openai import OpenAI
from typing_extensions import TypedDict

from memanto.cli.client.sdk_client import SdkClient

logger = logging.getLogger(__name__)

MAX_USER_ID_LENGTH = 40
MAX_MEMORY_CONTENT_LENGTH = 500
MAX_MEMORY_TITLE_LENGTH = 100
ALLOWED_USER_ID_CHARS = "-_"
DEFAULT_SESSION_DURATION_HOURS = 6
DEFAULT_RECALL_LIMIT = 6
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"


class AssistantState(TypedDict, total=False):
    """State carried across LangGraph nodes."""

    user_id: str
    thread_id: str
    user_message: str
    intent: str
    recall_query: str
    recalled_memories: list[dict[str, Any]]
    response_style: str
    response: str
    should_store: bool
    memory_to_store: dict[str, Any]


@dataclass(slots=True)
class MemantoSessionManager:
    """Creates and activates a Memanto agent session."""

    api_key: str
    agent_id: str
    pattern: str = "support"
    session_duration_hours: int = DEFAULT_SESSION_DURATION_HOURS
    client: SdkClient = field(init=False)

    def __post_init__(self) -> None:
        self.client = SdkClient(api_key=self.api_key)

    def setup(self) -> SdkClient:
        """Create agent if needed and activate a fresh session."""
        try:
            self.client.create_agent(
                agent_id=self.agent_id,
                pattern=self.pattern,
                description=(
                    "LangGraph customer support assistant using Memanto for "
                    "persistent long-term memory"
                ),
            )
            logger.info("Created Memanto agent '%s'", self.agent_id)
        except Exception:
            try:
                self.client.get_agent(self.agent_id)
                logger.info("Memanto agent '%s' already exists, reusing", self.agent_id)
            except Exception as get_exc:
                logger.exception("Failed to create Memanto agent '%s'", self.agent_id)
                raise RuntimeError(
                    f"Unable to create or reuse Memanto agent '{self.agent_id}'"
                ) from get_exc

        self.client.activate_agent(
            self.agent_id,
            duration_hours=self.session_duration_hours,
        )
        logger.info("Activated session for agent '%s'", self.agent_id)
        return self.client

    def teardown(self) -> None:
        """Deactivate active Memanto session."""
        try:
            self.client.deactivate_agent(self.agent_id)
        except Exception as exc:
            logger.exception("Failed to deactivate agent '%s'", self.agent_id)
            raise RuntimeError(
                f"Unable to deactivate Memanto agent '{self.agent_id}'"
            ) from exc


class MemoryAwareSupportAssistant:
    """LangGraph assistant with Memanto-backed long-term memory."""

    def __init__(
        self,
        client: SdkClient,
        agent_id: str,
        llm_client: OpenAI | None = None,
        llm_model: str | None = None,
    ) -> None:
        self.client = client
        self.agent_id = agent_id
        self.llm_model = cast(
            str, llm_model or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        )
        self.llm_client = llm_client
        if self.llm_client is None and os.getenv("OPENAI_API_KEY"):
            self.llm_client = OpenAI()
        self.graph: Any = self._build_graph()

    def _build_graph(self) -> Any:
        workflow: Any = StateGraph(AssistantState)

        workflow.add_node("retrieve_context", self.retrieve_context)
        workflow.add_node("classify_intent", self.classify_intent)
        workflow.add_node("route_support", self.route_support)
        workflow.add_node("route_research", self.route_research)
        workflow.add_node("compose_response", self.compose_response)
        workflow.add_node("store_memory", self.store_memory)

        workflow.add_edge(START, "retrieve_context")
        workflow.add_edge("retrieve_context", "classify_intent")

        workflow.add_conditional_edges(
            "classify_intent",
            self.pick_route,
            {
                "support": "route_support",
                "research": "route_research",
            },
        )

        workflow.add_edge("route_support", "compose_response")
        workflow.add_edge("route_research", "compose_response")

        workflow.add_conditional_edges(
            "compose_response",
            self.should_store,
            {
                "store": "store_memory",
                "finish": END,
            },
        )

        workflow.add_edge("store_memory", END)

        return workflow.compile()

    def retrieve_context(self, state: AssistantState) -> AssistantState:
        """Retrieve long-term memories at the start of each thread."""
        query = self._build_recall_query(
            user_id=state["user_id"],
            user_message=state["user_message"],
        )
        result = self.client.recall(
            agent_id=self.agent_id,
            query=query,
            limit=DEFAULT_RECALL_LIMIT,
        )

        memories = result.get("memories", [])
        style = self._infer_style(memories)

        return {
            "recall_query": query,
            "recalled_memories": memories,
            "response_style": style,
        }

    def classify_intent(self, state: AssistantState) -> AssistantState:
        """Decision-making node that classifies intent and storage need."""
        message = state["user_message"].lower()

        research_words = (
            "research",
            "analyze",
            "compare",
            "benchmark",
            "market",
            "trend",
        )

        intent = (
            "research" if any(word in message for word in research_words) else "support"
        )
        memory_candidate = self._extract_memory_from_message(
            state["user_id"],
            state["user_message"],
        )
        should_store = memory_candidate is not None

        return {
            "intent": intent,
            "should_store": should_store,
            "memory_to_store": memory_candidate or {},
        }

    def route_support(self, _state: AssistantState) -> AssistantState:
        """Support branch for normal customer-help requests."""
        return {}

    def route_research(self, _state: AssistantState) -> AssistantState:
        """Research branch for analysis-heavy requests."""
        return {}

    def compose_response(self, state: AssistantState) -> AssistantState:
        """Build a response grounded in recalled memories."""
        memories = state.get("recalled_memories", [])
        style = state.get("response_style", "clear")
        intent = state.get("intent", "support")

        memory_snippets = self._memory_snippets(memories)
        if memory_snippets:
            memory_context = f"I remember: {memory_snippets}. "
        else:
            memory_context = ""

        if self.llm_client:
            try:
                response = self._generate_response_with_llm(
                    user_message=state["user_message"],
                    memory_context=memory_context,
                    style=style,
                    intent=intent,
                )
                return {"response": response}
            except Exception:
                logger.exception(
                    "LLM response generation failed; using fallback template"
                )

        if intent == "research":
            core = (
                "I'll provide a structured research summary with assumptions, "
                "risks, and next actions."
            )
        else:
            core = "I'll solve this with concrete steps and keep it actionable."

        prefix = ""
        if style == "concise":
            prefix = "Concise response: "
        elif style == "bullet":
            prefix = "Bullet-style response: "

        response = f"{prefix}{memory_context}{core}"
        return {"response": response}

    def store_memory(self, state: AssistantState) -> AssistantState:
        """Persist newly discovered user-specific details into Memanto."""
        memory_payload = state.get("memory_to_store")
        if not memory_payload:
            return {}

        self.client.remember(
            agent_id=self.agent_id,
            memory_type=memory_payload["memory_type"],
            title=memory_payload["title"],
            content=memory_payload["content"],
            confidence=memory_payload["confidence"],
            tags=memory_payload["tags"],
            source="langgraph-assistant",
            provenance="explicit_statement",
        )

        return {}

    @staticmethod
    def pick_route(state: AssistantState) -> str:
        """Conditional router for support vs research paths."""
        return "research" if state.get("intent") == "research" else "support"

    @staticmethod
    def should_store(state: AssistantState) -> str:
        """Conditional router for memory storage."""
        return "store" if state.get("should_store") else "finish"

    def run(self, user_id: str, thread_id: str, message: str) -> AssistantState:
        """Run one graph execution for a single thread/session turn."""
        initial_state: AssistantState = {
            "user_id": user_id,
            "thread_id": thread_id,
            "user_message": message,
        }

        return cast(AssistantState, self.graph.invoke(initial_state))

    def _generate_response_with_llm(
        self, user_message: str, memory_context: str, style: str, intent: str
    ) -> str:
        if not self.llm_client:
            raise RuntimeError("LLM client not configured")

        style_instruction = {
            "bullet": "Use concise bullet points.",
            "concise": "Use concise short paragraphs.",
            "clear": "Use clear and actionable language.",
        }.get(style, "Use clear and actionable language.")

        intent_instruction = (
            "Provide a structured research response with assumptions, risks, and next actions."
            if intent == "research"
            else "Provide direct support guidance with concrete next steps."
        )

        system_prompt = (
            "You are a helpful support assistant. "
            f"{style_instruction} "
            f"{intent_instruction} "
            f"{memory_context}"
            "Use remembered preferences naturally when relevant."
        )
        completion = self.llm_client.chat.completions.create(
            model=self.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        output_text = completion.choices[0].message.content
        if output_text:
            return output_text.strip()
        raise RuntimeError("LLM response was empty")

    @staticmethod
    def _build_recall_query(user_id: str, user_message: str) -> str:
        return (
            f"User profile, communication preferences, prior decisions, and relevant "
            f"context for user {user_id}. Current request: {user_message}"
        )

    @staticmethod
    def _infer_style(memories: list[dict[str, Any]]) -> str:
        text = " ".join(
            str(item.get("content", "")).lower()
            for item in memories
            if item.get("content")
        )
        if "bullet" in text:
            return "bullet"
        if "concise" in text:
            return "concise"
        return "clear"

    @staticmethod
    def _memory_snippets(memories: list[dict[str, Any]]) -> str:
        snippets: list[str] = []
        for item in memories[:2]:
            content = str(item.get("content", "")).strip()
            if content:
                snippets.append(content)
        return " | ".join(snippets)

    @staticmethod
    def _extract_memory_from_message(
        user_id: str, user_message: str
    ) -> dict[str, Any] | None:
        message = user_message.strip()
        lower = message.lower()

        preference_markers = (
            "i prefer",
            "my preference",
            "please use",
            "call me",
            "i like",
        )

        if not any(marker in lower for marker in preference_markers):
            return None

        safe_user_id = "".join(
            ch for ch in user_id if ch.isalnum() or ch in ALLOWED_USER_ID_CHARS
        )[:MAX_USER_ID_LENGTH]
        safe_user_id = safe_user_id or "user"
        title = f"Preference for {safe_user_id}"
        content = message[:MAX_MEMORY_CONTENT_LENGTH]
        return {
            "memory_type": "preference",
            "title": title[:MAX_MEMORY_TITLE_LENGTH],
            "content": content,
            "confidence": 0.95,
            "tags": ["user-profile", "langgraph-demo"],
        }

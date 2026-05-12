"""Chainlit UI for LangGraph + Memanto memory continuity demo."""

from __future__ import annotations

import os
import uuid

import chainlit as cl
from dotenv import load_dotenv
from memory_graph import MemantoSessionManager, MemoryAwareSupportAssistant

load_dotenv()


def _is_truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@cl.on_chat_start
async def on_chat_start() -> None:
    provider = os.getenv("LLM_PROVIDER", "auto").strip().lower()
    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    memory_enabled = _is_truthy(
        os.getenv("MEMANTO_PERSISTENT_MEMORY_ENABLED", "true"), default=True
    )
    api_key = os.getenv("MOORCHEH_API_KEY")
    has_llm_key = (
        bool(openai_key)
        if provider == "openai"
        else bool(gemini_key)
        if provider == "gemini"
        else bool(openai_key or gemini_key)
    )
    if not has_llm_key or (memory_enabled and not api_key):
        llm_requirement = (
            "`OPENAI_API_KEY`"
            if provider == "openai"
            else "`GEMINI_API_KEY`"
            if provider == "gemini"
            else "`OPENAI_API_KEY` or `GEMINI_API_KEY`"
        )
        memory_requirement = " and `MOORCHEH_API_KEY`" if memory_enabled else ""
        await cl.Message(
            content=(
                "Missing required keys. Add "
                f"{llm_requirement}{memory_requirement} to `.env` before starting."
            )
        ).send()
        return

    agent_id = os.getenv("MEMANTO_AGENT_ID", "langgraph-support-demo")
    user_id = os.getenv("MEMANTO_DEMO_USER_ID", "sam-user")
    thread_id = f"thread-{uuid.uuid4().hex[:8]}"

    manager = None
    client = None
    if memory_enabled and api_key:
        manager = MemantoSessionManager(api_key=api_key, agent_id=agent_id)
        client = manager.setup()

    assistant = MemoryAwareSupportAssistant(
        client=client,
        agent_id=agent_id,
        enable_persistent_memory=memory_enabled,
    )

    cl.user_session.set("manager", manager)
    cl.user_session.set("assistant", assistant)
    cl.user_session.set("user_id", user_id)
    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("memory_enabled", memory_enabled)

    await cl.Message(
        content=(
            "Ready. Start chatting to store and recall cross-session preferences.\n\n"
            f"- Agent: `{agent_id}`\n"
            f"- User: `{user_id}`\n"
            f"- Thread: `{thread_id}`\n"
            f"- Persistent memory: `{memory_enabled}`"
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    assistant = cl.user_session.get("assistant")
    user_id = cl.user_session.get("user_id")
    thread_id = cl.user_session.get("thread_id")
    if not assistant or not user_id or not thread_id:
        await cl.Message(content="Session is not initialized. Start a new chat.").send()
        return

    result = await cl.make_async(assistant.run)(user_id, thread_id, message.content)
    response = result.get("response", "I could not generate a response.")
    recalled = result.get("recalled_memories", [])

    recall_note = ""
    if recalled:
        preview = ", ".join(str(item.get("content", "")) for item in recalled[:2])
        recall_note = f"\n\n_Recalled memories: {len(recalled)} (preview: {preview})_"

    await cl.Message(content=f"{response}{recall_note}").send()


@cl.on_chat_end
async def on_chat_end() -> None:
    manager = cl.user_session.get("manager")
    if manager:
        await cl.make_async(manager.teardown)()

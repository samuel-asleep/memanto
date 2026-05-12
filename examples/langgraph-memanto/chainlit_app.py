"""Chainlit UI for LangGraph + Memanto memory continuity demo."""

from __future__ import annotations

import os
import uuid

import chainlit as cl
from dotenv import load_dotenv

from memory_graph import MemantoSessionManager, MemoryAwareSupportAssistant

load_dotenv()


@cl.on_chat_start
async def on_chat_start() -> None:
    api_key = os.getenv("MOORCHEH_API_KEY")
    if not api_key:
        await cl.Message(
            content="Missing MOORCHEH_API_KEY. Add it to `.env` before starting."
        ).send()
        return

    agent_id = os.getenv("MEMANTO_AGENT_ID", "langgraph-support-demo")
    user_id = os.getenv("MEMANTO_DEMO_USER_ID", "sam-user")
    thread_id = f"thread-{uuid.uuid4().hex[:8]}"

    manager = MemantoSessionManager(api_key=api_key, agent_id=agent_id)
    client = manager.setup()
    assistant = MemoryAwareSupportAssistant(client=client, agent_id=agent_id)

    cl.user_session.set("manager", manager)
    cl.user_session.set("assistant", assistant)
    cl.user_session.set("user_id", user_id)
    cl.user_session.set("thread_id", thread_id)

    await cl.Message(
        content=(
            "Ready. Start chatting to store and recall cross-session preferences.\n\n"
            f"- Agent: `{agent_id}`\n"
            f"- User: `{user_id}`\n"
            f"- Thread: `{thread_id}`"
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

# LangGraph + Memanto Long-Term Memory Example

This example shows a customer support agent where **LangGraph owns the active
workflow** and **Memanto owns durable long-term memory**. The graph keeps only the
current turn in state, while customer facts and preferences are stored in Memanto
so they can be recalled by later graph instances, new thread ids, or separate
processes.

The scenario is intentionally simple:

1. A simulated "yesterday" support interaction stores customer facts in Memanto.
2. A simulated "today" interaction starts with a fresh LangGraph graph/thread and
   only a new user message.
3. The agent retrieves yesterday's customer context from Memanto and uses it in
   the response.

## Video walkthrough

> Placeholder: add a 30-second GIF or video link here before final submission.
>
> Suggested recording: run `langraph.py`, show the first session storing four
> memories, then show the second session recalling the refund preference, invoice,
> plan, and customer name from Memanto.

## Architecture

```text
User turn
  ↓
LangGraph StateGraph
  ├─ recall_customer_context  → Memanto semantic recall
  ├─ capture_new_memories     → Memanto durable writes
  └─ draft_support_reply      → response grounded in recalled memories
```

### Components

- `workflow.py` builds the LangGraph `StateGraph` with recall, write, and reply
  nodes.
- `memanto_memory.py` wraps Memanto's `SdkClient` behind a small
  `MemantoLongTermMemory` adapter.
- `langraph.py` is the live walkthrough script that simulates the yesterday and
  today sessions.
- `smoke_test.py` validates the same cross-session contract offline with a fake
  persistent memory adapter.

## Why Memanto is outside LangGraph state

`SupportState` contains only transient fields for the current turn:
`customer_id`, `user_message`, `recalled_memories`, `stored_memory_ids`, and
`response`.

Durable facts are not checkpointed in LangGraph. They are written to the Memanto
namespace for `MEMANTO_LANGGRAPH_AGENT_ID`, which lets later runs retrieve them
without replaying the previous conversation or reusing the previous thread state.

## Setup

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -r examples/langgraph-memanto/requirements.txt
cp examples/langgraph-memanto/.env.example examples/langgraph-memanto/.env
```

Edit `examples/langgraph-memanto/.env` and set `MOORCHEH_API_KEY` for the live
Memanto-backed walkthrough.

## Expected live behavior

The live walkthrough stores four memories during the first session:

- customer name: Maya
- subscription plan: Pro
- billing issue: invoice `INV-4421`
- refund preference: account credit

The second session starts from a fresh graph/thread and should recall those
memories from Memanto even though the second input only contains the current
`customer_id` and `user_message`.

## Offline validation

Use the smoke test when you want to verify the LangGraph wiring without a
Moorcheh API key:

```bash
python examples/langgraph-memanto/smoke_test.py
```

Pass condition: the command prints
`✅ Offline cross-session recall contract passed.`

## Files

```text
examples/langgraph-memanto/
├── .env.example
├── README.md
├── langraph.py
├── memanto_memory.py
├── requirements.txt
├── smoke_test.py
└── workflow.py
```

# LangGraph + Memanto Long-Term Memory Example

This example is a customer support workflow where LangGraph handles the active
turn and Memanto acts as the long-term memory layer outside of LangGraph state.
It demonstrates **cross-session recall**: the agent stores customer details in a
"yesterday" run, then a brand-new graph instance and thread id recall those
details in a "today" run without passing the prior conversation back into state.

## What the workflow demonstrates

- `workflow.py` defines a `StateGraph` with three nodes:
  1. `recall_customer_context` searches Memanto for durable memories.
  2. `capture_new_memories` stores explicit facts/preferences from the current turn.
  3. `draft_support_reply` writes a support response grounded in recalled memory.
- `memanto_memory.py` is a focused adapter around Memanto's `SdkClient`.
- `demo.py` runs two disjoint sessions with different LangGraph thread ids:
  - **Session 1 / yesterday** stores the customer's name, plan, invoice issue, and refund preference.
  - **Session 2 / today** starts with only a new user message, then recalls yesterday's refund and billing context from Memanto.

## Setup

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -r examples/langgraph-memanto/requirements.txt
cp examples/langgraph-memanto/.env.example examples/langgraph-memanto/.env
```

Edit `examples/langgraph-memanto/.env` and set `MOORCHEH_API_KEY`.

## Run the demo

```bash
cd examples/langgraph-memanto
python demo.py
```

Expected behavior:

1. The first run says it stored new memory item(s) in Memanto.
2. The second run prints that it found cross-session context in Memanto.
3. The recalled memories include information from the first run even though the
   second invocation only supplied `customer_id` and a fresh `user_message`.


## Test the Issue #397 Acceptance Criteria

Use the following checks to validate the bounty requirements from [issue #397](https://github.com/moorcheh-ai/memanto/issues/397):

| Requirement | How to verify |
| --- | --- |
| LangGraph workflow exists | `workflow.py` builds a `StateGraph` with recall, memory-capture, and reply nodes. |
| Memanto is outside LangGraph state | `SupportState` only has transient turn fields; durable facts are read/written through `MemantoLongTermMemory`. |
| Cross-session recall | Session 1 stores memories; Session 2 uses a new graph object and new thread id with only `customer_id` and `user_message` in state. |
| Clean single-folder example | All runnable code and docs are in `examples/langgraph-memanto/`. |

### Fast offline smoke test

This does **not** call Moorcheh. It uses a fake persistent memory object to prove
that the LangGraph workflow itself keeps durable memory outside the graph state
and can recall it from a fresh graph/thread.

```bash
python examples/langgraph-memanto/smoke_test.py
```

Pass condition: the command prints
`✅ Offline cross-session recall contract passed.`

### Live Memanto integration test

Use this when you want to verify the real Memanto/Moorcheh storage path:

```bash
cp examples/langgraph-memanto/.env.example examples/langgraph-memanto/.env
# edit .env and set MOORCHEH_API_KEY
cd examples/langgraph-memanto
python demo.py
```

Pass condition: the "today" session prints recalled memories from yesterday,
including Maya's Pro plan, invoice `INV-4421`, and account-credit refund
preference, even though the today invocation only supplied a fresh user message.

## Why this is outside normal LangGraph state

The `SupportState` only contains transient fields for the current turn:
`customer_id`, `user_message`, `recalled_memories`, `stored_memory_ids`, and
`response`. Durable facts are not checkpointed in LangGraph. They live in the
Memanto namespace for `MEMANTO_LANGGRAPH_AGENT_ID`, so they are available across
new graph objects, new thread ids, and separate processes.

## Files

```text
examples/langgraph-memanto/
├── .env.example
├── README.md
├── demo.py
├── memanto_memory.py
├── requirements.txt
├── smoke_test.py
└── workflow.py
```

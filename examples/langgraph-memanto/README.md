# LangGraph + Memanto: Cross-Session Memory Demo

This example shows **Memanto as the long-term memory layer** for a LangGraph customer support workflow.

It demonstrates:
- LangGraph state for the current turn
- Memanto for persistent memory outside graph state
- **Cross-session recall** ("day 2" remembers a preference saved on "day 1")

## Files

```text
examples/langgraph-memanto/
├── README.md
├── requirements.txt
└── langgraph_memanto_support_agent.py
```

## Prerequisites

- Python 3.10+
- `MOORCHEH_API_KEY` environment variable
- Memanto installed from this repository (or `pip install memanto`)

## Setup

From repository root:

```bash
pip install -e ".[all]"
pip install -r examples/langgraph-memanto/requirements.txt
```

Export API key:

```bash
export MOORCHEH_API_KEY="your-key-here"
```

## Run the Cross-Session Demo

Use the **same `--agent-id`** for both runs.

### 1) Day 1: store memory

```bash
python examples/langgraph-memanto/langgraph_memanto_support_agent.py \
  --scenario day1 \
  --agent-id langgraph-support-demo
```

This stores memories such as customer name and urgent-contact preference.

### 2) Day 2: recall from yesterday in a new session

```bash
python examples/langgraph-memanto/langgraph_memanto_support_agent.py \
  --scenario day2 \
  --agent-id langgraph-support-demo
```

Expected behavior: the agent recalls the urgent-contact preference from Memanto even though the current LangGraph turn state does not include that information.

## Why this proves cross-session memory

Each run creates a fresh LangGraph invocation and a fresh Memanto session token. The second run can still answer from the memory written in the first run because memory persists in Memanto's namespace for the agent ID.

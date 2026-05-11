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
└── langraph.py
```

## Prerequisites

- Python 3.10+
- API key in `examples/langgraph-memanto/.env` (recommended) or shell env vars
- Memanto installed from this repository (or `pip install memanto`)

## Setup

From repository root:

```bash
pip install -e ".[all]"
pip install -r examples/langgraph-memanto/requirements.txt
```

Create `examples/langgraph-memanto/.env`:

```bash
cp examples/langgraph-memanto/.env.example examples/langgraph-memanto/.env
# Then edit examples/langgraph-memanto/.env and set one of:
# MOORCHEH_API_KEY=your-key-here
# MEMANTO_API_KEY=your-key-here
```

## Run the Cross-Session Demo

Use the **same `--agent-id`** for both runs.

### 1) Store memory

```bash
python examples/langgraph-memanto/langraph.py \
  --store \
  --agent-id langgraph-support-demo
```

This stores memories such as customer name and urgent-contact preference.

To store your own information, pass a custom store message:

```bash
python examples/langgraph-memanto/langraph.py \
  --store \
  --store-message "My name is Alex. For urgent updates, call me instead of email." \
  --agent-id langgraph-support-demo
```

### 2) Retrieve from a new session

```bash
python examples/langgraph-memanto/langraph.py \
  --retrieve \
  --agent-id langgraph-support-demo
```

Expected behavior: the agent recalls the urgent-contact preference from Memanto even though the current LangGraph turn state does not include that information.

## Why this proves cross-session memory

Each run creates a fresh LangGraph invocation and a fresh Memanto session token. The second run can still answer from the memory written in the first run because memory persists in Memanto's namespace for the agent ID.

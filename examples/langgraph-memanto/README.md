# LangGraph + Memanto: Cross-Session Long-Term Memory

This example shows a **stateful LangGraph workflow** that uses **Memanto** as a persistent memory layer.

It demonstrates:

- **Retrieve node** at session start (`retrieve_context`) that pulls historical user context from Memanto
- **Decision node** (`classify_intent`) that routes to support vs research branches
- **Store node** (`store_memory`) that commits important new information to Memanto
- **Cross-session continuity**: a fresh session remembers details saved in a previous execution
- **Real LLM responses** in `compose_response` (OpenAI or Gemini key)
- **Interactive UI** via Chainlit for recording live demos
- **Persistent memory toggle** to turn Memanto recall/store on or off

## Architecture

```text
START
  -> retrieve_context (Memanto recall)
  -> classify_intent
      -> route_support  ---\
      -> route_research ---+-> compose_response
                              -> [if should_store] store_memory (Memanto remember)
                              -> END
```

## Prerequisites

- Python 3.10+
- One LLM API key:
  - OpenAI (`OPENAI_API_KEY`) or
  - Gemini (`GEMINI_API_KEY`)
- Optional Moorcheh API key (`MOORCHEH_API_KEY`) if persistent memory is enabled

## Setup

```bash
cd examples/langgraph-memanto/

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# Add your LLM key(s) in .env.
# Set MEMANTO_PERSISTENT_MEMORY_ENABLED=false if you want to run without Memanto.
```

## Run the Continuity Demo

```bash
python run_demo.py
```

What happens:

1. **Session A** starts a fresh Memanto session and stores:
   - "I prefer concise bullet-point updates. Call me Sam..."
2. **Session B** starts a completely new session and thread.
3. The graph's `retrieve_context` node recalls Session A memory and uses it in the response.

Expected output is JSON with:

- `session_a.stored_memory: true`
- `session_b.retrieved_count > 0`
- `session_b.response` reflecting recalled preferences (concise/bullet style)

## Run the Interactive UI (for video recording)

```bash
cd /home/runner/work/memanto/memanto/examples/langgraph-memanto
chainlit run chainlit_app.py
```

Important env toggles:

- `LLM_PROVIDER=auto|openai|gemini` (default `auto`)
- `MEMANTO_PERSISTENT_MEMORY_ENABLED=true|false`

Then record this flow:

1. **Chat Session 1**: send `My name is Sam, I prefer bullet points.`
2. End the chat and start a **new chat session** in Chainlit.
3. **Chat Session 2**: ask a normal support question.
4. The assistant should recall memory and adapt to remembered style/preferences.

If memory toggle is set to `false`, the app still chats with the LLM but skips Memanto recall/store.

## Files

```text
examples/langgraph-memanto/
├── README.md
├── requirements.txt
├── .env.example
├── memory_graph.py
├── run_demo.py
└── chainlit_app.py
```

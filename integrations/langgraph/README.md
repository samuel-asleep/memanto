# LangGraph + Memanto Integration

This package provides native LangGraph tools and a standalone memory layer for integrating Memanto's persistent, cross-session memory capabilities into LangGraph agents.

## Installation

```bash
pip install langgraph-memanto
```

## Features

- **Native LangChain Tools**: Easy-to-use `@tool` wrappers that LangGraph agents can autonomously call (`memanto_remember`, `memanto_recall`, `memanto_answer`).
- **Cross-Session Persistence**: Memories stored by your agents survive across threads, sessions, and even different agents within the same namespace.

## Usage

```python
from langgraph_memanto import create_memanto_tools
from memanto.cli.client.sdk_client import SdkClient

# Initialize the Memanto SDK Client
client = SdkClient(api_key="your_moorcheh_api_key")

# Get native LangChain tools
# The tools will automatically ensure the agent is created and activated 
# the first time the LLM tries to call them!
tools = create_memanto_tools(client, "my-langgraph-agent")

# Bind them to your LLM
llm_with_tools = llm.bind_tools(tools)
```

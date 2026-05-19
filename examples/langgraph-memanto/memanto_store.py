"""MemantoStore - a LangGraph BaseStore backed by Memanto.

This is what makes the demo work. Compile the graph with
``store=MemantoStore(client, agent_id)`` and nodes get cross-thread,
cross-session memory through the official LangGraph store API
(``store.aput`` / ``store.asearch``), just like ``InMemoryStore``,
``PostgresStore``, or ``RedisStore``.

Mapping between abstractions
----------------------------

LangGraph's BaseStore is a namespaced key-value store with semantic
search. Memanto is a typed semantic memory database addressed by
``agent_id`` and ``memory_id``. The mapping:

    BaseStore                       ->  Memanto
    --------------------------------------------------------------
    namespace (tuple[str, ...])     ->  reserved tags  ``lg:ns:0:<p0>``,
                                                       ``lg:ns:1:<p1>``, ...
    key (str)                       ->  reserved tag   ``lg:key:<key>``
    value["kind"] / value["type"]   ->  memory_type    (default "fact")
    value["title"]                  ->  title          (auto-derived if absent)
    value["content"]                ->  content        (auto-stringified if absent)
    value["confidence"]             ->  confidence     (default 0.8)
    value["tags"]                   ->  user tags      (joined with reserved)
    SearchOp.query                  ->  recall query   ("*" if empty)
    SearchOp.filter["type"]         ->  type filter
    SearchOp.filter["tags"]         ->  extra tag filter
    SearchOp.filter["min_confidence"] -> min_confidence

Documented limitations
----------------------

* **Delete** (``PutOp`` with ``value=None``) raises ``NotImplementedError``.
  Memanto deletions go through its conflict-resolution flow, not free-form
  removal. Use ``memanto conflicts resolve`` instead.
* **TTL** on put is ignored - Memanto doesn't expire memories on a timer.
* **Pagination offset** in search is ignored - Memanto recall doesn't
  paginate. Raise the ``limit`` instead.
* **list_namespaces** is best-effort: samples up to ``limit`` recent
  memories and derives unique namespaces from their tags.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    PutOp,
    SearchItem,
    SearchOp,
)

from memanto.cli.client.sdk_client import SdkClient

logger = logging.getLogger(__name__)

_NS_TAG_PREFIX = "lg:ns:"
_KEY_TAG_PREFIX = "lg:key:"
_RESERVED_PREFIX = "lg:"

_VALID_MEMORY_TYPES = {
    "fact",
    "preference",
    "goal",
    "decision",
    "artifact",
    "learning",
    "event",
    "instruction",
    "relationship",
    "context",
    "observation",
    "commitment",
    "error",
}


class MemantoStore(BaseStore):
    """LangGraph ``BaseStore`` backed by Memanto's typed semantic memory.

    Drop-in replacement for ``InMemoryStore`` / ``PostgresStore`` /
    ``RedisStore``. Memories persist across threads and sessions because
    Memanto persists them server-side, scoped by ``agent_id``.

    Example::

        from memanto_setup import MemantoSetup
        from memanto_store import MemantoStore

        client = MemantoSetup(api_key).setup(agent_id="my-app")
        store = MemantoStore(client, agent_id="my-app")
        graph = builder.compile(store=store, checkpointer=InMemorySaver())
    """

    def __init__(self, client: SdkClient, agent_id: str) -> None:
        self._client = client
        self._agent_id = agent_id

    # ------------------------------------------------------------------ #
    # Required abstract methods                                          #
    # ------------------------------------------------------------------ #

    def batch(self, ops: Iterable[Any]) -> list[Any]:
        """Execute a batch of store operations synchronously."""
        return [self._dispatch_one(op) for op in ops]

    async def abatch(self, ops: Iterable[Any]) -> list[Any]:
        """Execute a batch of store operations asynchronously.

        The Memanto SDK is synchronous, so we offload to a worker thread
        to keep the event loop free.
        """
        op_list = list(ops)
        return await asyncio.to_thread(self.batch, op_list)

    # ------------------------------------------------------------------ #
    # Per-op dispatch                                                    #
    # ------------------------------------------------------------------ #

    def _dispatch_one(self, op: Any) -> Any:
        if isinstance(op, GetOp):
            return self._do_get(op)
        if isinstance(op, PutOp):
            return self._do_put(op)
        if isinstance(op, SearchOp):
            return self._do_search(op)
        if isinstance(op, ListNamespacesOp):
            return self._do_list_namespaces(op)
        raise NotImplementedError(f"Unsupported store op: {type(op).__name__}")

    # ------------------------------------------------------------------ #
    # GET                                                                #
    # ------------------------------------------------------------------ #

    def _do_get(self, op: GetOp) -> Item | None:
        """Lookup-by-key, implemented via tag-filtered recall."""
        ns_tags = self._namespace_to_tags(op.namespace)
        key_tag = self._key_to_tag(op.key)

        result = self._client.recall(
            agent_id=self._agent_id,
            query=op.key or "*",
            limit=10,
            tags=ns_tags + [key_tag],
        )

        # Memanto's tag filter may be permissive - enforce match here.
        for mem in result.get("memories", []):
            tags = mem.get("tags", []) or []
            if key_tag in tags and all(t in tags for t in ns_tags):
                return self._memory_to_item(mem, op.namespace, op.key)
        return None

    # ------------------------------------------------------------------ #
    # PUT (and delete-via-put-None)                                      #
    # ------------------------------------------------------------------ #

    def _do_put(self, op: PutOp) -> None:
        if op.value is None:
            raise NotImplementedError(
                "MemantoStore does not support delete via PutOp(value=None). "
                "Memanto removals go through the conflict-resolution flow; "
                "use `memanto conflicts resolve` or the SdkClient's resolve API."
            )

        value: dict[str, Any] = dict(op.value)

        memory_type = str(value.pop("kind", value.pop("type", "fact"))).lower()
        if memory_type not in _VALID_MEMORY_TYPES:
            memory_type = "fact"

        raw_content = value.pop("content", None)
        if raw_content is None:
            raw_content = self._stringify(value)

        title = value.pop("title", None)
        if not title:
            title = raw_content if len(raw_content) <= 80 else raw_content[:77] + "..."
        title = title[:100]

        confidence = float(value.pop("confidence", 0.8))
        confidence = max(0.0, min(1.0, confidence))

        user_tags = list(value.pop("tags", []) or [])
        user_tags = [t for t in user_tags if not str(t).startswith(_RESERVED_PREFIX)]

        all_tags = (
            user_tags
            + self._namespace_to_tags(op.namespace)
            + [self._key_to_tag(op.key)]
        )

        self._client.remember(
            agent_id=self._agent_id,
            memory_type=memory_type,
            title=title,
            content=str(raw_content),
            confidence=confidence,
            tags=all_tags,
            source="langgraph-store",
            provenance="explicit_statement",
        )

    # ------------------------------------------------------------------ #
    # SEARCH                                                             #
    # ------------------------------------------------------------------ #

    def _do_search(self, op: SearchOp) -> list[SearchItem]:
        query = op.query or "*"
        filter_dict = op.filter or {}
        ns_tags = self._namespace_to_tags(op.namespace_prefix)

        type_filter = filter_dict.get("type") or filter_dict.get("kind")
        if isinstance(type_filter, str):
            type_filter = [type_filter]

        extra_tags = list(filter_dict.get("tags", []) or [])
        min_conf = filter_dict.get("min_confidence")

        result = self._client.recall(
            agent_id=self._agent_id,
            query=query,
            limit=max(1, op.limit),
            type=type_filter,
            tags=ns_tags + extra_tags if (ns_tags or extra_tags) else None,
            min_confidence=min_conf,
        )

        out: list[SearchItem] = []
        for mem in result.get("memories", []):
            tags = mem.get("tags", []) or []
            # Enforce namespace_prefix match - tags must contain every ns tag.
            if ns_tags and not all(t in tags for t in ns_tags):
                continue
            namespace = self._tags_to_namespace(tags) or op.namespace_prefix
            key = self._tags_to_key(tags) or mem.get("id", "")
            out.append(self._memory_to_search_item(mem, namespace, key))

        return out

    # ------------------------------------------------------------------ #
    # LIST NAMESPACES (best-effort)                                      #
    # ------------------------------------------------------------------ #

    def _do_list_namespaces(self, op: ListNamespacesOp) -> list[tuple[str, ...]]:
        # Sample generously (at least 200) so we cover all namespaces, then
        # truncate the *output* to op.limit. op.limit controls what the caller
        # sees, not how many memories we query.
        sample_limit = max(op.limit or 0, 200)
        sample = self._client.recall(
            agent_id=self._agent_id,
            query="*",
            limit=sample_limit,
        )
        seen: set[tuple[str, ...]] = set()
        for mem in sample.get("memories", []):
            tags = mem.get("tags", []) or []
            ns = self._tags_to_namespace(tags)
            if ns:
                seen.add(ns)

        result = sorted(seen)
        if op.max_depth is not None:
            result = [ns[: op.max_depth] for ns in result]
            result = sorted(set(result))
        if op.limit:
            result = result[: op.limit]
        return result

    # ------------------------------------------------------------------ #
    # Encoding helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _namespace_to_tags(namespace: tuple[str, ...]) -> list[str]:
        """Encode a namespace tuple as a list of reserved tags.

        ``("user-bob", "memories")`` -> ``["lg:ns:0:user-bob", "lg:ns:1:memories"]``
        """
        return [f"{_NS_TAG_PREFIX}{i}:{part}" for i, part in enumerate(namespace)]

    @staticmethod
    def _key_to_tag(key: str) -> str:
        return f"{_KEY_TAG_PREFIX}{key}"

    @staticmethod
    def _tags_to_namespace(tags: list[str]) -> tuple[str, ...]:
        """Reverse ``_namespace_to_tags``. Returns () if none present."""
        positioned: dict[int, str] = {}
        for t in tags:
            if not t.startswith(_NS_TAG_PREFIX):
                continue
            rest = t[len(_NS_TAG_PREFIX) :]
            idx_str, _, value = rest.partition(":")
            try:
                positioned[int(idx_str)] = value
            except ValueError:
                continue
        if not positioned:
            return ()
        return tuple(positioned[i] for i in sorted(positioned))

    @staticmethod
    def _tags_to_key(tags: list[str]) -> str | None:
        for t in tags:
            if t.startswith(_KEY_TAG_PREFIX):
                return t[len(_KEY_TAG_PREFIX) :]
        return None

    @staticmethod
    def _stringify(value: dict[str, Any]) -> str:
        if not value:
            return "(empty)"
        return ", ".join(f"{k}={v}" for k, v in value.items())

    # ------------------------------------------------------------------ #
    # Item construction                                                  #
    # ------------------------------------------------------------------ #

    def _memory_to_item(
        self, mem: dict[str, Any], namespace: tuple[str, ...], key: str
    ) -> Item:
        return Item(
            value=self._memory_to_value(mem),
            key=key,
            namespace=namespace,
            created_at=self._parse_dt(mem.get("created_at")),
            updated_at=self._parse_dt(mem.get("updated_at") or mem.get("created_at")),
        )

    def _memory_to_search_item(
        self, mem: dict[str, Any], namespace: tuple[str, ...], key: str
    ) -> SearchItem:
        score = mem.get("score")
        if score is None:
            score = mem.get("similarity")
        try:
            score_f = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_f = None

        return SearchItem(
            value=self._memory_to_value(mem),
            key=key,
            namespace=namespace,
            created_at=self._parse_dt(mem.get("created_at")),
            updated_at=self._parse_dt(mem.get("updated_at") or mem.get("created_at")),
            score=score_f,
        )

    @staticmethod
    def _memory_to_value(mem: dict[str, Any]) -> dict[str, Any]:
        tags = mem.get("tags", []) or []
        user_tags = [t for t in tags if not t.startswith(_RESERVED_PREFIX)]
        return {
            "kind": mem.get("type", "fact"),
            "title": mem.get("title", ""),
            "content": mem.get("content", ""),
            "confidence": mem.get("confidence"),
            "tags": user_tags,
            "memory_id": mem.get("id"),
        }

    @staticmethod
    def _parse_dt(raw: Any) -> datetime:
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.now(tz=timezone.utc)

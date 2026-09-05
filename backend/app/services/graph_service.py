"""Graph engine service: builds, caches and queries the relationship graph.

Rebuilding a 5,000-event graph costs tens of milliseconds, but the same graph is
hit by every traversal request, so it is cached in-process and rebuilt only when
the TTL expires, the event count changes, or a filter differs from the cached one.
Ingestion invalidates the cache explicitly so a freshly posted event is visible to
the next traversal.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Mapping

import networkx as nx

from app.config import settings
from app.graph import astar as astar_module
from app.graph import bfs as bfs_module
from app.graph import dfs as dfs_module
from app.graph import dijkstra as dijkstra_module
from app.graph.builder import build_graph, edge_summary, graph_stats
from app.models.common import Direction, Heuristic, WeightStrategy
from app.services.event_service import EventFilter, fetch_events

logger = logging.getLogger(__name__)


class DeviceNotInGraphError(KeyError):
    """Raised when a requested device has no events in the current graph."""


class _GraphCache:
    """Single cached graph guarded by an asyncio lock.

    The lock prevents a thundering herd of concurrent requests each triggering
    its own rebuild of the same graph.
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph | None = None
        self._filter_key: str | None = None
        self._built_at: float = 0.0
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(filter_dict: Mapping[str, Any] | None) -> str:
        if not filter_dict:
            return "*"
        return "&".join(f"{k}={v}" for k, v in sorted(filter_dict.items()) if v is not None) or "*"

    def _is_fresh(self, key: str) -> bool:
        return (
            self._graph is not None
            and self._filter_key == key
            and (time.time() - self._built_at) < settings.graph_cache_ttl
        )

    async def get(self, filter_dict: Mapping[str, Any] | None = None) -> nx.DiGraph:
        key = self._key(filter_dict)
        if self._is_fresh(key):
            return self._graph  # type: ignore[return-value]

        async with self._lock:
            # Re-check: another task may have rebuilt while we waited.
            if self._is_fresh(key):
                return self._graph  # type: ignore[return-value]

            started = time.perf_counter()
            events = await fetch_events(
                EventFilter(
                    start_time=(filter_dict or {}).get("start_time"),
                    end_time=(filter_dict or {}).get("end_time"),
                    protocol=(filter_dict or {}).get("protocol"),
                    dst_port=(filter_dict or {}).get("dst_port"),
                    min_bytes=(filter_dict or {}).get("min_bytes"),
                ),
                limit=settings.graph_max_events,
            )
            graph = build_graph(events)
            self._graph = graph
            self._filter_key = key
            self._built_at = time.time()
            logger.info(
                "Built graph: %d nodes, %d edges from %d events in %.1f ms (filter=%s)",
                graph.number_of_nodes(),
                graph.number_of_edges(),
                len(events),
                (time.perf_counter() - started) * 1000,
                key,
            )
            return graph

    def invalidate(self) -> None:
        self._graph = None
        self._filter_key = None
        self._built_at = 0.0


_cache = _GraphCache()


def invalidate() -> None:
    """Drop the cached graph; called after ingestion."""
    _cache.invalidate()


async def get_graph(filter_dict: Mapping[str, Any] | None = None) -> nx.DiGraph:
    return await _cache.get(filter_dict)


def _require_device(graph: nx.DiGraph, device: str) -> None:
    if device not in graph:
        raise DeviceNotInGraphError(
            f"device {device!r} has no events in the current graph"
        )


def _stats_block(graph: nx.DiGraph) -> dict[str, int]:
    return {
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "event_count": int(graph.graph.get("event_count", 0)),
    }


async def run_bfs(
    *,
    source: str,
    target: str | None = None,
    max_depth: int = 3,
    max_nodes: int = 500,
    direction: Direction = Direction.OUTBOUND,
    filter_dict: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    graph = await get_graph(filter_dict)
    _require_device(graph, source)
    result = bfs_module.bfs(
        graph, source, target=target, max_depth=max_depth,
        max_nodes=max_nodes, direction=direction,
    )
    result["graph_stats"] = _stats_block(graph)
    return result


async def run_dfs(
    *,
    source: str,
    target: str | None = None,
    max_depth: int = 5,
    max_nodes: int = 500,
    direction: Direction = Direction.OUTBOUND,
    filter_dict: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    graph = await get_graph(filter_dict)
    _require_device(graph, source)
    result = dfs_module.dfs(
        graph, source, target=target, max_depth=max_depth,
        max_nodes=max_nodes, direction=direction,
    )
    result["graph_stats"] = _stats_block(graph)
    return result


async def run_dijkstra(
    *,
    source: str,
    target: str,
    weight: WeightStrategy = WeightStrategy.STRENGTH,
    direction: Direction = Direction.OUTBOUND,
    k: int = 1,
    filter_dict: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    graph = await get_graph(filter_dict)
    _require_device(graph, source)
    _require_device(graph, target)

    if k > 1:
        paths = dijkstra_module.k_shortest_paths(
            graph, source, target, k=k, weight=weight, direction=direction
        )
        if not paths:
            result = dijkstra_module.dijkstra(
                graph, source, target, weight=weight, direction=direction
            )
        else:
            result = dict(paths[0])
            result["alternative_paths"] = [
                {"path": p["path"], "cost": p["cost"], "hops": p["hops"]} for p in paths[1:]
            ]
    else:
        result = dijkstra_module.dijkstra(
            graph, source, target, weight=weight, direction=direction
        )

    result["graph_stats"] = _stats_block(graph)
    return result


async def run_astar(
    *,
    source: str,
    target: str,
    weight: WeightStrategy = WeightStrategy.STRENGTH,
    heuristic: Heuristic = Heuristic.HOP_LOWER_BOUND,
    direction: Direction = Direction.OUTBOUND,
    filter_dict: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    graph = await get_graph(filter_dict)
    _require_device(graph, source)
    _require_device(graph, target)
    result = astar_module.astar(
        graph, source, target, weight=weight, heuristic=heuristic, direction=direction
    )
    result["graph_stats"] = _stats_block(graph)
    return result


async def stats(filter_dict: Mapping[str, Any] | None = None) -> dict[str, Any]:
    graph = await get_graph(filter_dict)
    return graph_stats(graph)


async def neighborhood(
    device: str,
    *,
    depth: int = 1,
    direction: Direction = Direction.BOTH,
    max_nodes: int = 200,
    filter_dict: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Induced subgraph around a device -- the payload a frontend would draw."""
    graph = await get_graph(filter_dict)
    _require_device(graph, device)

    traversal = bfs_module.bfs(
        graph, device, max_depth=depth, max_nodes=max_nodes, direction=direction
    )
    members = {node["device"] for node in traversal["nodes"]}
    depths = {node["device"]: node["depth"] for node in traversal["nodes"]}

    edges = [
        edge_summary(graph, u, v, strategy=WeightStrategy.STRENGTH)
        for u, v in graph.edges()
        if u in members and v in members
    ]
    nodes = [
        {
            "device": node,
            "depth": depths[node],
            **{
                key: graph.nodes[node].get(key, 0)
                for key in ("events_out", "events_in", "bytes_out", "bytes_in")
            },
        }
        for node in members
    ]
    nodes.sort(key=lambda item: (item["depth"], item["device"]))

    return {"device": device, "depth": depth, "nodes": nodes, "edges": edges}

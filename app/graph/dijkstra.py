"""Dijkstra's algorithm over the weighted relationship graph (spec 10.3).

The lowest-cost path is the most *plausible communication route* between two
devices: every weight strategy in ``builder.edge_weight`` makes a stronger
relationship cheaper to traverse, so minimising cost maximises relationship
strength along the route.
"""

from __future__ import annotations

import heapq
import itertools
from typing import Any, Sequence

import networkx as nx

from app.graph.builder import edge_data_between, neighbors_fn, path_edges, weight_function
from app.models.common import Direction, WeightStrategy

__all__ = ["dijkstra", "k_shortest_paths"]


def _edge_cost(
    graph: nx.DiGraph, u: str, v: str, weigh, direction: Direction | str
) -> float | None:
    resolved = edge_data_between(graph, u, v, direction)
    return None if resolved is None else weigh(resolved[2])


def dijkstra(
    graph: nx.DiGraph,
    source: str,
    target: str,
    *,
    weight: WeightStrategy | str = WeightStrategy.STRENGTH,
    direction: Direction | str = Direction.OUTBOUND,
    banned_edges: set[tuple[str, str]] | None = None,
    banned_nodes: set[str] | None = None,
) -> dict[str, Any]:
    """Lowest-cost path from ``source`` to ``target``.

    ``banned_edges`` / ``banned_nodes`` support Yen's k-shortest-paths on top of
    this same routine.
    """
    for device in (source, target):
        if device not in graph:
            raise KeyError(f"device not present in graph: {device}")

    strategy = WeightStrategy(weight)
    weigh = weight_function(strategy)
    neighbors = neighbors_fn(graph, direction)
    banned_edges = banned_edges or set()
    banned_nodes = banned_nodes or set()

    distances: dict[str, float] = {source: 0.0}
    parents: dict[str, str | None] = {source: None}
    settled: set[str] = set()
    explored = 0

    counter = itertools.count()  # tie-breaker keeps heap entries comparable
    heap: list[tuple[float, int, str]] = [(0.0, next(counter), source)]

    while heap:
        cost, _, node = heapq.heappop(heap)
        if node in settled:
            continue  # stale entry from a since-improved distance
        settled.add(node)
        explored += 1

        if node == target:
            break

        for neighbor in neighbors(node):
            if neighbor in settled or neighbor in banned_nodes:
                continue
            if (node, neighbor) in banned_edges:
                continue
            step = _edge_cost(graph, node, neighbor, weigh, direction)
            if step is None:
                continue
            candidate = cost + step
            if candidate < distances.get(neighbor, float("inf")):
                distances[neighbor] = candidate
                parents[neighbor] = node
                heapq.heappush(heap, (candidate, next(counter), neighbor))

    if target not in settled:
        return {
            "algorithm": "dijkstra",
            "source": source,
            "target": target,
            "weight_strategy": strategy.value,
            "found": False,
            "cost": None,
            "hops": None,
            "path": [],
            "edges": [],
            "nodes_explored": explored,
        }

    path = _reconstruct(parents, target)
    return {
        "algorithm": "dijkstra",
        "source": source,
        "target": target,
        "weight_strategy": strategy.value,
        "found": True,
        "cost": round(distances[target], 6),
        "hops": len(path) - 1,
        "path": path,
        "edges": path_edges(graph, path, strategy=strategy, direction=direction),
        "nodes_explored": explored,
    }


def _reconstruct(parents: dict[str, str | None], target: str) -> list[str]:
    path = [target]
    cursor: str | None = target
    while (cursor := parents[cursor]) is not None:
        path.append(cursor)
    return list(reversed(path))


def path_cost(
    graph: nx.DiGraph,
    path: Sequence[str],
    weight: WeightStrategy | str,
    direction: Direction | str = Direction.OUTBOUND,
) -> float | None:
    """Total cost of an explicit path, or ``None`` if an edge is missing."""
    weigh = weight_function(weight)
    total = 0.0
    for u, v in zip(path, path[1:]):
        step = _edge_cost(graph, u, v, weigh, direction)
        if step is None:
            return None
        total += step
    return total


def k_shortest_paths(
    graph: nx.DiGraph,
    source: str,
    target: str,
    *,
    k: int = 3,
    weight: WeightStrategy | str = WeightStrategy.STRENGTH,
    direction: Direction | str = Direction.OUTBOUND,
) -> list[dict[str, Any]]:
    """Yen's algorithm: the k lowest-cost loop-free routes between two devices.

    Alternative routes matter in an investigation -- a second, slightly costlier
    path can be the one that actually explains an observed relationship.
    """
    first = dijkstra(graph, source, target, weight=weight, direction=direction)
    if not first["found"]:
        return []

    strategy = WeightStrategy(weight)
    accepted: list[dict[str, Any]] = [first]
    candidates: list[tuple[float, list[str]]] = []

    while len(accepted) < k:
        previous = accepted[-1]["path"]
        for i in range(len(previous) - 1):
            spur_node = previous[i]
            root_path = previous[: i + 1]

            banned_edges = {
                (p["path"][i], p["path"][i + 1])
                for p in accepted
                if len(p["path"]) > i + 1 and p["path"][: i + 1] == root_path
            }
            banned_nodes = set(root_path[:-1])

            spur = dijkstra(
                graph, spur_node, target,
                weight=strategy, direction=direction,
                banned_edges=banned_edges, banned_nodes=banned_nodes,
            )
            if not spur["found"]:
                continue

            total_path = root_path[:-1] + spur["path"]
            if any(p["path"] == total_path for p in accepted):
                continue
            if any(existing == total_path for _, existing in candidates):
                continue
            cost = path_cost(graph, total_path, strategy, direction)
            if cost is not None:
                candidates.append((cost, total_path))

        if not candidates:
            break
        candidates.sort(key=lambda item: (item[0], item[1]))
        cost, best = candidates.pop(0)
        accepted.append(
            {
                "algorithm": "dijkstra",
                "source": source,
                "target": target,
                "weight_strategy": strategy.value,
                "found": True,
                "cost": round(cost, 6),
                "hops": len(best) - 1,
                "path": best,
                "edges": path_edges(graph, best, strategy=strategy, direction=direction),
                "nodes_explored": None,
            }
        )

    return accepted[:k]

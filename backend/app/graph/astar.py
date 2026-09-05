"""A* search over the weighted relationship graph (spec 10.4).

A* is Dijkstra plus a heuristic estimate of the remaining cost, so it expands
fewer nodes when hunting for a specific device in a large graph.

Devices have no coordinates, so the usual geometric heuristics do not apply.
Instead ``hop_lower_bound`` uses::

    h(n) = min_edge_weight * undirected_hop_distance(n, target)

This is **admissible** -- the undirected hop distance never exceeds the directed
one, and no edge costs less than ``min_edge_weight``, so ``h`` can never
overestimate the true remaining cost -- and it is **consistent**, because adjacent
nodes' hop distances differ by at most one while every edge costs at least
``min_edge_weight``. Consistency means a node never needs re-expanding once
settled, which is what keeps the search sound.
"""

from __future__ import annotations

import heapq
import itertools
from collections import deque
from typing import Any, Callable

import networkx as nx

from app.graph.builder import (
    edge_data_between,
    min_edge_weight,
    neighbors_fn,
    path_edges,
    weight_function,
)
from app.models.common import Direction, Heuristic, WeightStrategy

__all__ = ["astar", "hop_distances_to"]

INF = float("inf")


def hop_distances_to(graph: nx.DiGraph, target: str) -> dict[str, int]:
    """Undirected hop distance from every reachable node to ``target``.

    One reverse BFS over the undirected view; a lower bound on the directed hop
    count from any node to the target.
    """
    distances: dict[str, int] = {target: 0}
    queue: deque[str] = deque([target])
    while queue:
        node = queue.popleft()
        depth = distances[node]
        for neighbor in (*graph.successors(node), *graph.predecessors(node)):
            if neighbor not in distances:
                distances[neighbor] = depth + 1
                queue.append(neighbor)
    return distances


def _build_heuristic(
    graph: nx.DiGraph,
    target: str,
    heuristic: Heuristic,
    weight: WeightStrategy,
) -> Callable[[str], float]:
    if heuristic is Heuristic.ZERO:
        # Degenerates to Dijkstra -- useful as a correctness baseline.
        return lambda _node: 0.0

    floor = min_edge_weight(graph, weight)
    hops = hop_distances_to(graph, target)

    def estimate(node: str) -> float:
        distance = hops.get(node)
        # Unreachable even ignoring direction: prune the branch entirely.
        return INF if distance is None else floor * distance

    return estimate


def astar(
    graph: nx.DiGraph,
    source: str,
    target: str,
    *,
    weight: WeightStrategy | str = WeightStrategy.STRENGTH,
    heuristic: Heuristic | str = Heuristic.HOP_LOWER_BOUND,
    direction: Direction | str = Direction.OUTBOUND,
) -> dict[str, Any]:
    """Heuristic-guided lowest-cost path from ``source`` to ``target``.

    With an admissible heuristic the returned cost matches Dijkstra's; the payoff
    is ``nodes_explored``, which is typically far smaller.
    """
    for device in (source, target):
        if device not in graph:
            raise KeyError(f"device not present in graph: {device}")

    strategy = WeightStrategy(weight)
    mode = Heuristic(heuristic)
    weigh = weight_function(strategy)
    neighbors = neighbors_fn(graph, direction)
    estimate = _build_heuristic(graph, target, mode, strategy)

    g_score: dict[str, float] = {source: 0.0}
    parents: dict[str, str | None] = {source: None}
    settled: set[str] = set()
    explored = 0

    counter = itertools.count()
    start_h = estimate(source)
    heap: list[tuple[float, int, str]] = [(start_h, next(counter), source)]

    while heap:
        f_score, _, node = heapq.heappop(heap)
        if node in settled:
            continue
        if f_score == INF:
            break  # only unreachable nodes remain
        settled.add(node)
        explored += 1

        if node == target:
            break

        cost = g_score[node]
        for neighbor in neighbors(node):
            if neighbor in settled:
                continue
            resolved = edge_data_between(graph, node, neighbor, direction)
            if resolved is None:
                continue
            candidate = cost + weigh(resolved[2])
            if candidate < g_score.get(neighbor, INF):
                g_score[neighbor] = candidate
                parents[neighbor] = node
                h = estimate(neighbor)
                if h < INF:
                    heapq.heappush(heap, (candidate + h, next(counter), neighbor))

    if target not in settled:
        return {
            "algorithm": "astar",
            "source": source,
            "target": target,
            "weight_strategy": strategy.value,
            "heuristic": mode.value,
            "found": False,
            "cost": None,
            "hops": None,
            "path": [],
            "edges": [],
            "nodes_explored": explored,
        }

    path = [target]
    cursor: str | None = target
    while (cursor := parents[cursor]) is not None:
        path.append(cursor)
    path.reverse()

    return {
        "algorithm": "astar",
        "source": source,
        "target": target,
        "weight_strategy": strategy.value,
        "heuristic": mode.value,
        "found": True,
        "cost": round(g_score[target], 6),
        "hops": len(path) - 1,
        "path": path,
        "edges": path_edges(graph, path, strategy=strategy, direction=direction),
        "nodes_explored": explored,
    }

"""Breadth-first search over the relationship graph (spec 10.1).

BFS answers "which devices sit in this device's local communication
neighbourhood, and how many hops away?" -- so the result is reported as levels,
not just a visited set.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import networkx as nx

from app.graph.builder import neighbors_fn
from app.models.common import Direction

__all__ = ["bfs"]


def bfs(
    graph: nx.DiGraph,
    source: str,
    *,
    target: str | None = None,
    max_depth: int = 3,
    max_nodes: int = 500,
    direction: Direction | str = Direction.OUTBOUND,
) -> dict[str, Any]:
    """Explore outward from ``source`` in hop order.

    Returns visited nodes with their hop depth, the discovery tree, nodes grouped
    by level, and -- when ``target`` is given -- the shortest hop path to it.

    ``truncated`` reports whether ``max_nodes`` or ``max_depth`` cut the search
    short, so callers never mistake a capped result for the full neighbourhood.
    """
    if source not in graph:
        raise KeyError(f"device not present in graph: {source}")

    neighbors = neighbors_fn(graph, direction)

    depths: dict[str, int] = {source: 0}
    parents: dict[str, str | None] = {source: None}
    order: list[str] = [source]
    tree_edges: list[tuple[str, str]] = []
    truncated = False

    queue: deque[str] = deque([source])
    while queue:
        node = queue.popleft()
        depth = depths[node]
        if depth >= max_depth:
            # Deeper neighbours exist but fall outside the requested horizon.
            if any(n not in depths for n in neighbors(node)):
                truncated = True
            continue

        for neighbor in neighbors(node):
            if neighbor in depths:
                continue
            if len(depths) >= max_nodes:
                truncated = True
                queue.clear()
                break
            depths[neighbor] = depth + 1
            parents[neighbor] = node
            order.append(neighbor)
            tree_edges.append((node, neighbor))
            queue.append(neighbor)

    levels: dict[int, list[str]] = {}
    for node, depth in depths.items():
        levels.setdefault(depth, []).append(node)
    for bucket in levels.values():
        bucket.sort()

    paths_to_target: list[list[str]] = []
    if target is not None and target in depths:
        path = [target]
        cursor: str | None = target
        while (cursor := parents[cursor]) is not None:
            path.append(cursor)
        paths_to_target.append(list(reversed(path)))

    return {
        "algorithm": "bfs",
        "source": source,
        "target": target,
        "direction": Direction(direction).value,
        "max_depth": max_depth,
        "node_count": len(depths),
        "nodes": [
            {"device": node, "depth": depths[node], "discovered_from": parents[node]}
            for node in order
        ],
        "levels": dict(sorted(levels.items())),
        "tree_edges": tree_edges,
        "order": order,
        "paths_to_target": paths_to_target,
        "truncated": truncated,
    }

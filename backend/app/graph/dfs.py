"""Depth-first search over the relationship graph (spec 10.2).

DFS follows communication *chains* -- A talked to B, which talked to C -- which is
the shape an investigator traces when following activity forward, rather than the
concentric rings BFS produces.
"""

from __future__ import annotations

from typing import Any

import networkx as nx

from app.graph.builder import neighbors_fn
from app.models.common import Direction

__all__ = ["dfs"]

# Cap on enumerated simple paths, so a dense graph cannot produce a combinatorial
# explosion of routes to the target.
MAX_PATHS = 25


def dfs(
    graph: nx.DiGraph,
    source: str,
    *,
    target: str | None = None,
    max_depth: int = 5,
    max_nodes: int = 500,
    direction: Direction | str = Direction.OUTBOUND,
) -> dict[str, Any]:
    """Walk depth-first from ``source``, bounded by depth and node count.

    Implemented iteratively rather than recursively: with 100k+ devices a
    recursive walk would exhaust the Python stack.

    When ``target`` is given, simple paths to it (up to ``max_depth`` hops) are
    enumerated separately from the discovery tree, since the DFS tree contains at
    most one route to any node.
    """
    if source not in graph:
        raise KeyError(f"device not present in graph: {source}")

    neighbors = neighbors_fn(graph, direction)

    visited: dict[str, int] = {}
    parents: dict[str, str | None] = {source: None}
    order: list[str] = []
    tree_edges: list[tuple[str, str]] = []
    truncated = False

    # Stack holds (node, depth, parent). Neighbours are pushed reversed so the
    # walk explores them in sorted order.
    stack: list[tuple[str, int, str | None]] = [(source, 0, None)]
    while stack:
        node, depth, parent = stack.pop()
        if node in visited:
            continue
        if len(visited) >= max_nodes:
            truncated = True
            break

        visited[node] = depth
        parents[node] = parent
        order.append(node)
        if parent is not None:
            tree_edges.append((parent, node))

        if depth >= max_depth:
            if any(n not in visited for n in neighbors(node)):
                truncated = True
            continue

        for neighbor in sorted(neighbors(node), reverse=True):
            if neighbor not in visited:
                stack.append((neighbor, depth + 1, node))

    levels: dict[int, list[str]] = {}
    for node, depth in visited.items():
        levels.setdefault(depth, []).append(node)
    for bucket in levels.values():
        bucket.sort()

    paths_to_target: list[list[str]] = []
    if target is not None and target in graph:
        paths_to_target = _simple_paths(graph, source, target, max_depth, direction)

    return {
        "algorithm": "dfs",
        "source": source,
        "target": target,
        "direction": Direction(direction).value,
        "max_depth": max_depth,
        "node_count": len(visited),
        "nodes": [
            {"device": node, "depth": visited[node], "discovered_from": parents[node]}
            for node in order
        ],
        "levels": dict(sorted(levels.items())),
        "tree_edges": tree_edges,
        "order": order,
        "paths_to_target": paths_to_target,
        "truncated": truncated,
    }


def _simple_paths(
    graph: nx.DiGraph,
    source: str,
    target: str,
    max_depth: int,
    direction: Direction | str,
) -> list[list[str]]:
    """Enumerate loop-free routes from source to target, depth- and count-bounded."""
    if source == target:
        return [[source]]

    neighbors = neighbors_fn(graph, direction)
    found: list[list[str]] = []
    path: list[str] = [source]
    on_path: set[str] = {source}
    # Each frame is an iterator over the current node's unexplored neighbours.
    frontier = [iter(sorted(neighbors(source)))]

    while frontier:
        candidates = frontier[-1]
        neighbor = next(candidates, None)
        if neighbor is None:
            on_path.discard(path.pop())
            frontier.pop()
            continue
        if neighbor in on_path:
            continue
        if neighbor == target:
            found.append([*path, target])
            if len(found) >= MAX_PATHS:
                break
            continue
        if len(path) < max_depth:
            path.append(neighbor)
            on_path.add(neighbor)
            frontier.append(iter(sorted(neighbors(neighbor))))

    return found

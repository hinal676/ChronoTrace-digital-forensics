"""Construction of the NetworkX relationship graph from normalized events (spec 7, 8).

Devices are nodes; repeated communication between the same ordered pair is folded
into a single directed edge carrying aggregate metadata. Aggregating (rather than
keeping one edge per event) is what makes the edges weightable, so Dijkstra and A*
have a meaningful cost to minimise; individual event ids are retained on the edge
for drill-down.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

import networkx as nx

from app.models.common import Direction, WeightStrategy

__all__ = [
    "build_graph",
    "edge_weight",
    "weight_function",
    "min_edge_weight",
    "neighbors_fn",
    "edge_summary",
    "graph_stats",
    "matches_filter",
    "MAX_EVENT_IDS_PER_EDGE",
]

# Per-edge cap on retained event ids: enough for drill-down without turning the
# graph into a second copy of the events collection.
MAX_EVENT_IDS_PER_EDGE = 25


def matches_filter(event: Mapping[str, Any], flt: Mapping[str, Any] | None) -> bool:
    """Whether an event passes an optional graph filter."""
    if not flt:
        return True
    start = flt.get("start_time")
    if start is not None and event.get("timestamp", 0) < start:
        return False
    end = flt.get("end_time")
    if end is not None and event.get("timestamp", 0) > end:
        return False
    protocol = flt.get("protocol")
    if protocol is not None and event.get("protocol") != protocol:
        return False
    dst_port = flt.get("dst_port")
    if dst_port is not None and event.get("dst_port") != dst_port:
        return False
    min_bytes = flt.get("min_bytes")
    if min_bytes is not None and event.get("total_bytes", 0) < min_bytes:
        return False
    return True


def build_graph(
    events: Iterable[Mapping[str, Any]],
    *,
    filter: Mapping[str, Any] | None = None,
) -> nx.DiGraph:
    """Fold events into an aggregated directed device graph.

    Edge attributes: ``event_count``, ``total_bytes``, ``total_packets``,
    ``total_duration``, ``protocols``, ``dst_ports``, ``first_seen``,
    ``last_seen``, ``event_ids``.
    """
    graph = nx.DiGraph()
    event_count = 0

    for event in events:
        if not matches_filter(event, filter):
            continue
        src = event.get("src_device")
        dst = event.get("dst_device")
        if not src or not dst:
            continue

        event_count += 1
        timestamp = int(event.get("timestamp") or 0)
        src_bytes = int(event.get("src_bytes") or 0)
        dst_bytes = int(event.get("dst_bytes") or 0)
        src_packets = int(event.get("src_packets") or 0)
        dst_packets = int(event.get("dst_packets") or 0)
        total_bytes = int(event.get("total_bytes") or (src_bytes + dst_bytes))
        total_packets = int(event.get("total_packets") or (src_packets + dst_packets))
        duration = float(event.get("duration") or 0.0)
        protocol = event.get("protocol")
        dst_port = event.get("dst_port")

        for node, bytes_out, bytes_in, packets_out, packets_in, out_ev, in_ev in (
            (src, src_bytes, dst_bytes, src_packets, dst_packets, 1, 0),
            (dst, dst_bytes, src_bytes, dst_packets, src_packets, 0, 1),
        ):
            if node not in graph:
                graph.add_node(
                    node,
                    events_out=0, events_in=0,
                    bytes_out=0, bytes_in=0,
                    packets_out=0, packets_in=0,
                    first_seen=timestamp, last_seen=timestamp,
                )
            attrs = graph.nodes[node]
            attrs["events_out"] += out_ev
            attrs["events_in"] += in_ev
            attrs["bytes_out"] += bytes_out
            attrs["bytes_in"] += bytes_in
            attrs["packets_out"] += packets_out
            attrs["packets_in"] += packets_in
            attrs["first_seen"] = min(attrs["first_seen"], timestamp)
            attrs["last_seen"] = max(attrs["last_seen"], timestamp)

        if graph.has_edge(src, dst):
            edge = graph.edges[src, dst]
            edge["event_count"] += 1
            edge["total_bytes"] += total_bytes
            edge["total_packets"] += total_packets
            edge["total_duration"] += duration
            edge["first_seen"] = min(edge["first_seen"], timestamp)
            edge["last_seen"] = max(edge["last_seen"], timestamp)
            if protocol is not None:
                edge["protocols"].add(protocol)
            if dst_port is not None:
                edge["dst_ports"].add(dst_port)
            if len(edge["event_ids"]) < MAX_EVENT_IDS_PER_EDGE:
                edge["event_ids"].append(event.get("event_id"))
        else:
            graph.add_edge(
                src, dst,
                event_count=1,
                total_bytes=total_bytes,
                total_packets=total_packets,
                total_duration=duration,
                protocols={protocol} if protocol is not None else set(),
                dst_ports={dst_port} if dst_port is not None else set(),
                first_seen=timestamp,
                last_seen=timestamp,
                event_ids=[event.get("event_id")],
            )

    graph.graph["event_count"] = event_count
    graph.graph["built_at"] = time.time()
    graph.graph["filter"] = dict(filter) if filter else {}
    return graph


def edge_weight(data: Mapping[str, Any], strategy: WeightStrategy | str) -> float:
    """Cost of traversing one aggregated edge.

    Every strategy returns a strictly positive cost where *lower means a stronger
    relationship*, which is what makes the shortest path the most plausible
    communication route. Positivity is required for Dijkstra to be correct.
    """
    strategy = WeightStrategy(strategy)
    count = max(int(data.get("event_count", 1)), 1)
    total_bytes = max(int(data.get("total_bytes", 0)), 0)
    total_duration = max(float(data.get("total_duration", 0.0)), 0.0)

    if strategy is WeightStrategy.HOPS:
        return 1.0
    if strategy is WeightStrategy.FREQUENCY:
        # Frequent contact is cheap to traverse.
        return 1.0 / count
    if strategy is WeightStrategy.BYTES:
        # Log-scaled: byte volumes span six orders of magnitude in this dataset.
        return 1.0 / (1.0 + math.log10(1.0 + total_bytes))
    if strategy is WeightStrategy.DURATION:
        avg_duration = total_duration / count
        return 1.0 / (1.0 + math.log10(1.0 + avg_duration))
    # STRENGTH: blend contact frequency, volume and dwell time.
    score = (
        math.log1p(count)
        + 0.5 * math.log10(1.0 + total_bytes)
        + 0.25 * math.log10(1.0 + total_duration)
    )
    return 1.0 / (1.0 + score)


def weight_function(strategy: WeightStrategy | str) -> Callable[[Mapping[str, Any]], float]:
    """Bind a weight strategy into a single-argument callable."""
    resolved = WeightStrategy(strategy)
    return lambda data: edge_weight(data, resolved)


def min_edge_weight(graph: nx.DiGraph, strategy: WeightStrategy | str) -> float:
    """Smallest edge cost in the graph.

    A* multiplies this by a hop lower bound to build an admissible heuristic.
    """
    weigh = weight_function(strategy)
    weights = [weigh(data) for _, _, data in graph.edges(data=True)]
    return min(weights) if weights else 0.0


def neighbors_fn(
    graph: nx.DiGraph, direction: Direction | str
) -> Callable[[str], Iterable[str]]:
    """Neighbour accessor honouring the requested traversal direction."""
    direction = Direction(direction)
    if direction is Direction.OUTBOUND:
        return graph.successors
    if direction is Direction.INBOUND:
        return graph.predecessors

    def both(node: str) -> Iterable[str]:
        # dict.fromkeys de-duplicates while preserving order.
        return dict.fromkeys((*graph.successors(node), *graph.predecessors(node)))

    return both


def edge_data_between(
    graph: nx.DiGraph, u: str, v: str, direction: Direction | str = Direction.OUTBOUND
) -> tuple[str, str, Mapping[str, Any]] | None:
    """Resolve the stored edge between two adjacent nodes for either direction."""
    if graph.has_edge(u, v):
        return u, v, graph.edges[u, v]
    if Direction(direction) is not Direction.OUTBOUND and graph.has_edge(v, u):
        return v, u, graph.edges[v, u]
    return None


def edge_summary(
    graph: nx.DiGraph,
    u: str,
    v: str,
    *,
    strategy: WeightStrategy | str | None = None,
    direction: Direction | str = Direction.OUTBOUND,
) -> dict[str, Any] | None:
    """Serializable summary of one edge, optionally including its cost."""
    resolved = edge_data_between(graph, u, v, direction)
    if resolved is None:
        return None
    source, target, data = resolved
    summary: dict[str, Any] = {
        "source": source,
        "target": target,
        "event_count": data.get("event_count", 0),
        "total_bytes": data.get("total_bytes", 0),
        "total_packets": data.get("total_packets", 0),
        "total_duration": round(float(data.get("total_duration", 0.0)), 3),
        "protocols": sorted(data.get("protocols", set())),
        "dst_ports": sorted(data.get("dst_ports", set())),
        "first_seen": data.get("first_seen"),
        "last_seen": data.get("last_seen"),
    }
    if strategy is not None:
        summary["weight"] = round(edge_weight(data, strategy), 6)
    return summary


def path_edges(
    graph: nx.DiGraph,
    path: Sequence[str],
    *,
    strategy: WeightStrategy | str | None = None,
    direction: Direction | str = Direction.OUTBOUND,
) -> list[dict[str, Any]]:
    """Edge summaries along a path."""
    summaries = []
    for u, v in zip(path, path[1:]):
        summary = edge_summary(graph, u, v, strategy=strategy, direction=direction)
        if summary is not None:
            summaries.append(summary)
    return summaries


def graph_stats(graph: nx.DiGraph, *, top: int = 5) -> dict[str, Any]:
    """Overall shape of the relationship graph (spec 9)."""
    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()

    talkers = sorted(
        graph.nodes(data=True), key=lambda item: item[1].get("bytes_out", 0), reverse=True
    )[:top]
    receivers = sorted(
        graph.nodes(data=True), key=lambda item: item[1].get("bytes_in", 0), reverse=True
    )[:top]
    busiest = sorted(
        graph.edges(data=True), key=lambda item: item[2].get("event_count", 0), reverse=True
    )[:top]

    undirected = graph.to_undirected(as_view=True)
    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "event_count": int(graph.graph.get("event_count", 0)),
        "density": round(nx.density(graph), 6) if node_count > 1 else 0.0,
        "is_weakly_connected": nx.is_weakly_connected(graph) if node_count else False,
        "weakly_connected_components": nx.number_weakly_connected_components(graph)
        if node_count
        else 0,
        "strongly_connected_components": nx.number_strongly_connected_components(graph)
        if node_count
        else 0,
        "average_out_degree": round(edge_count / node_count, 3) if node_count else 0.0,
        "total_bytes": sum(data.get("total_bytes", 0) for _, _, data in graph.edges(data=True)),
        "top_talkers": [
            {"device": n, "bytes_out": d.get("bytes_out", 0), "events_out": d.get("events_out", 0)}
            for n, d in talkers
        ],
        "top_receivers": [
            {"device": n, "bytes_in": d.get("bytes_in", 0), "events_in": d.get("events_in", 0)}
            for n, d in receivers
        ],
        "busiest_edges": [
            edge_summary(graph, u, v, strategy=WeightStrategy.STRENGTH) for u, v, _ in busiest
        ],
        "built_at": graph.graph.get("built_at"),
        "undirected_edges": undirected.number_of_edges(),
    }

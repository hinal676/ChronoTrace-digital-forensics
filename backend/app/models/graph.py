"""Request/response models for the graph algorithm APIs (spec 10, 12)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import Direction, Heuristic, WeightStrategy


class GraphFilter(BaseModel):
    """Restricts which events are folded into the graph before traversal."""

    model_config = ConfigDict(extra="forbid")

    start_time: int | None = Field(None, ge=0, description="Only events at/after this epoch.")
    end_time: int | None = Field(None, ge=0, description="Only events at/before this epoch.")
    protocol: int | None = Field(None, ge=0, le=255)
    dst_port: int | None = Field(None, ge=0, le=65535)
    min_bytes: int | None = Field(None, ge=0, description="Minimum total_bytes per event.")


class TraversalRequest(BaseModel):
    """Input for BFS and DFS."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1, description="Device to start from.")
    target: str | None = Field(None, description="Optional device to stop at / find paths to.")
    max_depth: int = Field(3, ge=1, le=20, description="Traversal depth limit.")
    max_nodes: int = Field(500, ge=1, le=20_000, description="Safety cap on visited nodes.")
    direction: Direction = Direction.OUTBOUND
    filter: GraphFilter = Field(default_factory=GraphFilter)


class PathRequest(BaseModel):
    """Input for Dijkstra and A*."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    weight: WeightStrategy = WeightStrategy.STRENGTH
    heuristic: Heuristic = Field(
        Heuristic.HOP_LOWER_BOUND, description="A* only; ignored by Dijkstra."
    )
    direction: Direction = Direction.OUTBOUND
    k: int = Field(1, ge=1, le=10, description="Return up to k shortest paths (Dijkstra only).")
    filter: GraphFilter = Field(default_factory=GraphFilter)


class EdgeSummary(BaseModel):
    """An aggregated device-to-device relationship."""

    source: str
    target: str
    event_count: int
    total_bytes: int
    total_packets: int
    total_duration: float
    protocols: list[int] = Field(default_factory=list)
    dst_ports: list[int] = Field(default_factory=list)
    first_seen: int | None = None
    last_seen: int | None = None
    weight: float | None = Field(None, description="Cost under the requested weight strategy.")


class NodeAtDepth(BaseModel):
    device: str
    depth: int
    discovered_from: str | None = None


class TraversalResponse(BaseModel):
    algorithm: str
    source: str
    target: str | None = None
    direction: Direction
    max_depth: int
    node_count: int
    nodes: list[NodeAtDepth]
    levels: dict[int, list[str]] = Field(
        default_factory=dict, description="Devices grouped by hop distance from the source."
    )
    tree_edges: list[tuple[str, str]] = Field(default_factory=list)
    order: list[str] = Field(default_factory=list, description="Visit order (DFS discovery order).")
    paths_to_target: list[list[str]] = Field(default_factory=list)
    truncated: bool = False
    graph_stats: dict[str, int] = Field(default_factory=dict)


class PathResponse(BaseModel):
    algorithm: str
    source: str
    target: str
    weight_strategy: WeightStrategy
    heuristic: Heuristic | None = None
    found: bool
    cost: float | None = None
    hops: int | None = None
    path: list[str] = Field(default_factory=list)
    edges: list[EdgeSummary] = Field(default_factory=list)
    alternative_paths: list[dict] = Field(default_factory=list)
    nodes_explored: int | None = Field(
        None, description="Nodes A* expanded; shows the heuristic's benefit over Dijkstra."
    )
    graph_stats: dict[str, int] = Field(default_factory=dict)


class GraphStatsResponse(BaseModel):
    """Overall shape of the relationship graph."""

    node_count: int
    edge_count: int
    event_count: int
    density: float
    is_weakly_connected: bool
    weakly_connected_components: int
    strongly_connected_components: int
    average_out_degree: float
    total_bytes: int
    top_talkers: list[dict] = Field(default_factory=list)
    top_receivers: list[dict] = Field(default_factory=list)
    busiest_edges: list[EdgeSummary] = Field(default_factory=list)
    built_at: float | None = None


class NeighborhoodResponse(BaseModel):
    """Induced subgraph around a device, ready for a future frontend to draw."""

    device: str
    depth: int
    nodes: list[dict]
    edges: list[EdgeSummary]

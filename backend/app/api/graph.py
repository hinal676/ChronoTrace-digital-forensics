"""Graph algorithm endpoints: BFS, DFS, Dijkstra and A* (spec 10, 12)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.models.common import Direction
from app.models.graph import (
    GraphStatsResponse,
    NeighborhoodResponse,
    PathRequest,
    PathResponse,
    TraversalRequest,
    TraversalResponse,
)
from app.services import graph_service

router = APIRouter(prefix="/graph", tags=["graph"])


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/bfs",
    response_model=TraversalResponse,
    summary="Breadth-first search from a device",
)
async def bfs(request: TraversalRequest) -> TraversalResponse:
    """Find devices within N hops, grouped by hop distance."""
    try:
        result = await graph_service.run_bfs(
            source=request.source,
            target=request.target,
            max_depth=request.max_depth,
            max_nodes=request.max_nodes,
            direction=request.direction,
            filter_dict=request.filter.model_dump(exclude_none=True),
        )
    except graph_service.DeviceNotInGraphError as exc:
        raise _not_found(exc) from exc
    return TraversalResponse(**result)


@router.post(
    "/dfs",
    response_model=TraversalResponse,
    summary="Depth-first search from a device",
)
async def dfs(request: TraversalRequest) -> TraversalResponse:
    """Follow communication chains depth-first; enumerates routes when a target is given."""
    try:
        result = await graph_service.run_dfs(
            source=request.source,
            target=request.target,
            max_depth=request.max_depth,
            max_nodes=request.max_nodes,
            direction=request.direction,
            filter_dict=request.filter.model_dump(exclude_none=True),
        )
    except graph_service.DeviceNotInGraphError as exc:
        raise _not_found(exc) from exc
    return TraversalResponse(**result)


@router.post(
    "/dijkstra",
    response_model=PathResponse,
    summary="Lowest-cost path between two devices",
)
async def dijkstra(request: PathRequest) -> PathResponse:
    """Lowest-cost communication path under the chosen weight strategy.

    Set ``k`` above 1 to receive alternative routes (Yen's algorithm).
    """
    try:
        result = await graph_service.run_dijkstra(
            source=request.source,
            target=request.target,
            weight=request.weight,
            direction=request.direction,
            k=request.k,
            filter_dict=request.filter.model_dump(exclude_none=True),
        )
    except graph_service.DeviceNotInGraphError as exc:
        raise _not_found(exc) from exc
    return PathResponse(**result)


@router.post(
    "/astar",
    response_model=PathResponse,
    summary="Heuristic-guided path between two devices",
)
async def astar(request: PathRequest) -> PathResponse:
    """A* path search. Returns the same optimal cost as Dijkstra by expanding fewer nodes."""
    try:
        result = await graph_service.run_astar(
            source=request.source,
            target=request.target,
            weight=request.weight,
            heuristic=request.heuristic,
            direction=request.direction,
            filter_dict=request.filter.model_dump(exclude_none=True),
        )
    except graph_service.DeviceNotInGraphError as exc:
        raise _not_found(exc) from exc
    return PathResponse(**result)


@router.get(
    "/stats",
    response_model=GraphStatsResponse,
    summary="Shape and hot spots of the relationship graph",
)
async def stats(
    start_time: int | None = Query(None, ge=0),
    end_time: int | None = Query(None, ge=0),
    protocol: int | None = Query(None, ge=0, le=255),
    dst_port: int | None = Query(None, ge=0, le=65535),
    min_bytes: int | None = Query(None, ge=0),
) -> GraphStatsResponse:
    filters = {
        "start_time": start_time, "end_time": end_time,
        "protocol": protocol, "dst_port": dst_port, "min_bytes": min_bytes,
    }
    result = await graph_service.stats({k: v for k, v in filters.items() if v is not None})
    return GraphStatsResponse(**result)


@router.get(
    "/neighborhood/{device}",
    response_model=NeighborhoodResponse,
    summary="Induced subgraph around a device",
)
async def neighborhood(
    device: str,
    depth: int = Query(1, ge=1, le=5),
    direction: Direction = Query(Direction.BOTH),
    max_nodes: int = Query(200, ge=1, le=5000),
) -> NeighborhoodResponse:
    """Nodes and edges around a device -- the payload a future frontend would draw."""
    try:
        result = await graph_service.neighborhood(
            device, depth=depth, direction=direction, max_nodes=max_nodes
        )
    except graph_service.DeviceNotInGraphError as exc:
        raise _not_found(exc) from exc
    return NeighborhoodResponse(**result)


@router.post("/rebuild", summary="Force a rebuild of the cached graph")
async def rebuild() -> dict:
    """Drop the cached graph and rebuild it from MongoDB immediately."""
    graph_service.invalidate()
    result = await graph_service.stats()
    return {
        "status": "rebuilt",
        "node_count": result["node_count"],
        "edge_count": result["edge_count"],
        "event_count": result["event_count"],
    }

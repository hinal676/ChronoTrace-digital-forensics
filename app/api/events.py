"""Event ingestion, retrieval and filtering endpoints (spec 12)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.models.common import Page, SortOrder, StatusResponse
from app.models.event import (
    DeviceSummary,
    Event,
    EventBulkCreate,
    EventCreate,
    IngestResult,
    RelationshipResponse,
)
from app.services import event_service, graph_service
from app.services.event_service import EventFilter

router = APIRouter(tags=["events"])

SORTABLE = {
    "timestamp", "duration", "total_bytes", "total_packets",
    "src_bytes", "dst_bytes", "src_device", "dst_device", "dst_port",
}


@router.post(
    "/events",
    response_model=IngestResult,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a network event",
)
async def create_event(payload: EventCreate) -> IngestResult:
    """Normalize and store one event. Re-posting the same event is a no-op upsert."""
    result = await event_service.insert_events(
        [payload.to_document()], pre_normalized=True
    )
    graph_service.invalidate()
    return IngestResult(**result)


@router.post(
    "/events/bulk",
    response_model=IngestResult,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a batch of network events",
)
async def create_events(payload: EventBulkCreate) -> IngestResult:
    documents = [event.to_document(source=payload.source) for event in payload.events]
    result = await event_service.insert_events(documents, pre_normalized=True)
    graph_service.invalidate()
    return IngestResult(**result)


@router.get(
    "/events",
    response_model=Page[Event],
    summary="List and filter network events",
)
async def list_events(
    src_device: str | None = Query(None, description="Exact source device."),
    dst_device: str | None = Query(None, description="Exact destination device."),
    device: str | None = Query(None, description="Match as either source or destination."),
    protocol: int | None = Query(None, ge=0, le=255, description="Protocol number, e.g. 6 for TCP."),
    src_port: int | None = Query(None, ge=0, le=65535),
    dst_port: int | None = Query(None, ge=0, le=65535),
    start_time: int | None = Query(None, ge=0, description="Epoch seconds, inclusive."),
    end_time: int | None = Query(None, ge=0, description="Epoch seconds, inclusive."),
    min_duration: float | None = Query(None, ge=0),
    max_duration: float | None = Query(None, ge=0),
    min_bytes: int | None = Query(None, ge=0, description="Minimum total_bytes."),
    max_bytes: int | None = Query(None, ge=0),
    source: str | None = Query(None, description='Origin tag, e.g. "dataset" or "collector".'),
    limit: int = Query(50, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    sort_by: str = Query("timestamp"),
    order: SortOrder = Query(SortOrder.DESC),
) -> Page[Event]:
    if sort_by not in SORTABLE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"sort_by must be one of: {', '.join(sorted(SORTABLE))}",
        )

    page = await event_service.list_events(
        EventFilter(
            src_device=src_device, dst_device=dst_device, device=device,
            protocol=protocol, src_port=src_port, dst_port=dst_port,
            start_time=start_time, end_time=end_time,
            min_duration=min_duration, max_duration=max_duration,
            min_bytes=min_bytes, max_bytes=max_bytes, source=source,
        ),
        limit=limit, skip=skip, sort_by=sort_by, order=order,
    )
    return Page[Event](**page)


@router.get("/events/{event_id}", response_model=Event, summary="Fetch one event")
async def get_event(event_id: str) -> Event:
    document = await event_service.get_event(event_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no event with id {event_id}"
        )
    return Event(**document)


@router.delete("/events/{event_id}", response_model=StatusResponse, summary="Delete one event")
async def delete_event(event_id: str) -> StatusResponse:
    if not await event_service.delete_event(event_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no event with id {event_id}"
        )
    graph_service.invalidate()
    return StatusResponse(status="deleted", detail=event_id)


# --- Device views -----------------------------------------------------------


@router.get("/devices", summary="List devices ranked by activity")
async def list_devices(
    limit: int = Query(200, ge=1, le=5000), skip: int = Query(0, ge=0)
) -> dict:
    return await event_service.list_devices(limit=limit, skip=skip)


@router.get("/devices/{device}", response_model=DeviceSummary, summary="Device activity profile")
async def get_device(device: str) -> DeviceSummary:
    summary = await event_service.device_summary(device)
    if not summary.get("total_events"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no events involve device {device}"
        )
    return DeviceSummary(**summary)


@router.get(
    "/relationships/{device}",
    response_model=RelationshipResponse,
    tags=["relationships"],
    summary="Devices and traffic related to a device",
)
async def get_relationships(
    device: str,
    limit: int = Query(100, ge=1, le=1000, description="Max related devices."),
    recent: int = Query(10, ge=0, le=100, description="Recent events to include."),
) -> RelationshipResponse:
    summary = await event_service.device_summary(device)
    if not summary.get("total_events"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no events involve device {device}"
        )
    related = await event_service.related_devices(device, limit=limit)
    events = (
        await event_service.recent_events_for_device(device, limit=recent) if recent else []
    )
    return RelationshipResponse(
        device=device,
        summary=DeviceSummary(**summary),
        related=related,
        recent_events=events,
    )


@router.get("/protocols", tags=["protocols"], summary="Traffic grouped by protocol")
async def get_protocols() -> list[dict]:
    return await event_service.protocol_breakdown()


@router.get("/ports", tags=["protocols"], summary="Most-contacted destination ports")
async def get_ports(limit: int = Query(20, ge=1, le=200)) -> list[dict]:
    return await event_service.top_ports(limit=limit)

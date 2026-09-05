"""Timeline endpoint: events ordered or bucketed by time (spec 12)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.models.event import TimelineResponse
from app.services import event_service
from app.services.event_service import EventFilter

router = APIRouter(tags=["timeline"])


@router.get(
    "/timeline",
    response_model=TimelineResponse,
    summary="Activity over time, bucketed or raw",
)
async def get_timeline(
    src_device: str | None = Query(None),
    dst_device: str | None = Query(None),
    device: str | None = Query(None, description="Match as either source or destination."),
    protocol: int | None = Query(None, ge=0, le=255),
    dst_port: int | None = Query(None, ge=0, le=65535),
    start_time: int | None = Query(None, ge=0),
    end_time: int | None = Query(None, ge=0),
    min_bytes: int | None = Query(None, ge=0),
    interval: int | None = Query(
        3600,
        ge=1,
        description="Bucket width in seconds. Pass raw=true for individual events instead.",
    ),
    raw: bool = Query(False, description="Return individual events in time order."),
    limit: int = Query(1000, ge=1, le=10_000),
) -> TimelineResponse:
    """Aggregate activity into fixed-width time buckets, or list raw events.

    Buckets are the default because a 5,000-event window is unreadable as a list
    but immediately legible as a per-hour series.
    """
    result = await event_service.timeline(
        EventFilter(
            src_device=src_device, dst_device=dst_device, device=device,
            protocol=protocol, dst_port=dst_port,
            start_time=start_time, end_time=end_time, min_bytes=min_bytes,
        ),
        interval=None if raw else interval,
        limit=limit,
    )
    return TimelineResponse(**result)

"""Event models: ingestion input, stored representation and API output."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.collector.normalizer import (
    MAX_PORT,
    NormalizationError,
    normalize_event,
    parse_port,
)


class EventCreate(BaseModel):
    """A raw network event submitted to the API.

    Accepts the dataset's field names (``Time``, ``SrcDevice``, ``SrcPort`` as
    ``"Port62917"``) as well as the canonical ones, because the live collector and
    the CSV loader share this entry point.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        json_schema_extra={
            "example": {
                "Time": 1720001344,
                "Duration": 10540,
                "SrcDevice": "Comp679356",
                "DstDevice": "Comp654763",
                "Protocol": 6,
                "SrcPort": "Port62917",
                "DstPort": 443,
                "SrcPackets": 4636,
                "DstPackets": 9480,
                "SrcBytes": 3782976,
                "DstBytes": 6948840,
            }
        },
    )

    timestamp: int = Field(..., ge=0, alias="Time", description="Event start time, epoch seconds.")
    duration: float = Field(..., ge=0, alias="Duration", description="Event duration in seconds.")
    src_device: str = Field(..., min_length=1, alias="SrcDevice")
    dst_device: str = Field(..., min_length=1, alias="DstDevice")
    protocol: int = Field(..., ge=0, le=255, alias="Protocol")
    src_port: int | str = Field(..., alias="SrcPort", description='Integer or "Port62917" label.')
    dst_port: int | str = Field(..., alias="DstPort")
    src_packets: int = Field(..., ge=0, alias="SrcPackets")
    dst_packets: int = Field(..., ge=0, alias="DstPackets")
    src_bytes: int = Field(..., ge=0, alias="SrcBytes")
    dst_bytes: int = Field(..., ge=0, alias="DstBytes")
    source: str | None = Field(default=None, description='Origin tag, e.g. "dataset" or "collector".')

    @field_validator("src_port", "dst_port")
    @classmethod
    def _validate_port(cls, value: int | str, info: Any) -> int:
        try:
            return parse_port(value, field=info.field_name)
        except NormalizationError as exc:
            raise ValueError(str(exc)) from exc

    def to_document(self, *, source: str = "collector") -> dict[str, Any]:
        """Normalize into the canonical stored document."""
        return normalize_event(
            self.model_dump(by_alias=False, exclude_none=True),
            source=self.source or source,
        )


class EventBulkCreate(BaseModel):
    """Batch ingestion payload."""

    model_config = ConfigDict(extra="forbid")

    events: list[EventCreate] = Field(..., min_length=1, max_length=10_000)
    source: str = Field(default="collector")


class Event(BaseModel):
    """A stored, normalized network event."""

    model_config = ConfigDict(extra="ignore")

    event_id: str
    timestamp: int = Field(..., description="Raw epoch seconds, as supplied.")
    event_time: datetime = Field(..., description="UTC timestamp derived from `timestamp`.")
    duration: float

    src_device: str
    dst_device: str
    protocol: int
    protocol_name: str
    src_port: int = Field(..., ge=0, le=MAX_PORT)
    dst_port: int = Field(..., ge=0, le=MAX_PORT)
    dst_service: str | None = None

    src_packets: int
    dst_packets: int
    src_bytes: int
    dst_bytes: int

    # --- Derived (spec 5) ---
    total_packets: int
    total_bytes: int
    packet_ratio: float
    byte_ratio: float
    bytes_per_second: float
    src_bytes_per_packet: float
    dst_bytes_per_packet: float

    source: str = "dataset"


class IngestResult(BaseModel):
    """Outcome of an ingestion request."""

    received: int
    inserted: int
    duplicates: int = Field(0, description="Events already present under the same content hash.")
    rejected: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)


class DeviceSummary(BaseModel):
    """Aggregate activity profile for a single device."""

    device: str
    events_out: int = 0
    events_in: int = 0
    total_events: int = 0
    bytes_out: int = 0
    bytes_in: int = 0
    packets_out: int = 0
    packets_in: int = 0
    unique_destinations: int = 0
    unique_sources: int = 0
    unique_dst_ports: int = 0
    protocols: list[int] = Field(default_factory=list)
    first_seen: int | None = None
    last_seen: int | None = None


class RelatedDevice(BaseModel):
    """One communication partner of a focus device."""

    device: str
    direction: str = Field(..., description='"outbound", "inbound" or "bidirectional".')
    event_count: int
    total_bytes: int
    total_packets: int
    protocols: list[int] = Field(default_factory=list)
    dst_ports: list[int] = Field(default_factory=list)
    first_seen: int | None = None
    last_seen: int | None = None


class RelationshipResponse(BaseModel):
    """Devices and traffic related to a focus device (spec 12, /relationships)."""

    device: str
    summary: DeviceSummary
    related: list[RelatedDevice]
    recent_events: list[Event] = Field(default_factory=list)


class TimelineBucket(BaseModel):
    """One aggregated slice of the activity timeline."""

    bucket_start: int
    bucket_end: int
    bucket_time: datetime
    event_count: int
    total_bytes: int
    total_packets: int
    unique_src_devices: int
    unique_dst_devices: int


class TimelineResponse(BaseModel):
    interval_seconds: int | None = Field(
        None, description="Bucket width; null when raw events were returned."
    )
    start_time: int | None = None
    end_time: int | None = None
    total_events: int
    buckets: list[TimelineBucket] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)

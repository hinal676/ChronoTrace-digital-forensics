"""Collection accessors and index management (spec 6)."""

from __future__ import annotations

import logging

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

from app.database.connection import get_database

logger = logging.getLogger(__name__)

EVENTS = "events"
DEVICES = "devices"
PROTOCOLS = "protocols"
INVESTIGATIONS = "investigations"
ANALYSES = "analyses"


def events(db: AsyncDatabase | None = None) -> AsyncCollection:
    return (db or get_database())[EVENTS]


def devices(db: AsyncDatabase | None = None) -> AsyncCollection:
    return (db or get_database())[DEVICES]


def protocols(db: AsyncDatabase | None = None) -> AsyncCollection:
    return (db or get_database())[PROTOCOLS]


def investigations(db: AsyncDatabase | None = None) -> AsyncCollection:
    return (db or get_database())[INVESTIGATIONS]


def analyses(db: AsyncDatabase | None = None) -> AsyncCollection:
    return (db or get_database())[ANALYSES]


# Indexes chosen to cover the filters the spec lists for /events plus the
# timeline sort and the per-device relationship lookups.
_EVENT_INDEXES = [
    IndexModel([("event_id", ASCENDING)], unique=True, name="uniq_event_id"),
    IndexModel([("timestamp", DESCENDING)], name="ts_desc"),
    IndexModel([("src_device", ASCENDING), ("timestamp", DESCENDING)], name="src_ts"),
    IndexModel([("dst_device", ASCENDING), ("timestamp", DESCENDING)], name="dst_ts"),
    IndexModel([("src_device", ASCENDING), ("dst_device", ASCENDING)], name="pair"),
    IndexModel([("protocol", ASCENDING)], name="protocol"),
    IndexModel([("dst_port", ASCENDING)], name="dst_port"),
    IndexModel([("src_port", ASCENDING)], name="src_port"),
    IndexModel([("total_bytes", DESCENDING)], name="total_bytes_desc"),
    IndexModel([("duration", DESCENDING)], name="duration_desc"),
]

_INVESTIGATION_INDEXES = [
    IndexModel([("investigation_id", ASCENDING)], unique=True, name="uniq_investigation_id"),
    IndexModel([("device", ASCENDING)], name="device"),
    IndexModel([("created_at", DESCENDING)], name="created_desc"),
    IndexModel([("status", ASCENDING)], name="status"),
]

_ANALYSIS_INDEXES = [
    IndexModel([("analysis_id", ASCENDING)], unique=True, name="uniq_analysis_id"),
    IndexModel([("created_at", DESCENDING)], name="created_desc"),
]

_DEVICE_INDEXES = [
    IndexModel([("device", ASCENDING)], unique=True, name="uniq_device"),
    IndexModel([("total_events", DESCENDING)], name="total_events_desc"),
]

_PROTOCOL_INDEXES = [
    IndexModel([("protocol", ASCENDING)], unique=True, name="uniq_protocol"),
]


async def ensure_indexes(db: AsyncDatabase | None = None) -> dict[str, list[str]]:
    """Create every index the backend relies on. Safe to call repeatedly."""
    database = db or get_database()
    created: dict[str, list[str]] = {}
    for name, models in (
        (EVENTS, _EVENT_INDEXES),
        (INVESTIGATIONS, _INVESTIGATION_INDEXES),
        (ANALYSES, _ANALYSIS_INDEXES),
        (DEVICES, _DEVICE_INDEXES),
        (PROTOCOLS, _PROTOCOL_INDEXES),
    ):
        created[name] = await database[name].create_indexes(models)
    logger.info("Ensured indexes on %s", ", ".join(created))
    return created

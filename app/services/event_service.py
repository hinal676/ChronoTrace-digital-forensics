"""Event storage, filtering, timeline and relationship queries (spec 12)."""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping, Sequence

from pymongo import ASCENDING, DESCENDING, UpdateOne
from pymongo.errors import BulkWriteError

from app.collector.normalizer import NormalizationError, normalize_event
from app.database import collections
from app.models.common import SortOrder

logger = logging.getLogger(__name__)

# Never return Mongo's internal id to API clients.
PROJECTION: dict[str, int] = {"_id": 0}


class EventFilter:
    """Translates the API's documented filters into a MongoDB query.

    Kept as one class so ``/events``, ``/timeline`` and ``/analysis`` cannot drift
    apart in how they interpret the same query parameters.
    """

    def __init__(
        self,
        *,
        src_device: str | None = None,
        dst_device: str | None = None,
        device: str | None = None,
        protocol: int | None = None,
        protocol_name: str | None = None,
        src_port: int | None = None,
        dst_port: int | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        min_duration: float | None = None,
        max_duration: float | None = None,
        min_bytes: int | None = None,
        max_bytes: int | None = None,
        min_packets: int | None = None,
        source: str | None = None,
    ) -> None:
        self.src_device = src_device
        self.dst_device = dst_device
        self.device = device
        self.protocol = protocol
        self.protocol_name = protocol_name
        self.src_port = src_port
        self.dst_port = dst_port
        self.start_time = start_time
        self.end_time = end_time
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.min_bytes = min_bytes
        self.max_bytes = max_bytes
        self.min_packets = min_packets
        self.source = source

    def to_query(self) -> dict[str, Any]:
        query: dict[str, Any] = {}

        for field, value in (
            ("src_device", self.src_device),
            ("dst_device", self.dst_device),
            ("protocol", self.protocol),
            ("protocol_name", self.protocol_name),
            ("src_port", self.src_port),
            ("dst_port", self.dst_port),
            ("source", self.source),
        ):
            if value is not None:
                query[field] = value

        # `device` matches either end of the conversation.
        if self.device is not None:
            query["$or"] = [{"src_device": self.device}, {"dst_device": self.device}]

        for field, low, high in (
            ("timestamp", self.start_time, self.end_time),
            ("duration", self.min_duration, self.max_duration),
            ("total_bytes", self.min_bytes, self.max_bytes),
            ("total_packets", self.min_packets, None),
        ):
            bounds: dict[str, Any] = {}
            if low is not None:
                bounds["$gte"] = low
            if high is not None:
                bounds["$lte"] = high
            if bounds:
                query[field] = bounds

        return query


async def insert_events(
    records: Iterable[Mapping[str, Any]],
    *,
    source: str = "collector",
    pre_normalized: bool = False,
) -> dict[str, Any]:
    """Upsert events by ``event_id``.

    Upsert rather than insert makes ingestion idempotent: re-loading the CSV or
    replaying a collector buffer updates in place instead of duplicating.
    """
    operations: list[UpdateOne] = []
    event_ids: list[str] = []
    errors: list[dict[str, Any]] = []
    received = 0

    for index, record in enumerate(records):
        received += 1
        try:
            document = dict(record) if pre_normalized else normalize_event(record, source=source)
        except NormalizationError as exc:
            errors.append({"index": index, "error": str(exc)})
            continue
        event_ids.append(document["event_id"])
        operations.append(
            UpdateOne({"event_id": document["event_id"]}, {"$set": document}, upsert=True)
        )

    inserted = duplicates = 0
    if operations:
        try:
            result = await collections.events().bulk_write(operations, ordered=False)
            inserted = result.upserted_count
            duplicates = len(operations) - result.upserted_count
        except BulkWriteError as exc:
            logger.error("bulk write failed: %s", exc.details)
            errors.append({"error": "bulk write partially failed", "detail": str(exc)})
            inserted = exc.details.get("nUpserted", 0)
            duplicates = len(operations) - inserted

    return {
        "received": received,
        "inserted": inserted,
        "duplicates": duplicates,
        "rejected": len(errors),
        "errors": errors[:50],
        "event_ids": event_ids[:1000],
    }


async def list_events(
    event_filter: EventFilter,
    *,
    limit: int = 50,
    skip: int = 0,
    sort_by: str = "timestamp",
    order: SortOrder | str = SortOrder.DESC,
) -> dict[str, Any]:
    """Paginated event listing with a total count."""
    query = event_filter.to_query()
    direction = DESCENDING if SortOrder(order) is SortOrder.DESC else ASCENDING

    collection = collections.events()
    total = await collection.count_documents(query)
    cursor = collection.find(query, PROJECTION).sort(sort_by, direction).skip(skip).limit(limit)
    items = [document async for document in cursor]

    return {"total": total, "limit": limit, "skip": skip, "count": len(items), "items": items}


async def get_event(event_id: str) -> dict[str, Any] | None:
    return await collections.events().find_one({"event_id": event_id}, PROJECTION)


async def delete_event(event_id: str) -> bool:
    result = await collections.events().delete_one({"event_id": event_id})
    return result.deleted_count > 0


async def fetch_events(
    event_filter: EventFilter, *, limit: int = 10_000, sort_by: str = "timestamp"
) -> list[dict[str, Any]]:
    """Bulk fetch for the graph and ML layers (no pagination envelope)."""
    cursor = (
        collections.events()
        .find(event_filter.to_query(), PROJECTION)
        .sort(sort_by, ASCENDING)
        .limit(limit)
    )
    return [document async for document in cursor]


async def count_events(event_filter: EventFilter | None = None) -> int:
    query = event_filter.to_query() if event_filter else {}
    return await collections.events().count_documents(query)


async def timeline(
    event_filter: EventFilter,
    *,
    interval: int | None = 3600,
    limit: int = 1000,
) -> dict[str, Any]:
    """Events over time (spec 12, /timeline).

    With ``interval`` set, returns fixed-width buckets aggregated in MongoDB; with
    ``interval=None`` returns the raw events in timestamp order.
    """
    query = event_filter.to_query()
    collection = collections.events()
    total = await collection.count_documents(query)

    if interval is None:
        cursor = collection.find(query, PROJECTION).sort("timestamp", ASCENDING).limit(limit)
        events = [document async for document in cursor]
        return {
            "interval_seconds": None,
            "start_time": events[0]["timestamp"] if events else None,
            "end_time": events[-1]["timestamp"] if events else None,
            "total_events": total,
            "buckets": [],
            "events": events,
        }

    pipeline: list[dict[str, Any]] = [
        {"$match": query},
        {
            "$group": {
                # Integer division then multiplication snaps each event to its
                # bucket's start epoch.
                "_id": {
                    "$multiply": [
                        {"$floor": {"$divide": ["$timestamp", interval]}},
                        interval,
                    ]
                },
                "event_count": {"$sum": 1},
                "total_bytes": {"$sum": "$total_bytes"},
                "total_packets": {"$sum": "$total_packets"},
                "src_devices": {"$addToSet": "$src_device"},
                "dst_devices": {"$addToSet": "$dst_device"},
            }
        },
        {"$sort": {"_id": ASCENDING}},
        {"$limit": limit},
        {
            "$project": {
                "_id": 0,
                "bucket_start": {"$toInt": "$_id"},
                "bucket_end": {"$toInt": {"$add": ["$_id", interval]}},
                "bucket_time": {"$toDate": {"$multiply": ["$_id", 1000]}},
                "event_count": 1,
                "total_bytes": 1,
                "total_packets": 1,
                "unique_src_devices": {"$size": "$src_devices"},
                "unique_dst_devices": {"$size": "$dst_devices"},
            }
        },
    ]
    cursor = await collection.aggregate(pipeline)
    buckets = [document async for document in cursor]

    return {
        "interval_seconds": interval,
        "start_time": buckets[0]["bucket_start"] if buckets else None,
        "end_time": buckets[-1]["bucket_end"] if buckets else None,
        "total_events": total,
        "buckets": buckets,
        "events": [],
    }


async def device_summary(device: str) -> dict[str, Any]:
    """Aggregate activity profile for one device (both directions)."""
    pipeline = [
        {"$match": {"$or": [{"src_device": device}, {"dst_device": device}]}},
        {
            "$group": {
                "_id": None,
                "events_out": {"$sum": {"$cond": [{"$eq": ["$src_device", device]}, 1, 0]}},
                "events_in": {"$sum": {"$cond": [{"$eq": ["$dst_device", device]}, 1, 0]}},
                "total_events": {"$sum": 1},
                "bytes_out": {
                    "$sum": {"$cond": [{"$eq": ["$src_device", device]}, "$src_bytes", "$dst_bytes"]}
                },
                "bytes_in": {
                    "$sum": {"$cond": [{"$eq": ["$src_device", device]}, "$dst_bytes", "$src_bytes"]}
                },
                "packets_out": {
                    "$sum": {
                        "$cond": [{"$eq": ["$src_device", device]}, "$src_packets", "$dst_packets"]
                    }
                },
                "packets_in": {
                    "$sum": {
                        "$cond": [{"$eq": ["$src_device", device]}, "$dst_packets", "$src_packets"]
                    }
                },
                "destinations": {
                    "$addToSet": {
                        "$cond": [{"$eq": ["$src_device", device]}, "$dst_device", "$$REMOVE"]
                    }
                },
                "sources": {
                    "$addToSet": {
                        "$cond": [{"$eq": ["$dst_device", device]}, "$src_device", "$$REMOVE"]
                    }
                },
                "dst_ports": {"$addToSet": "$dst_port"},
                "protocols": {"$addToSet": "$protocol"},
                "first_seen": {"$min": "$timestamp"},
                "last_seen": {"$max": "$timestamp"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "events_out": 1, "events_in": 1, "total_events": 1,
                "bytes_out": 1, "bytes_in": 1, "packets_out": 1, "packets_in": 1,
                "unique_destinations": {"$size": "$destinations"},
                "unique_sources": {"$size": "$sources"},
                "unique_dst_ports": {"$size": "$dst_ports"},
                "protocols": 1, "first_seen": 1, "last_seen": 1,
            }
        },
    ]
    cursor = await collections.events().aggregate(pipeline)
    results = [document async for document in cursor]
    if not results:
        return {"device": device, "total_events": 0}
    summary = results[0]
    summary["device"] = device
    summary["protocols"] = sorted(summary.get("protocols", []))
    return summary


async def related_devices(device: str, *, limit: int = 100) -> list[dict[str, Any]]:
    """Communication partners of a device, aggregated per peer (spec 12)."""
    pipeline = [
        {"$match": {"$or": [{"src_device": device}, {"dst_device": device}]}},
        {
            "$group": {
                "_id": {
                    "peer": {
                        "$cond": [{"$eq": ["$src_device", device]}, "$dst_device", "$src_device"]
                    }
                },
                "event_count": {"$sum": 1},
                "outbound": {"$sum": {"$cond": [{"$eq": ["$src_device", device]}, 1, 0]}},
                "inbound": {"$sum": {"$cond": [{"$eq": ["$dst_device", device]}, 1, 0]}},
                "total_bytes": {"$sum": "$total_bytes"},
                "total_packets": {"$sum": "$total_packets"},
                "protocols": {"$addToSet": "$protocol"},
                "dst_ports": {"$addToSet": "$dst_port"},
                "first_seen": {"$min": "$timestamp"},
                "last_seen": {"$max": "$timestamp"},
            }
        },
        {"$sort": {"event_count": DESCENDING}},
        {"$limit": limit},
    ]

    peers: list[dict[str, Any]] = []
    cursor = await collections.events().aggregate(pipeline)
    async for document in cursor:
        outbound, inbound = document["outbound"], document["inbound"]
        direction = (
            "bidirectional" if outbound and inbound else "outbound" if outbound else "inbound"
        )
        peers.append(
            {
                "device": document["_id"]["peer"],
                "direction": direction,
                "event_count": document["event_count"],
                "total_bytes": document["total_bytes"],
                "total_packets": document["total_packets"],
                "protocols": sorted(document.get("protocols", [])),
                "dst_ports": sorted(document.get("dst_ports", []))[:50],
                "first_seen": document.get("first_seen"),
                "last_seen": document.get("last_seen"),
            }
        )
    return peers


async def list_devices(*, limit: int = 200, skip: int = 0) -> dict[str, Any]:
    """All devices seen in either direction, ranked by activity."""
    pipeline = [
        {
            "$facet": {
                "outbound": [
                    {
                        "$group": {
                            "_id": "$src_device",
                            "events_out": {"$sum": 1},
                            "bytes_out": {"$sum": "$src_bytes"},
                        }
                    }
                ],
                "inbound": [
                    {
                        "$group": {
                            "_id": "$dst_device",
                            "events_in": {"$sum": 1},
                            "bytes_in": {"$sum": "$dst_bytes"},
                        }
                    }
                ],
            }
        }
    ]
    cursor = await collections.events().aggregate(pipeline)
    facets = [document async for document in cursor]
    if not facets:
        return {"total": 0, "limit": limit, "skip": skip, "count": 0, "items": []}

    merged: dict[str, dict[str, Any]] = {}
    for entry in facets[0].get("outbound", []):
        merged.setdefault(entry["_id"], {"device": entry["_id"]}).update(
            events_out=entry["events_out"], bytes_out=entry["bytes_out"]
        )
    for entry in facets[0].get("inbound", []):
        merged.setdefault(entry["_id"], {"device": entry["_id"]}).update(
            events_in=entry["events_in"], bytes_in=entry["bytes_in"]
        )

    devices = []
    for record in merged.values():
        record.setdefault("events_out", 0)
        record.setdefault("events_in", 0)
        record.setdefault("bytes_out", 0)
        record.setdefault("bytes_in", 0)
        record["total_events"] = record["events_out"] + record["events_in"]
        devices.append(record)

    devices.sort(key=lambda item: item["total_events"], reverse=True)
    page = devices[skip : skip + limit]
    return {
        "total": len(devices),
        "limit": limit,
        "skip": skip,
        "count": len(page),
        "items": page,
    }


async def protocol_breakdown() -> list[dict[str, Any]]:
    """Traffic grouped by protocol, for the `protocols` collection view."""
    pipeline = [
        {
            "$group": {
                "_id": {"protocol": "$protocol", "protocol_name": "$protocol_name"},
                "event_count": {"$sum": 1},
                "total_bytes": {"$sum": "$total_bytes"},
                "total_packets": {"$sum": "$total_packets"},
            }
        },
        {"$sort": {"event_count": DESCENDING}},
        {
            "$project": {
                "_id": 0,
                "protocol": "$_id.protocol",
                "protocol_name": "$_id.protocol_name",
                "event_count": 1,
                "total_bytes": 1,
                "total_packets": 1,
            }
        },
    ]
    cursor = await collections.events().aggregate(pipeline)
    return [document async for document in cursor]


async def top_ports(*, limit: int = 20) -> list[dict[str, Any]]:
    """Most-contacted destination ports."""
    pipeline = [
        {
            "$group": {
                "_id": {"port": "$dst_port", "service": "$dst_service"},
                "event_count": {"$sum": 1},
                "total_bytes": {"$sum": "$total_bytes"},
            }
        },
        {"$sort": {"event_count": DESCENDING}},
        {"$limit": limit},
        {
            "$project": {
                "_id": 0,
                "dst_port": "$_id.port",
                "dst_service": "$_id.service",
                "event_count": 1,
                "total_bytes": 1,
            }
        },
    ]
    cursor = await collections.events().aggregate(pipeline)
    return [document async for document in cursor]


async def recent_events_for_device(device: str, *, limit: int = 20) -> list[dict[str, Any]]:
    cursor = (
        collections.events()
        .find({"$or": [{"src_device": device}, {"dst_device": device}]}, PROJECTION)
        .sort("timestamp", DESCENDING)
        .limit(limit)
    )
    return [document async for document in cursor]

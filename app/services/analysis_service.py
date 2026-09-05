"""Analysis and investigation orchestration (spec 11, 12).

Ties the stored events, the graph engine and the ML layer into the two
investigator-facing products: an *analysis* (risk over a slice of traffic) and an
*investigation* (a device-centred case file).
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from app.database import collections
from app.ml import predict
from app.models.analysis import AnalysisRequest
from app.models.common import Classification, Direction, WeightStrategy
from app.models.investigation import InvestigationRequest
from app.services import event_service, graph_service
from app.services.event_service import EventFilter

logger = logging.getLogger(__name__)

PROJECTION = {"_id": 0}


def _filter_from_analysis(request: AnalysisRequest) -> EventFilter:
    return EventFilter(
        src_device=request.src_device,
        dst_device=request.dst_device,
        device=request.device,
        protocol=request.protocol,
        dst_port=request.dst_port,
        start_time=request.start_time,
        end_time=request.end_time,
        min_bytes=request.min_bytes,
    )


def summarize(scored: Sequence[Mapping[str, Any]], *, min_risk: float = 0.5) -> dict[str, Any]:
    """Roll scored events up into headline numbers for a report."""
    if not scored:
        return {
            "analyzed_events": 0,
            "flagged_events": 0,
            "mean_risk_score": 0.0,
            "max_risk_score": 0.0,
            "classification_counts": {},
            "top_risk_devices": [],
            "top_reasons": [],
        }

    risks = [float(item["risk_score"]) for item in scored]
    flagged = [item for item in scored if float(item["risk_score"]) >= min_risk]

    bands = Counter(
        item["classification"].value
        if isinstance(item["classification"], Classification)
        else str(item["classification"])
        for item in scored
    )

    per_device: dict[str, list[float]] = {}
    for item in scored:
        device = item.get("src_device")
        if device:
            per_device.setdefault(device, []).append(float(item["risk_score"]))

    top_devices = sorted(
        (
            {
                "device": device,
                "event_count": len(values),
                "mean_risk_score": round(sum(values) / len(values), 4),
                "max_risk_score": round(max(values), 4),
                "flagged_events": sum(1 for value in values if value >= min_risk),
            }
            for device, values in per_device.items()
        ),
        key=lambda item: (item["max_risk_score"], item["mean_risk_score"]),
        reverse=True,
    )[:10]

    reason_counts = Counter(reason for item in flagged for reason in item.get("reasons", []))

    return {
        "analyzed_events": len(scored),
        "flagged_events": len(flagged),
        "mean_risk_score": round(sum(risks) / len(risks), 4),
        "max_risk_score": round(max(risks), 4),
        "classification_counts": dict(bands),
        "top_risk_devices": top_devices,
        "top_reasons": [
            {"reason": reason, "count": count} for reason, count in reason_counts.most_common(10)
        ],
    }


async def run_analysis(request: AnalysisRequest) -> dict[str, Any]:
    """Score a filtered slice of events and optionally persist the report."""
    events = await event_service.fetch_events(
        _filter_from_analysis(request), limit=request.limit
    )
    scored = predict.score_events(events)

    ranked = sorted(scored, key=lambda item: float(item["risk_score"]), reverse=True)
    results = [
        item for item in ranked if float(item["risk_score"]) >= request.min_risk_score
    ][: request.top_n]

    model = predict.get_model()
    payload: dict[str, Any] = {
        "analysis_id": f"ana_{uuid.uuid4().hex[:12]}",
        "created_at": datetime.now(timezone.utc),
        "model_version": model.model_version,
        "request": request.model_dump(),
        "summary": summarize(scored, min_risk=model.thresholds["requires_review"]),
        "results": [_serialize_risk(item) for item in results],
    }

    if request.persist:
        await collections.analyses().insert_one(dict(payload))
        payload.pop("_id", None)

    return payload


def _serialize_risk(item: Mapping[str, Any]) -> dict[str, Any]:
    """Make a scored event JSON/BSON-safe (enums -> their values)."""
    record = dict(item)
    classification = record.get("classification")
    if isinstance(classification, Classification):
        record["classification"] = classification.value
    return record


async def get_analysis(analysis_id: str) -> dict[str, Any] | None:
    return await collections.analyses().find_one({"analysis_id": analysis_id}, PROJECTION)


async def list_analyses(*, limit: int = 20, skip: int = 0) -> dict[str, Any]:
    collection = collections.analyses()
    total = await collection.count_documents({})
    cursor = (
        collection.find({}, {"_id": 0, "results": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    items = [document async for document in cursor]
    return {"total": total, "limit": limit, "skip": skip, "count": len(items), "items": items}


async def score_device(device: str, *, limit: int = 1000) -> dict[str, Any]:
    """Rolled-up risk for a single device's outbound traffic."""
    events = await event_service.fetch_events(
        EventFilter(src_device=device), limit=limit
    )
    if not events:
        return {
            "device": device,
            "event_count": 0,
            "mean_risk_score": 0.0,
            "max_risk_score": 0.0,
            "flagged_events": 0,
            "classification": Classification.NORMAL.value,
            "top_reasons": [],
        }

    scored = predict.score_events(events)
    model = predict.get_model()
    risks = [float(item["risk_score"]) for item in scored]
    threshold = model.thresholds["requires_review"]
    flagged = [item for item in scored if float(item["risk_score"]) >= threshold]
    reasons = Counter(reason for item in flagged for reason in item["reasons"])

    # The device band follows its worst event: one clear exfiltration matters more
    # than a thousand ordinary sessions averaging it away.
    peak = max(risks)
    return {
        "device": device,
        "event_count": len(scored),
        "mean_risk_score": round(sum(risks) / len(risks), 4),
        "max_risk_score": round(peak, 4),
        "flagged_events": len(flagged),
        "classification": model.classify(peak).value,
        "top_reasons": [reason for reason, _ in reasons.most_common(5)],
    }


def _observations(
    device_summary: Mapping[str, Any],
    related: Sequence[Mapping[str, Any]],
    risk_summary: Mapping[str, Any],
) -> list[str]:
    """Plain-language findings for the case file."""
    notes: list[str] = []
    device = device_summary.get("device")
    total_events = device_summary.get("total_events", 0)

    if not total_events:
        return [f"No stored events involve {device}."]

    notes.append(
        f"{device} appears in {total_events} events "
        f"({device_summary.get('events_out', 0)} outbound, "
        f"{device_summary.get('events_in', 0)} inbound)."
    )
    notes.append(
        f"Communicated with {len(related)} distinct devices; "
        f"{device_summary.get('bytes_out', 0):,} bytes sent and "
        f"{device_summary.get('bytes_in', 0):,} bytes received."
    )

    bytes_out = device_summary.get("bytes_out", 0)
    bytes_in = device_summary.get("bytes_in", 0)
    if bytes_out > 5 * max(bytes_in, 1):
        notes.append(
            "Outbound volume greatly exceeds inbound, which is the shape of a data "
            "transfer away from this device."
        )

    flagged = risk_summary.get("flagged_events", 0)
    if flagged:
        notes.append(
            f"{flagged} of {risk_summary.get('analyzed_events', 0)} scored events reached the "
            "review threshold."
        )
        top = risk_summary.get("top_reasons", [])
        if top:
            notes.append("Most common factors: " + ", ".join(item["reason"] for item in top[:3]) + ".")
    else:
        notes.append("No events for this device reached the review threshold.")

    if related:
        busiest = related[0]
        notes.append(
            f"Most frequent peer is {busiest['device']} "
            f"({busiest['event_count']} events, {busiest['total_bytes']:,} bytes)."
        )

    notes.append(
        "Risk scores are statistical indicators of unusual traffic, not confirmation "
        "of malicious activity; each finding needs analyst review."
    )
    return notes


async def run_investigation(request: InvestigationRequest) -> dict[str, Any]:
    """Build a device-centred case file combining storage, graph and ML output."""
    device = request.device

    summary = await event_service.device_summary(device)
    related = await event_service.related_devices(device, limit=50)
    recent = await event_service.recent_events_for_device(device, limit=10)

    # --- Graph neighbourhood (BFS, spec 10.1) ---
    levels: dict[int, list[str]] = {}
    edges: list[dict[str, Any]] = []
    graph_filter = {"start_time": request.start_time, "end_time": request.end_time}
    try:
        hood = await graph_service.neighborhood(
            device, depth=request.depth, direction=Direction.BOTH, filter_dict=graph_filter
        )
        edges = hood["edges"]
        for node in hood["nodes"]:
            levels.setdefault(node["depth"], []).append(node["device"])
    except graph_service.DeviceNotInGraphError:
        logger.info("device %s absent from graph; investigation continues without it", device)

    # --- Risk scoring (spec 11) ---
    events = await event_service.fetch_events(
        EventFilter(
            device=device, start_time=request.start_time, end_time=request.end_time
        ),
        limit=request.max_events,
    )
    scored = predict.score_events(events)
    model = predict.get_model()
    threshold = model.thresholds["requires_review"]
    risk_summary = summarize(scored, min_risk=threshold)
    ranked = sorted(scored, key=lambda item: float(item["risk_score"]), reverse=True)
    risky = [_serialize_risk(item) for item in ranked[: request.top_n]]

    overall = max((float(item["risk_score"]) for item in scored), default=0.0)
    now = datetime.now(timezone.utc)

    document: dict[str, Any] = {
        "investigation_id": f"inv_{uuid.uuid4().hex[:12]}",
        "device": device,
        "title": request.title or f"Investigation of {device}",
        "notes": request.notes,
        "analyst": request.analyst,
        "status": "open",
        "created_at": now,
        "updated_at": now,
        "overall_risk_score": round(overall, 4),
        "classification": model.classify(overall).value,
        "request": request.model_dump(mode="json"),
        "findings": {
            "device_summary": summary,
            "related_devices": list(related),
            "neighborhood_levels": {str(k): v for k, v in sorted(levels.items())},
            "neighborhood_edges": edges[:200],
            "risk_summary": risk_summary,
            "risky_events": risky,
            "notable_events": recent,
            "observations": _observations(summary, list(related), risk_summary),
        },
    }

    if request.persist:
        await collections.investigations().insert_one(dict(document))
        document.pop("_id", None)

    return document


async def get_investigation(investigation_id: str) -> dict[str, Any] | None:
    return await collections.investigations().find_one(
        {"investigation_id": investigation_id}, PROJECTION
    )


async def list_investigations(
    *, device: str | None = None, status: str | None = None, limit: int = 20, skip: int = 0
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if device:
        query["device"] = device
    if status:
        query["status"] = status

    collection = collections.investigations()
    total = await collection.count_documents(query)
    cursor = (
        collection.find(query, {"_id": 0, "findings": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    items = [document async for document in cursor]
    return {"total": total, "limit": limit, "skip": skip, "count": len(items), "items": items}


async def update_investigation(
    investigation_id: str, changes: Mapping[str, Any]
) -> dict[str, Any] | None:
    updates = {key: value for key, value in changes.items() if value is not None}
    if not updates:
        return await get_investigation(investigation_id)
    updates["updated_at"] = datetime.now(timezone.utc)
    result = await collections.investigations().update_one(
        {"investigation_id": investigation_id}, {"$set": updates}
    )
    if result.matched_count == 0:
        return None
    return await get_investigation(investigation_id)


async def delete_investigation(investigation_id: str) -> bool:
    result = await collections.investigations().delete_one(
        {"investigation_id": investigation_id}
    )
    return result.deleted_count > 0

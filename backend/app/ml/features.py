"""Feature engineering for the anomaly-detection layer (spec 11).

Two families of features are combined:

* **Per-event** -- volume, duration, ports and the derived ratios already stored
  on each document.
* **Per-device context** -- how often the source device talks, to how many
  distinct destinations, and how usual *this* destination is for it. A 900 MB
  transfer is unremarkable for a backup server and glaring for a workstation, so
  the context is what turns a raw number into a signal.

Device context is computed from the whole training corpus and **persisted with
the model**. Recomputing it from whatever slice is being scored would make an
event's features depend on the query that retrieved it -- the same event would
score differently in a one-device query than in a full sweep. At prediction time
the stored profiles are reused, and only unseen devices fall back to batch
statistics.

Heavy-tailed quantities (bytes, packets, ratios) are ``log1p``-compressed: raw
byte counts span six orders of magnitude in this dataset, which would otherwise
let a single feature dominate every distance computation.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from app.collector.normalizer import PORT_SERVICES

__all__ = [
    "FEATURE_COLUMNS",
    "compute_device_profiles",
    "build_feature_frame",
    "profiles_to_json",
    "profiles_from_json",
]

# Ordered feature vector. The order is persisted with the model and re-asserted
# at prediction time, so a change here invalidates an existing model.
FEATURE_COLUMNS: tuple[str, ...] = (
    "duration_log",
    "is_tcp",
    "is_udp",
    "src_port",
    "dst_port",
    "dst_port_is_wellknown",
    "dst_port_is_known_service",
    "src_packets_log",
    "dst_packets_log",
    "src_bytes_log",
    "dst_bytes_log",
    "total_packets_log",
    "total_bytes_log",
    "packet_ratio_log",
    "byte_ratio_log",
    "bytes_per_second_log",
    "src_bytes_per_packet_log",
    "dst_bytes_per_packet_log",
    "no_response_traffic",
    "device_event_count_log",
    "device_unique_destinations_log",
    "device_unique_src_ports_log",
    "device_unique_dst_ports_log",
    "device_mean_bytes_log",
    "pair_event_count_log",
    "destination_share",
    "bytes_vs_device_mean",
)

# Human-readable labels used when explaining a score.
FEATURE_LABELS: dict[str, str] = {
    "src_bytes_log": "outbound data volume",
    "total_bytes_log": "total data transferred",
    "byte_ratio_log": "outbound/inbound byte imbalance",
    "packet_ratio_log": "outbound/inbound packet imbalance",
    "bytes_per_second_log": "sustained transfer rate",
    "duration_log": "connection duration",
    "device_event_count_log": "communication frequency",
    "device_unique_destinations_log": "number of distinct destinations contacted",
    "destination_share": "how usual this destination is for the source device",
    "bytes_vs_device_mean": "volume relative to this device's norm",
}


def _log(value: float) -> float:
    """``log1p`` guarded against negatives and non-finite input."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number) or number < 0.0:
        return 0.0
    return math.log1p(number)


def compute_device_profiles(events: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-source-device activity profile used as ML context.

    Returns, per source device: event count, distinct destinations, distinct
    source/destination ports, mean total bytes, and the per-destination event
    counts that drive the "uncommon destination" signal.
    """
    counts: dict[str, int] = defaultdict(int)
    destinations: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    src_ports: dict[str, set[int]] = defaultdict(set)
    dst_ports: dict[str, set[int]] = defaultdict(set)
    byte_totals: dict[str, int] = defaultdict(int)

    for event in events:
        device = event.get("src_device")
        if not device:
            continue
        counts[device] += 1
        destination = event.get("dst_device")
        if destination:
            destinations[device][destination] += 1
        if event.get("src_port") is not None:
            src_ports[device].add(int(event["src_port"]))
        if event.get("dst_port") is not None:
            dst_ports[device].add(int(event["dst_port"]))
        byte_totals[device] += int(event.get("total_bytes") or 0)

    return {
        device: {
            "event_count": count,
            "unique_destinations": len(destinations[device]),
            "unique_src_ports": len(src_ports[device]),
            "unique_dst_ports": len(dst_ports[device]),
            "mean_bytes": byte_totals[device] / count if count else 0.0,
            "destination_counts": dict(destinations[device]),
        }
        for device, count in counts.items()
    }


_EMPTY_PROFILE: dict[str, Any] = {
    "event_count": 0,
    "unique_destinations": 0,
    "unique_src_ports": 0,
    "unique_dst_ports": 0,
    "mean_bytes": 0.0,
    "destination_counts": {},
}


def build_feature_frame(
    events: Sequence[Mapping[str, Any]],
    *,
    profiles: Mapping[str, Mapping[str, Any]] | None = None,
) -> pd.DataFrame:
    """Build the model matrix for a batch of events.

    Indexed by ``event_id`` with exactly ``FEATURE_COLUMNS`` as columns. When
    ``profiles`` is omitted, device context is derived from ``events`` itself
    (the training path).
    """
    if not events:
        return pd.DataFrame(columns=list(FEATURE_COLUMNS))

    if profiles is None:
        profiles = compute_device_profiles(events)
    else:
        # Devices absent from the trained profiles (new hosts seen by the live
        # collector) fall back to statistics from the batch in hand.
        batch_profiles = compute_device_profiles(events)
        merged = dict(profiles)
        for device, profile in batch_profiles.items():
            if device not in merged:
                merged[device] = profile
        profiles = merged

    rows: list[dict[str, float]] = []
    index: list[str] = []

    for event in events:
        device = event.get("src_device") or ""
        profile = profiles.get(device, _EMPTY_PROFILE)
        device_events = int(profile.get("event_count", 0) or 0)
        destination_counts = profile.get("destination_counts", {}) or {}
        pair_count = int(destination_counts.get(event.get("dst_device"), 0) or 0)

        total_bytes = float(event.get("total_bytes") or 0)
        mean_bytes = float(profile.get("mean_bytes", 0.0) or 0.0)
        protocol = int(event.get("protocol") or 0)
        dst_port = int(event.get("dst_port") or 0)

        rows.append(
            {
                "duration_log": _log(event.get("duration")),
                "is_tcp": 1.0 if protocol == 6 else 0.0,
                "is_udp": 1.0 if protocol == 17 else 0.0,
                # Ports are identifiers, not magnitudes; scaled to [0, 1] so they
                # contribute without dominating.
                "src_port": float(event.get("src_port") or 0) / 65535.0,
                "dst_port": dst_port / 65535.0,
                "dst_port_is_wellknown": 1.0 if 0 < dst_port < 1024 else 0.0,
                "dst_port_is_known_service": 1.0 if dst_port in PORT_SERVICES else 0.0,
                "src_packets_log": _log(event.get("src_packets")),
                "dst_packets_log": _log(event.get("dst_packets")),
                "src_bytes_log": _log(event.get("src_bytes")),
                "dst_bytes_log": _log(event.get("dst_bytes")),
                "total_packets_log": _log(event.get("total_packets")),
                "total_bytes_log": _log(total_bytes),
                "packet_ratio_log": _log(event.get("packet_ratio")),
                "byte_ratio_log": _log(event.get("byte_ratio")),
                "bytes_per_second_log": _log(event.get("bytes_per_second")),
                "src_bytes_per_packet_log": _log(event.get("src_bytes_per_packet")),
                "dst_bytes_per_packet_log": _log(event.get("dst_bytes_per_packet")),
                "no_response_traffic": 1.0 if not event.get("dst_packets") else 0.0,
                "device_event_count_log": _log(device_events),
                "device_unique_destinations_log": _log(profile.get("unique_destinations", 0)),
                "device_unique_src_ports_log": _log(profile.get("unique_src_ports", 0)),
                "device_unique_dst_ports_log": _log(profile.get("unique_dst_ports", 0)),
                "device_mean_bytes_log": _log(mean_bytes),
                "pair_event_count_log": _log(pair_count),
                # Share of this device's traffic aimed at this destination; a low
                # value means an unusual destination for that device.
                "destination_share": (pair_count / device_events) if device_events else 0.0,
                # How far this event's volume sits above the device's own norm.
                "bytes_vs_device_mean": _log(total_bytes / mean_bytes) if mean_bytes > 0 else 0.0,
            }
        )
        index.append(str(event.get("event_id") or f"row_{len(index)}"))

    frame = pd.DataFrame(rows, index=index, columns=list(FEATURE_COLUMNS))
    return frame.fillna(0.0)


def profiles_to_json(profiles: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Make device profiles JSON-serializable for the model sidecar."""
    return {
        device: {
            "event_count": int(profile.get("event_count", 0)),
            "unique_destinations": int(profile.get("unique_destinations", 0)),
            "unique_src_ports": int(profile.get("unique_src_ports", 0)),
            "unique_dst_ports": int(profile.get("unique_dst_ports", 0)),
            "mean_bytes": float(profile.get("mean_bytes", 0.0)),
            "destination_counts": {
                str(k): int(v) for k, v in (profile.get("destination_counts") or {}).items()
            },
        }
        for device, profile in profiles.items()
    }


def profiles_from_json(raw: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Inverse of :func:`profiles_to_json`."""
    return {str(device): dict(profile) for device, profile in (raw or {}).items()}

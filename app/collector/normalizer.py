"""Normalization of raw network activity records into ChronoTrace's canonical schema.

This module is the single place where raw input becomes a stored event, so the CSV
loader, the ``POST /events`` endpoint and the live collector all produce identical
documents.

Raw input may use either the dataset's column names (``Time``, ``SrcDevice``, ...)
or the canonical names (``timestamp``, ``src_device``, ...); both are accepted.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

__all__ = [
    "NormalizationError",
    "PROTOCOL_NAMES",
    "PORT_SERVICES",
    "CANONICAL_FIELDS",
    "parse_port",
    "protocol_name",
    "port_service",
    "make_event_id",
    "normalize_event",
    "normalize_many",
]


class NormalizationError(ValueError):
    """Raised when a raw record cannot be turned into a valid event."""


# IANA protocol numbers seen in network telemetry. The dataset uses 6 and 17.
PROTOCOL_NAMES: dict[int, str] = {
    1: "ICMP",
    2: "IGMP",
    6: "TCP",
    17: "UDP",
    41: "IPv6",
    47: "GRE",
    50: "ESP",
    58: "ICMPv6",
    89: "OSPF",
    132: "SCTP",
}

# Well-known destination ports, used to label events for investigators.
PORT_SERVICES: dict[int, str] = {
    20: "FTP-DATA", 21: "FTP", 22: "SSH", 23: "TELNET", 25: "SMTP",
    53: "DNS", 67: "DHCP-SERVER", 68: "DHCP-CLIENT", 69: "TFTP",
    80: "HTTP", 88: "KERBEROS", 110: "POP3", 111: "RPCBIND",
    119: "NNTP", 123: "NTP", 135: "MSRPC", 137: "NETBIOS-NS",
    138: "NETBIOS-DGM", 139: "NETBIOS-SSN", 143: "IMAP", 161: "SNMP",
    162: "SNMP-TRAP", 389: "LDAP", 443: "HTTPS", 445: "SMB",
    465: "SMTPS", 500: "ISAKMP", 514: "SYSLOG", 587: "SMTP-SUBMISSION",
    636: "LDAPS", 993: "IMAPS", 995: "POP3S", 1433: "MSSQL",
    1521: "ORACLE", 1900: "SSDP", 3306: "MYSQL", 3389: "RDP",
    5060: "SIP", 5432: "POSTGRES", 5900: "VNC", 6379: "REDIS",
    8080: "HTTP-ALT", 8443: "HTTPS-ALT", 27017: "MONGODB",
}

# Canonical field order for the stored document.
CANONICAL_FIELDS = (
    "event_id", "timestamp", "event_time", "duration",
    "src_device", "dst_device", "protocol", "protocol_name",
    "src_port", "dst_port", "dst_service",
    "src_packets", "dst_packets", "src_bytes", "dst_bytes",
    "total_packets", "total_bytes", "packet_ratio", "byte_ratio",
    "bytes_per_second", "src_bytes_per_packet", "dst_bytes_per_packet",
    "source",
)

# Raw column name -> canonical name. Lookup is case-insensitive.
_FIELD_ALIASES: dict[str, str] = {
    "time": "timestamp", "timestamp": "timestamp", "start_time": "timestamp",
    "duration": "duration",
    "srcdevice": "src_device", "src_device": "src_device", "source_device": "src_device",
    "dstdevice": "dst_device", "dst_device": "dst_device", "destination_device": "dst_device",
    "protocol": "protocol",
    "srcport": "src_port", "src_port": "src_port", "source_port": "src_port",
    "dstport": "dst_port", "dst_port": "dst_port", "destination_port": "dst_port",
    "srcpackets": "src_packets", "src_packets": "src_packets", "source_packets": "src_packets",
    "dstpackets": "dst_packets", "dst_packets": "dst_packets", "destination_packets": "dst_packets",
    "srcbytes": "src_bytes", "src_bytes": "src_bytes", "source_bytes": "src_bytes",
    "dstbytes": "dst_bytes", "dst_bytes": "dst_bytes", "destination_bytes": "dst_bytes",
    "event_id": "event_id", "source": "source",
}

# The dataset stores source ports as the label "Port62917" rather than an integer.
_PORT_LABEL = re.compile(r"^\s*port[\s_:-]*(\d+)\s*$", re.IGNORECASE)

MAX_PORT = 65535


def parse_port(value: Any, *, field: str = "port") -> int:
    """Coerce a port to an integer, accepting ``Port62917``-style labels.

    The dataset's ``SrcPort`` column is a string label while ``DstPort`` is an
    integer; both funnel through here so stored ports are always comparable.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        raise NormalizationError(f"{field} is missing")
    if isinstance(value, bool):
        raise NormalizationError(f"{field} must be a port number, got a boolean")
    if isinstance(value, (int, float)):
        port = int(value)
    else:
        text = str(value).strip()
        match = _PORT_LABEL.match(text)
        if match:
            port = int(match.group(1))
        elif text.lstrip("+-").isdigit():
            port = int(text)
        else:
            raise NormalizationError(f"{field} is not a recognisable port: {value!r}")
    if not 0 <= port <= MAX_PORT:
        raise NormalizationError(f"{field} out of range 0-{MAX_PORT}: {port}")
    return port


def protocol_name(protocol: int) -> str:
    """Human-readable protocol name, falling back to ``PROTO-<n>``."""
    return PROTOCOL_NAMES.get(protocol, f"PROTO-{protocol}")


def port_service(port: int) -> str | None:
    """Well-known service label for a destination port, or ``None`` if unknown."""
    return PORT_SERVICES.get(port)


def make_event_id(doc: Mapping[str, Any]) -> str:
    """Deterministic content-addressed id for an event.

    A content hash (rather than a running counter) makes ingestion idempotent:
    re-loading the CSV, or a collector re-sending a buffered event, upserts the
    same ``event_id`` instead of duplicating the record.
    """
    parts = "|".join(
        str(doc.get(field, ""))
        for field in (
            "timestamp", "duration", "src_device", "dst_device", "protocol",
            "src_port", "dst_port", "src_packets", "dst_packets",
            "src_bytes", "dst_bytes",
        )
    )
    return "evt_" + hashlib.sha1(parts.encode("utf-8")).hexdigest()[:16]


def _canonical_key(key: str) -> str | None:
    return _FIELD_ALIASES.get(str(key).strip().lower().replace(" ", "_"))


def _require_value(raw: Mapping[str, Any], field: str) -> Any:
    if field not in raw:
        raise NormalizationError(f"missing required field: {field}")
    value = raw[field]
    if value is None or (isinstance(value, float) and math.isnan(value)):
        raise NormalizationError(f"{field} is missing")
    return value


def _as_int(raw: Mapping[str, Any], field: str, *, minimum: int | None = 0) -> int:
    value = _require_value(raw, field)
    try:
        number = int(float(value))
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"{field} is not an integer: {value!r}") from exc
    if minimum is not None and number < minimum:
        raise NormalizationError(f"{field} must be >= {minimum}, got {number}")
    return number


def _as_float(raw: Mapping[str, Any], field: str, *, minimum: float | None = 0.0) -> float:
    value = _require_value(raw, field)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"{field} is not a number: {value!r}") from exc
    if not math.isfinite(number):
        raise NormalizationError(f"{field} is not finite: {value!r}")
    if minimum is not None and number < minimum:
        raise NormalizationError(f"{field} must be >= {minimum}, got {number}")
    return number


def _as_device(raw: Mapping[str, Any], field: str) -> str:
    if field not in raw:
        raise NormalizationError(f"missing required field: {field}")
    value = raw[field]
    if value is None:
        raise NormalizationError(f"{field} is missing")
    device = str(value).strip()
    if not device:
        raise NormalizationError(f"{field} is empty")
    return device


def _ratio(numerator: float, denominator: float) -> float:
    """Directional ratio that stays defined when the denominator is zero.

    ``DstPackets`` and ``DstBytes`` are legitimately 0 in the dataset (no reply
    traffic), so the denominator is floored at 1 rather than yielding ``None``.
    That keeps the field numeric for both Mongo range queries and ML features.
    """
    return round(numerator / max(denominator, 1.0), 6)


def normalize_event(raw: Mapping[str, Any], *, source: str = "dataset") -> dict[str, Any]:
    """Turn one raw record into a canonical ChronoTrace event document.

    Raises ``NormalizationError`` if a required field is missing or invalid.
    """
    if not isinstance(raw, Mapping):
        raise NormalizationError(f"record must be a mapping, got {type(raw).__name__}")

    # Fold aliases down to canonical names, ignoring unknown columns.
    mapped: dict[str, Any] = {}
    for key, value in raw.items():
        canonical = _canonical_key(key)
        if canonical is not None and value is not None:
            mapped.setdefault(canonical, value)

    timestamp = _as_int(mapped, "timestamp", minimum=0)
    doc: dict[str, Any] = {
        "timestamp": timestamp,
        # The raw epoch is retained above; this derived field powers date-range
        # queries and human-readable output (spec 4.1).
        "event_time": datetime.fromtimestamp(timestamp, tz=timezone.utc),
        "duration": _as_float(mapped, "duration", minimum=0.0),
        "src_device": _as_device(mapped, "src_device"),
        "dst_device": _as_device(mapped, "dst_device"),
        "protocol": _as_int(mapped, "protocol", minimum=0),
        "src_port": parse_port(mapped.get("src_port"), field="src_port"),
        "dst_port": parse_port(mapped.get("dst_port"), field="dst_port"),
        "src_packets": _as_int(mapped, "src_packets"),
        "dst_packets": _as_int(mapped, "dst_packets"),
        "src_bytes": _as_int(mapped, "src_bytes"),
        "dst_bytes": _as_int(mapped, "dst_bytes"),
    }

    doc["protocol_name"] = protocol_name(doc["protocol"])
    doc["dst_service"] = port_service(doc["dst_port"])

    # --- Derived features (spec 5) ---
    doc["total_packets"] = doc["src_packets"] + doc["dst_packets"]
    doc["total_bytes"] = doc["src_bytes"] + doc["dst_bytes"]
    doc["packet_ratio"] = _ratio(doc["src_packets"], doc["dst_packets"])
    doc["byte_ratio"] = _ratio(doc["src_bytes"], doc["dst_bytes"])
    doc["bytes_per_second"] = _ratio(doc["total_bytes"], doc["duration"])
    doc["src_bytes_per_packet"] = _ratio(doc["src_bytes"], doc["src_packets"])
    doc["dst_bytes_per_packet"] = _ratio(doc["dst_bytes"], doc["dst_packets"])

    doc["source"] = str(mapped.get("source") or source)
    doc["event_id"] = str(mapped.get("event_id") or make_event_id(doc))

    return {field: doc[field] for field in CANONICAL_FIELDS if field in doc}


def normalize_many(
    records: Iterable[Mapping[str, Any]],
    *,
    source: str = "dataset",
    strict: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize a batch, returning ``(events, rejected)``.

    With ``strict=True`` the first bad record raises instead of being collected.
    """
    events: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        try:
            events.append(normalize_event(record, source=source))
        except NormalizationError as exc:
            if strict:
                raise
            rejected.append({"index": index, "error": str(exc), "record": dict(record)})
    return events, rejected

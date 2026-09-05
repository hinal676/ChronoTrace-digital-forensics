"""Live network activity collector (spec 14, phase 8).

Captures **authorized connection metadata from the host it runs on** -- addresses,
ports, protocol, and how long each connection persisted -- normalizes it through
the shared normalizer, and posts it to the ChronoTrace API.

Scope and honesty about what this can measure:

* It samples the host's own connection table via ``psutil``. That is metadata
  only: no packet contents are captured, and no other host is probed.
* ``psutil`` exposes no per-connection byte or packet counters, so those fields
  are attributed from per-NIC deltas across the sample interval, divided among the
  connections observed in that window. They are **estimates**, and every event
  produced this way carries ``source="collector"`` so estimated traffic is never
  confused with the exact figures in a dataset import.
* Duration is measured properly: a connection first seen at t0 and still present
  at t1 has lasted t1 - t0.

Run only on systems you are authorized to monitor::

    python -m app.collector.collector --once
    python -m app.collector.collector --interval 10 --api http://127.0.0.1:8000
    python -m app.collector.collector --replay data/chronotrace_network_5000.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from app.collector.normalizer import NormalizationError, normalize_event
from app.config import settings

logger = logging.getLogger(__name__)

# IANA numbers for the socket types psutil reports.
_PROTO_TCP = 6
_PROTO_UDP = 17

# Only established connections describe an actual conversation.
_ACTIVE_STATES = {"ESTABLISHED", "SYN_SENT", "SYN_RECV", "CLOSE_WAIT", "FIN_WAIT1", "FIN_WAIT2"}


class CollectorUnavailableError(RuntimeError):
    """Raised when the host cannot be sampled (psutil missing or access denied)."""


@dataclass
class _Tracked:
    """A connection seen across sampling rounds."""

    first_seen: float
    last_seen: float
    src_device: str
    dst_device: str
    src_port: int
    dst_port: int
    protocol: int
    samples: int = 1
    src_bytes: int = 0
    dst_bytes: int = 0
    src_packets: int = 0
    dst_packets: int = 0


@dataclass
class HostCollector:
    """Samples the local connection table and emits normalized events."""

    host_name: str = field(default_factory=socket.gethostname)
    include_loopback: bool = False
    _tracked: dict[tuple, _Tracked] = field(default_factory=dict)
    _last_counters: tuple[float, int, int, int, int] | None = None

    def _psutil(self):
        try:
            import psutil
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise CollectorUnavailableError(
                "psutil is required for live collection: pip install psutil"
            ) from exc
        return psutil

    def _nic_deltas(self, psutil_module) -> tuple[int, int, int, int]:
        """Bytes/packets sent and received since the previous sample."""
        counters = psutil_module.net_io_counters()
        now = time.time()
        current = (now, counters.bytes_sent, counters.bytes_recv,
                   counters.packets_sent, counters.packets_recv)
        if self._last_counters is None:
            self._last_counters = current
            return 0, 0, 0, 0
        _, prev_bs, prev_br, prev_ps, prev_pr = self._last_counters
        self._last_counters = current
        # Counters reset when an interface restarts; clamp rather than go negative.
        return (
            max(counters.bytes_sent - prev_bs, 0),
            max(counters.bytes_recv - prev_br, 0),
            max(counters.packets_sent - prev_ps, 0),
            max(counters.packets_recv - prev_pr, 0),
        )

    def sample(self) -> list[dict[str, Any]]:
        """Take one sample; returns events for connections that have closed.

        An event is emitted when a tracked connection disappears, because only
        then is its duration final.
        """
        psutil_module = self._psutil()
        try:
            connections = psutil_module.net_connections(kind="inet")
        except (PermissionError, psutil_module.AccessDenied) as exc:
            raise CollectorUnavailableError(
                "insufficient privileges to read the connection table; "
                "run with elevated permissions on a host you are authorized to monitor"
            ) from exc

        bytes_sent, bytes_recv, packets_sent, packets_recv = self._nic_deltas(psutil_module)
        now = time.time()
        seen: set[tuple] = set()

        active: list[tuple] = []
        for conn in connections:
            if not conn.raddr or not conn.laddr:
                continue
            if conn.status and conn.status not in _ACTIVE_STATES:
                continue
            remote_ip = conn.raddr.ip
            if not self.include_loopback and remote_ip in ("127.0.0.1", "::1"):
                continue

            protocol = _PROTO_TCP if conn.type == socket.SOCK_STREAM else _PROTO_UDP
            key = (conn.laddr.port, remote_ip, conn.raddr.port, protocol)
            active.append(key)
            seen.add(key)

            if key in self._tracked:
                tracked = self._tracked[key]
                tracked.last_seen = now
                tracked.samples += 1
            else:
                self._tracked[key] = _Tracked(
                    first_seen=now, last_seen=now,
                    src_device=self.host_name, dst_device=remote_ip,
                    src_port=conn.laddr.port, dst_port=conn.raddr.port,
                    protocol=protocol,
                )

        # Attribute this interval's NIC traffic evenly across active connections.
        # Even attribution is an approximation, stated plainly rather than hidden.
        if active:
            share = len(active)
            for key in active:
                tracked = self._tracked[key]
                tracked.src_bytes += bytes_sent // share
                tracked.dst_bytes += bytes_recv // share
                tracked.src_packets += packets_sent // share
                tracked.dst_packets += packets_recv // share

        closed = [key for key in self._tracked if key not in seen]
        events: list[dict[str, Any]] = []
        for key in closed:
            tracked = self._tracked.pop(key)
            try:
                events.append(self._to_event(tracked))
            except NormalizationError as exc:
                logger.warning("skipping malformed collected connection: %s", exc)
        return events

    def flush(self) -> list[dict[str, Any]]:
        """Emit every still-open connection; call on shutdown."""
        events = []
        for tracked in list(self._tracked.values()):
            try:
                events.append(self._to_event(tracked))
            except NormalizationError as exc:
                logger.warning("skipping malformed connection on flush: %s", exc)
        self._tracked.clear()
        return events

    @staticmethod
    def _to_event(tracked: _Tracked) -> dict[str, Any]:
        return normalize_event(
            {
                "Time": int(tracked.first_seen),
                "Duration": max(tracked.last_seen - tracked.first_seen, 0.0),
                "SrcDevice": tracked.src_device,
                "DstDevice": tracked.dst_device,
                "Protocol": tracked.protocol,
                "SrcPort": tracked.src_port,
                "DstPort": tracked.dst_port,
                "SrcPackets": tracked.src_packets,
                "DstPackets": tracked.dst_packets,
                "SrcBytes": tracked.src_bytes,
                "DstBytes": tracked.dst_bytes,
            },
            source="collector",
        )


def _json_safe(event: Mapping[str, Any]) -> dict[str, Any]:
    """Make a normalized event JSON-encodable.

    ``event_time`` is a ``datetime``, which no JSON encoder accepts. The API
    re-derives it from ``timestamp`` on receipt, so converting to ISO-8601 here
    keeps the payload readable without the server depending on it.
    """
    return {
        key: (value.isoformat() if isinstance(value, datetime) else value)
        for key, value in event.items()
    }


async def post_events(events: Sequence[dict[str, Any]], *, api_url: str) -> dict[str, Any]:
    """Send normalized events to the ChronoTrace API."""
    if not events:
        return {"received": 0, "inserted": 0}
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover
        raise CollectorUnavailableError("httpx is required to post events: pip install httpx") from exc

    payload = {"events": [_json_safe(event) for event in events], "source": "collector"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{api_url.rstrip('/')}/events/bulk", json=payload)
        response.raise_for_status()
        return response.json()


def _events_from_csv(path: Path) -> Iterable[dict[str, Any]]:
    """Replay a CSV through the collector path -- an end-to-end pipeline test."""
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                yield normalize_event(row, source="replay")
            except NormalizationError as exc:
                logger.warning("skipping row: %s", exc)


async def replay(path: Path, *, api_url: str, batch_size: int = 500, limit: int = 0) -> int:
    """Push a CSV to the API in batches, exercising the full ingestion path."""
    batch: list[dict[str, Any]] = []
    sent = 0
    for event in _events_from_csv(path):
        batch.append(event)
        if len(batch) >= batch_size:
            result = await post_events(batch, api_url=api_url)
            sent += result.get("received", len(batch))
            print(f"  sent {sent} events (inserted {result.get('inserted', 0)})")
            batch.clear()
            if limit and sent >= limit:
                return sent
    if batch:
        result = await post_events(batch, api_url=api_url)
        sent += result.get("received", len(batch))
        print(f"  sent {sent} events (inserted {result.get('inserted', 0)})")
    return sent


async def run(
    *, api_url: str, interval: float, once: bool = False, include_loopback: bool = False
) -> int:
    """Sample the host on a loop, posting completed connections as they close."""
    collector = HostCollector(include_loopback=include_loopback)
    print(f"Collecting on {collector.host_name}; posting to {api_url}. Ctrl+C to stop.")
    print("Only run this on hosts you are authorized to monitor.")

    total = 0
    try:
        while True:
            events = collector.sample()
            if events:
                result = await post_events(events, api_url=api_url)
                total += len(events)
                print(f"  posted {len(events)} events (total {total}, "
                      f"inserted {result.get('inserted', 0)})")
            if once:
                break
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopping; flushing open connections ...")
    finally:
        remaining = collector.flush()
        if remaining:
            await post_events(remaining, api_url=api_url)
            total += len(remaining)
            print(f"  flushed {len(remaining)} open connections")
    print(f"Collected {total} events.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect authorized network activity metadata and send it to ChronoTrace."
    )
    parser.add_argument("--api", default=settings.collector_api_url, help="ChronoTrace API base URL.")
    parser.add_argument("--interval", type=float, default=settings.collector_interval)
    parser.add_argument("--once", action="store_true", help="Take a single sample and exit.")
    parser.add_argument("--include-loopback", action="store_true")
    parser.add_argument(
        "--replay", type=Path, help="Replay a CSV through the API instead of sampling the host."
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--limit", type=int, default=0, help="Stop after N replayed events.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        if args.replay:
            if not args.replay.exists():
                parser.error(f"CSV not found: {args.replay}")
            sent = asyncio.run(
                replay(args.replay, api_url=args.api, batch_size=args.batch_size, limit=args.limit)
            )
            print(f"Replayed {sent} events to {args.api}")
            return 0
        return asyncio.run(
            run(
                api_url=args.api,
                interval=args.interval,
                once=args.once,
                include_loopback=args.include_loopback,
            )
        )
    except CollectorUnavailableError as exc:
        print(f"Collector unavailable: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

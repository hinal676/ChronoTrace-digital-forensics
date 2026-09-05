"""Load the network activity CSV into MongoDB (spec phases 2-3).

Normalizes every row through the shared normalizer, then upserts by ``event_id``
so re-running the loader is idempotent rather than duplicating the dataset.

Usage::

    python scripts/load_dataset.py                       # load the default CSV
    python scripts/load_dataset.py --dry-run             # validate without a database
    python scripts/load_dataset.py --drop                # replace existing events
    python scripts/load_dataset.py --csv other.csv --batch-size 1000
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

# Allow running as a plain script from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.collector.normalizer import normalize_many  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import collections, connection  # noqa: E402


def safe_uri(uri: str) -> str:
    """Hide credentials before printing a connection string.

    Atlas URIs embed a password; logging one verbatim leaks it into terminal
    history, CI output and screenshots.
    """
    if "@" not in uri:
        return uri
    scheme, _, rest = uri.partition("://")
    _, _, host = rest.partition("@")
    return f"{scheme}://<credentials>@{host}"


def read_csv(path: Path) -> list[dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def describe(events: Sequence[dict[str, Any]]) -> None:
    """Print a short profile of what was normalized (spec phase 1)."""
    if not events:
        print("no events")
        return

    devices = {event["src_device"] for event in events} | {
        event["dst_device"] for event in events
    }
    sources = {event["src_device"] for event in events}
    protocols = Counter(event["protocol_name"] for event in events)
    ports = Counter(event["dst_port"] for event in events)
    timestamps = [event["timestamp"] for event in events]
    total_bytes = sum(event["total_bytes"] for event in events)

    print(f"  events            : {len(events)}")
    print(f"  unique devices    : {len(devices)} ({len(sources)} act as a source)")
    print(f"  destination-only  : {len(devices - sources)} "
          f"{sorted(devices - sources)[:8]}")
    print(f"  protocols         : {dict(protocols)}")
    print(f"  time range        : {min(timestamps)} .. {max(timestamps)}")
    print(f"  total bytes       : {total_bytes:,}")
    print(f"  top dst ports     : {[port for port, _ in ports.most_common(8)]}")


async def load(
    path: Path, *, batch_size: int = 1000, drop: bool = False, dry_run: bool = False
) -> int:
    rows = read_csv(path)
    print(f"Read {len(rows)} rows from {path}")

    events, rejected = normalize_many(rows, source="dataset")
    print(f"Normalized {len(events)} events, rejected {len(rejected)}")
    for problem in rejected[:10]:
        print(f"  row {problem['index']}: {problem['error']}")

    unique_ids = {event["event_id"] for event in events}
    if len(unique_ids) != len(events):
        print(
            f"  note: {len(events) - len(unique_ids)} duplicate record(s) collapse "
            "onto existing event ids"
        )

    print("\nDataset profile:")
    describe(events)

    if dry_run:
        print("\n--dry-run: nothing written to MongoDB.")
        return 0

    print(f"\nConnecting to {settings.mongo_uri} (database: {settings.mongo_db}) ...")
    await connection.connect()
    try:
        collection = collections.events()
        if drop:
            deleted = (await collection.delete_many({})).deleted_count
            print(f"Dropped {deleted} existing events")

        await collections.ensure_indexes()
        print("Indexes ensured")

        inserted = 0
        for start in range(0, len(events), batch_size):
            batch = events[start : start + batch_size]
            from pymongo import UpdateOne

            result = await collection.bulk_write(
                [
                    UpdateOne({"event_id": event["event_id"]}, {"$set": event}, upsert=True)
                    for event in batch
                ],
                ordered=False,
            )
            inserted += result.upserted_count
            print(
                f"  {min(start + batch_size, len(events)):>6}/{len(events)} "
                f"(new: {result.upserted_count}, updated: {result.modified_count})"
            )

        total = await collection.count_documents({})
        print(f"\nDone. Inserted {inserted} new events; collection holds {total}.")
    finally:
        await connection.close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load a network activity CSV into MongoDB.")
    parser.add_argument("--csv", type=Path, default=settings.resolved(settings.dataset_path))
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--drop", action="store_true", help="Delete existing events first.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and profile without writing."
    )
    args = parser.parse_args(argv)

    if not args.csv.exists():
        parser.error(f"CSV not found: {args.csv}")

    return asyncio.run(
        load(args.csv, batch_size=args.batch_size, drop=args.drop, dry_run=args.dry_run)
    )


if __name__ == "__main__":
    raise SystemExit(main())

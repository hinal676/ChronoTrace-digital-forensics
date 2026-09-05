"""Training for the ChronoTrace anomaly-detection model (spec 11, phase 7).

The dataset carries **no ground-truth label**, so supervised classification is not
available: there is nothing to learn "malicious" from. The spec anticipates this
and calls for unsupervised anomaly detection, so the model is an
``IsolationForest`` -- it isolates points that are easy to separate from the bulk
of traffic, needs no labels, handles the mixed-scale features here, and scores in
near-linear time.

The raw IsolationForest score is not interpretable on its own, so training also
persists a **calibration table**: the quantiles of the score distribution over the
training corpus. A new event's score is converted to a 0-1 risk by its percentile
rank against that table, which is what makes ``risk_score`` comparable between
runs. Per-feature percentiles are stored alongside it to explain each score.

Run directly::

    python -m app.ml.train --csv data/chronotrace_network_5000.csv
    python -m app.ml.train --from-mongo
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.collector.normalizer import normalize_many
from app.config import settings
from app.ml.features import (
    FEATURE_COLUMNS,
    build_feature_frame,
    compute_device_profiles,
    profiles_to_json,
)

logger = logging.getLogger(__name__)

MODEL_VERSION = "isolation-forest-v1"

# Risk bands. 0.87 lands in "requires_review", matching the spec's worked example.
DEFAULT_THRESHOLDS = {
    "low_concern": 0.50,
    "requires_review": 0.75,
    "high_priority": 0.90,
}

# Number of quantile points retained for score calibration.
CALIBRATION_POINTS = 1001


def load_events_from_csv(path: Path) -> list[dict[str, Any]]:
    """Read and normalize the development CSV."""
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    events, rejected = normalize_many(rows, source="dataset")
    if rejected:
        logger.warning("%d record(s) rejected during normalization", len(rejected))
    return events


async def load_events_from_mongo(limit: int = 0) -> list[dict[str, Any]]:
    """Read normalized events straight from MongoDB."""
    from app.database import collections, connection

    await connection.connect()
    try:
        cursor = collections.events().find({}, {"_id": 0})
        if limit:
            cursor = cursor.limit(limit)
        return [doc async for doc in cursor]
    finally:
        await connection.close()


def train_model(
    events: Sequence[Mapping[str, Any]],
    *,
    contamination: float | str = "auto",
    n_estimators: int = 300,
    random_state: int = 42,
) -> tuple[Pipeline, dict[str, Any]]:
    """Fit the anomaly detector and build its metadata sidecar.

    Returns ``(pipeline, metadata)``; the caller persists both.
    """
    if len(events) < 50:
        raise ValueError(f"need at least 50 events to train, got {len(events)}")

    profiles = compute_device_profiles(events)
    frame = build_feature_frame(events, profiles=profiles)
    matrix = frame.to_numpy(dtype=float)

    pipeline = Pipeline(
        [
            # Standardised first: IsolationForest splits per-feature, but scaling
            # keeps the persisted percentiles and explanations comparable.
            ("scaler", StandardScaler()),
            (
                "forest",
                IsolationForest(
                    n_estimators=n_estimators,
                    contamination=contamination,
                    max_samples="auto",
                    random_state=random_state,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    pipeline.fit(matrix)

    # Calibration: lower score_samples means more isolated (more anomalous).
    scores = pipeline.named_steps["forest"].score_samples(
        pipeline.named_steps["scaler"].transform(matrix)
    )
    quantiles = np.quantile(scores, np.linspace(0.0, 1.0, CALIBRATION_POINTS)).tolist()

    # Per-feature percentiles drive the human-readable reasons at predict time.
    feature_percentiles = {
        column: {
            "p01": float(np.percentile(frame[column], 1)),
            "p05": float(np.percentile(frame[column], 5)),
            "p50": float(np.percentile(frame[column], 50)),
            "p95": float(np.percentile(frame[column], 95)),
            "p99": float(np.percentile(frame[column], 99)),
            "mean": float(frame[column].mean()),
            "std": float(frame[column].std()),
        }
        for column in FEATURE_COLUMNS
    }

    flagged = int((pipeline.named_steps["forest"].predict(
        pipeline.named_steps["scaler"].transform(matrix)
    ) == -1).sum())

    metadata: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "model_type": "IsolationForest",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_events": len(events),
        "contamination": contamination if isinstance(contamination, float) else "auto",
        "n_estimators": n_estimators,
        "random_state": random_state,
        "features": list(FEATURE_COLUMNS),
        "score_quantiles": quantiles,
        "feature_percentiles": feature_percentiles,
        "thresholds": DEFAULT_THRESHOLDS,
        "device_profiles": profiles_to_json(profiles),
        "training_flagged": flagged,
        "training_score_range": [float(scores.min()), float(scores.max())],
    }
    return pipeline, metadata


def save_model(pipeline: Pipeline, metadata: dict[str, Any]) -> tuple[Path, Path]:
    """Persist the pipeline and its metadata sidecar."""
    model_path = settings.resolved(settings.model_path)
    meta_path = settings.resolved(settings.model_meta_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, model_path)
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return model_path, meta_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the ChronoTrace anomaly detector.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--csv", type=Path, help="Train from a CSV file.")
    source.add_argument("--from-mongo", action="store_true", help="Train from MongoDB events.")
    parser.add_argument(
        "--contamination", default="auto",
        help="Expected anomaly fraction: 'auto' or a float such as 0.02.",
    )
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.from_mongo:
        events = asyncio.run(load_events_from_mongo())
        origin = "MongoDB"
    else:
        path = args.csv or settings.resolved(settings.dataset_path)
        events = load_events_from_csv(path)
        origin = str(path)

    if not events:
        parser.error(f"no events loaded from {origin}")

    contamination: float | str = args.contamination
    if contamination != "auto":
        contamination = float(contamination)

    pipeline, metadata = train_model(
        events,
        contamination=contamination,
        n_estimators=args.n_estimators,
        random_state=args.random_state,
    )
    model_path, meta_path = save_model(pipeline, metadata)

    print(f"Trained {metadata['model_type']} on {len(events)} events from {origin}")
    print(f"  features        : {len(metadata['features'])}")
    print(f"  flagged (train) : {metadata['training_flagged']}")
    print(f"  model           : {model_path}")
    print(f"  metadata        : {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

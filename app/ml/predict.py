"""Scoring and explanation for the anomaly-detection model (spec 11).

Produces the spec's output shape -- a ``risk_score``, a ``classification`` band and
a list of human-readable ``reasons`` -- for each event.

Two deliberate choices:

* The score is an **indicator, never a verdict**. Bands are worded
  ``requires_review`` / ``high_priority``, not "malicious": an IsolationForest
  reports statistical unusualness, and unusual traffic is often legitimate.
* Reasons come from **rule checks against the training percentiles**, not from
  the forest itself. IsolationForest offers no per-feature attribution, so an
  invented one would be fiction; comparing each feature to the corpus it was
  trained on is a claim that can actually be checked.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np

from app.collector.normalizer import PORT_SERVICES
from app.config import settings
from app.ml.features import build_feature_frame, profiles_from_json
from app.ml.train import DEFAULT_THRESHOLDS, MODEL_VERSION
from app.models.common import Classification

logger = logging.getLogger(__name__)

__all__ = [
    "ModelNotTrainedError",
    "RiskModel",
    "get_model",
    "reload_model",
    "score_events",
    "model_info",
]


class ModelNotTrainedError(RuntimeError):
    """Raised when scoring is attempted before a model has been trained."""


class RiskModel:
    """A trained pipeline plus the metadata needed to interpret its scores."""

    def __init__(self, pipeline: Any, metadata: Mapping[str, Any]) -> None:
        self.pipeline = pipeline
        self.metadata = dict(metadata)
        self.features: list[str] = list(metadata.get("features", []))
        self.quantiles = np.asarray(metadata.get("score_quantiles", []), dtype=float)
        self.feature_percentiles: dict[str, dict[str, float]] = metadata.get(
            "feature_percentiles", {}
        )
        self.thresholds: dict[str, float] = {
            **DEFAULT_THRESHOLDS,
            **(metadata.get("thresholds") or {}),
        }
        self.device_profiles = profiles_from_json(metadata.get("device_profiles"))
        self.model_version: str = metadata.get("model_version", MODEL_VERSION)

    def raw_scores(self, matrix: np.ndarray) -> np.ndarray:
        """IsolationForest ``score_samples``: lower means more isolated."""
        return self.pipeline.named_steps["forest"].score_samples(
            self.pipeline.named_steps["scaler"].transform(matrix)
        )

    def to_risk(self, scores: np.ndarray) -> np.ndarray:
        """Map raw anomaly scores to an absolute 0-1 risk.

        The scale is anchored on two fixed points of the *training* score
        distribution: the median (risk 0) and the 1st percentile (risk 0.9, the
        ``high_priority`` threshold). Beyond that the tail is compressed
        exponentially so still-more-extreme events remain separable without ever
        reaching exactly 1.

        Anchoring on absolute score rather than percentile rank matters: a
        rank-based score would push a fixed share of *every* batch into the top
        band, so a quiet day would look as alarming as an incident. Here a batch
        of ordinary traffic scores near zero throughout, and the ordering of
        events is unchanged because the mapping is monotone.
        """
        if self.quantiles.size < 2:
            # No calibration table: fall back to a bounded squash of the raw score.
            return np.clip(0.5 - scores, 0.0, 1.0)

        median = float(self.quantiles[len(self.quantiles) // 2])
        tail = float(self.quantiles[max(len(self.quantiles) // 100, 1)])  # ~p01
        spread = median - tail
        if spread <= 0:
            return np.clip(0.5 - scores, 0.0, 1.0)

        # 0 at the training median, 1 at the training 1st percentile.
        normalized = (median - np.asarray(scores, dtype=float)) / spread
        within = np.clip(normalized, 0.0, 1.0)
        beyond = np.maximum(normalized - 1.0, 0.0)
        return np.clip(
            self.thresholds["high_priority"] * within
            + (1.0 - self.thresholds["high_priority"]) * (1.0 - np.exp(-beyond)),
            0.0,
            1.0,
        )

    def classify(self, risk: float) -> Classification:
        if risk >= self.thresholds["high_priority"]:
            return Classification.HIGH_PRIORITY
        if risk >= self.thresholds["requires_review"]:
            return Classification.REQUIRES_REVIEW
        if risk >= self.thresholds["low_concern"]:
            return Classification.LOW_CONCERN
        return Classification.NORMAL


_model: RiskModel | None = None
_lock = threading.Lock()


def _load() -> RiskModel:
    model_path: Path = settings.resolved(settings.model_path)
    meta_path: Path = settings.resolved(settings.model_meta_path)
    if not model_path.exists():
        raise ModelNotTrainedError(
            f"no trained model at {model_path}. Run: python -m app.ml.train"
        )
    pipeline = joblib.load(model_path)
    metadata: dict[str, Any] = {}
    if meta_path.exists():
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        logger.warning("model metadata missing at %s; scores will be uncalibrated", meta_path)
    return RiskModel(pipeline, metadata)


def get_model() -> RiskModel:
    """Return the process-wide model, loading it on first use."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = _load()
                logger.info("Loaded risk model %s", _model.model_version)
    return _model


def reload_model() -> RiskModel:
    """Drop the cached model and load it again (after retraining)."""
    global _model
    with _lock:
        _model = None
    return get_model()


def is_trained() -> bool:
    return settings.resolved(settings.model_path).exists()


def _percentile(model: RiskModel, feature: str, key: str, default: float = 0.0) -> float:
    return float(model.feature_percentiles.get(feature, {}).get(key, default))


def explain(
    model: RiskModel,
    event: Mapping[str, Any],
    row: Mapping[str, float],
) -> tuple[list[str], dict[str, float]]:
    """Human-readable factors behind an event's score.

    Each rule compares one feature against the training distribution, so a reason
    means "this is extreme relative to the corpus the model learned", not "this is
    an attack".
    """
    reasons: list[str] = []
    contributing: dict[str, float] = {}

    def flag(feature: str, message: str, *, above: str | None = None, below: str | None = None) -> None:
        value = float(row.get(feature, 0.0))
        if above is not None and value > _percentile(model, feature, above):
            reasons.append(message)
            contributing[feature] = round(value, 6)
        elif below is not None and value < _percentile(model, feature, below):
            reasons.append(message)
            contributing[feature] = round(value, 6)

    flag("src_bytes_log", "High outbound data volume", above="p99")
    flag("total_bytes_log", "Unusually large total data transfer", above="p99")
    flag("byte_ratio_log", "Strongly outbound-skewed byte exchange", above="p99")
    flag("packet_ratio_log", "Asymmetric packet exchange", above="p99")
    flag("bytes_per_second_log", "High sustained transfer rate", above="p99")
    flag("device_event_count_log", "Unusual communication frequency", above="p99")
    flag(
        "device_unique_destinations_log",
        "Source device contacts an unusually large number of destinations",
        above="p99",
    )
    flag("duration_log", "Unusually long-lived connection", above="p99")

    # "Uncommon destination" only means something once the device has enough
    # history for its normal pattern to be established.
    if float(row.get("device_event_count_log", 0.0)) > _percentile(
        model, "device_event_count_log", "p50"
    ) and float(row.get("destination_share", 1.0)) < _percentile(
        model, "destination_share", "p05", 0.0
    ):
        reasons.append("Destination is uncommon for this source device")
        contributing["destination_share"] = round(float(row.get("destination_share", 0.0)), 6)

    if float(row.get("bytes_vs_device_mean", 0.0)) > _percentile(
        model, "bytes_vs_device_mean", "p99"
    ):
        reasons.append("Data volume far exceeds this device's usual level")
        contributing["bytes_vs_device_mean"] = round(float(row.get("bytes_vs_device_mean", 0.0)), 6)

    dst_port = event.get("dst_port")
    if dst_port is not None and int(dst_port) not in PORT_SERVICES:
        reasons.append(f"Destination port {dst_port} is not a recognised common service")
        contributing["dst_port"] = float(dst_port)

    if not event.get("dst_packets"):
        reasons.append("No response traffic from the destination")
        contributing["dst_packets"] = 0.0

    if not reasons:
        reasons.append("Overall traffic pattern differs from the learned baseline")

    return reasons, contributing


def score_events(
    events: Sequence[Mapping[str, Any]],
    *,
    model: RiskModel | None = None,
) -> list[dict[str, Any]]:
    """Score a batch of normalized events.

    Returns one dict per event matching the ``EventRisk`` model.
    """
    if not events:
        return []

    model = model or get_model()
    frame = build_feature_frame(events, profiles=model.device_profiles)

    if model.features and list(frame.columns) != model.features:
        # Reorder to the trained layout; a genuinely different feature set is a
        # stale model and must fail loudly rather than score nonsense.
        missing = set(model.features) - set(frame.columns)
        if missing:
            raise ModelNotTrainedError(
                f"model expects features not produced by this build: {sorted(missing)}. "
                "Retrain with: python -m app.ml.train"
            )
        frame = frame[model.features]

    matrix = frame.to_numpy(dtype=float)
    raw = model.raw_scores(matrix)
    risks = model.to_risk(raw)

    results: list[dict[str, Any]] = []
    for position, event in enumerate(events):
        row = frame.iloc[position].to_dict()
        risk = float(risks[position])
        reasons, contributing = explain(model, event, row)
        results.append(
            {
                "event_id": str(event.get("event_id", "")),
                "src_device": event.get("src_device"),
                "dst_device": event.get("dst_device"),
                "timestamp": event.get("timestamp"),
                "risk_score": round(risk, 4),
                "classification": model.classify(risk),
                "reasons": reasons,
                "anomaly_score": round(float(raw[position]), 6),
                "contributing_features": contributing,
            }
        )
    return results


def model_info() -> dict[str, Any]:
    """Metadata for ``GET /analysis/model``."""
    if not is_trained():
        return {"trained": False, "features": [], "thresholds": DEFAULT_THRESHOLDS}
    model = get_model()
    trained_at = model.metadata.get("trained_at")
    return {
        "trained": True,
        "model_type": model.metadata.get("model_type"),
        "model_version": model.model_version,
        "trained_at": datetime.fromisoformat(trained_at) if trained_at else None,
        "training_events": model.metadata.get("training_events"),
        "contamination": model.metadata.get("contamination")
        if isinstance(model.metadata.get("contamination"), (int, float))
        else None,
        "features": model.features,
        "thresholds": model.thresholds,
    }

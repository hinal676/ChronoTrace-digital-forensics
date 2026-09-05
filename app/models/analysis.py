"""Models for the machine-learning / anomaly-analysis layer (spec 11)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import Classification


class EventRisk(BaseModel):
    """Risk indicator for a single event.

    Mirrors the spec's example output: a score, a band, and the human-readable
    factors that drove it.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_id": "evt_d5c7cdd218ddad59",
                "risk_score": 0.87,
                "classification": "requires_review",
                "reasons": [
                    "High outbound data volume",
                    "Unusual communication frequency",
                    "Destination is uncommon for this source device",
                ],
            }
        }
    )

    event_id: str
    src_device: str | None = None
    dst_device: str | None = None
    timestamp: int | None = None
    risk_score: float = Field(..., ge=0.0, le=1.0)
    classification: Classification
    reasons: list[str] = Field(default_factory=list)
    anomaly_score: float | None = Field(
        None, description="Raw IsolationForest score; lower means more isolated."
    )
    contributing_features: dict[str, float] = Field(
        default_factory=dict, description="Feature values that triggered the reasons."
    )


class AnalysisRequest(BaseModel):
    """Run an analysis over a filtered slice of events."""

    model_config = ConfigDict(extra="forbid")

    src_device: str | None = None
    dst_device: str | None = None
    device: str | None = Field(None, description="Match the device as either source or destination.")
    protocol: int | None = Field(None, ge=0, le=255)
    dst_port: int | None = Field(None, ge=0, le=65535)
    start_time: int | None = Field(None, ge=0)
    end_time: int | None = Field(None, ge=0)
    min_bytes: int | None = Field(None, ge=0)
    limit: int = Field(2000, ge=1, le=50_000, description="Max events to score.")
    top_n: int = Field(25, ge=1, le=1000, description="How many flagged events to return.")
    min_risk_score: float = Field(0.0, ge=0.0, le=1.0)
    persist: bool = Field(True, description="Store the result for later retrieval by id.")


class AnalysisSummary(BaseModel):
    analyzed_events: int
    flagged_events: int
    mean_risk_score: float
    max_risk_score: float
    classification_counts: dict[str, int] = Field(default_factory=dict)
    top_risk_devices: list[dict] = Field(default_factory=list)
    top_reasons: list[dict] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    # `model_version` collides with Pydantic's protected `model_` namespace.
    model_config = ConfigDict(protected_namespaces=())

    analysis_id: str | None = None
    created_at: datetime | None = None
    model_version: str | None = None
    request: AnalysisRequest | None = None
    summary: AnalysisSummary
    results: list[EventRisk] = Field(default_factory=list)


class DeviceRisk(BaseModel):
    """Rolled-up risk for one device."""

    device: str
    event_count: int
    mean_risk_score: float
    max_risk_score: float
    flagged_events: int
    classification: Classification
    top_reasons: list[str] = Field(default_factory=list)


class ModelInfo(BaseModel):
    """Metadata about the trained anomaly-detection model."""

    model_config = ConfigDict(protected_namespaces=())

    trained: bool
    model_type: str | None = None
    model_version: str | None = None
    trained_at: datetime | None = None
    training_events: int | None = None
    contamination: float | None = None
    features: list[str] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=dict)

"""Investigation models: a device-centred case file combining graph and ML output."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.analysis import AnalysisSummary, EventRisk
from app.models.common import Classification, WeightStrategy
from app.models.event import DeviceSummary, Event, RelatedDevice
from app.models.graph import EdgeSummary


class InvestigationRequest(BaseModel):
    """Open an investigation focused on one device."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "device": "Comp431255",
                "depth": 2,
                "start_time": None,
                "end_time": None,
                "title": "Suspected outbound transfer",
            }
        },
    )

    device: str = Field(..., min_length=1, description="Focus device for the investigation.")
    title: str | None = None
    notes: str | None = None
    analyst: str | None = None
    depth: int = Field(2, ge=1, le=5, description="Neighbourhood depth explored via BFS.")
    start_time: int | None = Field(None, ge=0)
    end_time: int | None = Field(None, ge=0)
    max_events: int = Field(1000, ge=1, le=20_000, description="Events pulled for the focus device.")
    top_n: int = Field(20, ge=1, le=500, description="Risky events included in the report.")
    weight: WeightStrategy = Field(
        WeightStrategy.STRENGTH, description="Cost model for path finding to related devices."
    )
    persist: bool = True


class InvestigationFindings(BaseModel):
    """The analytical body of an investigation report."""

    device_summary: DeviceSummary
    related_devices: list[RelatedDevice] = Field(default_factory=list)
    neighborhood_levels: dict[int, list[str]] = Field(default_factory=dict)
    neighborhood_edges: list[EdgeSummary] = Field(default_factory=list)
    risk_summary: AnalysisSummary
    risky_events: list[EventRisk] = Field(default_factory=list)
    notable_events: list[Event] = Field(default_factory=list)
    observations: list[str] = Field(
        default_factory=list, description="Plain-language findings for the case file."
    )


class Investigation(BaseModel):
    """A stored investigation record."""

    model_config = ConfigDict(extra="ignore")

    investigation_id: str
    device: str
    title: str | None = None
    notes: str | None = None
    analyst: str | None = None
    status: str = "open"
    created_at: datetime
    updated_at: datetime | None = None
    overall_risk_score: float = Field(0.0, ge=0.0, le=1.0)
    classification: Classification = Classification.NORMAL
    request: InvestigationRequest | None = None
    findings: InvestigationFindings | None = None


class InvestigationUpdate(BaseModel):
    """Analyst edits to an existing case."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    notes: str | None = None
    analyst: str | None = None
    status: str | None = Field(None, description='e.g. "open", "in_review", "closed".')

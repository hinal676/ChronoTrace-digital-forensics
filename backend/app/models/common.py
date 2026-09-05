"""Shared model primitives and enums."""

from __future__ import annotations

from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Classification(str, Enum):
    """Risk bands returned by the analysis layer.

    Deliberately worded as indicators, not verdicts: the ML layer reports that
    traffic *warrants review*, never that it is malicious (spec 11).
    """

    NORMAL = "normal"
    LOW_CONCERN = "low_concern"
    REQUIRES_REVIEW = "requires_review"
    HIGH_PRIORITY = "high_priority"


class WeightStrategy(str, Enum):
    """Edge-cost strategies available to Dijkstra and A* (spec 10.3)."""

    HOPS = "hops"
    FREQUENCY = "frequency"
    BYTES = "bytes"
    DURATION = "duration"
    STRENGTH = "strength"


class Heuristic(str, Enum):
    """Heuristics available to A* (spec 10.4)."""

    ZERO = "zero"
    HOP_LOWER_BOUND = "hop_lower_bound"


class Direction(str, Enum):
    """Edge direction to follow during traversal."""

    OUTBOUND = "outbound"
    INBOUND = "inbound"
    BOTH = "both"


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class Page(BaseModel, Generic[T]):
    """Envelope for paginated list responses."""

    total: int = Field(..., description="Total documents matching the filter.")
    limit: int
    skip: int
    count: int = Field(..., description="Number of items in this page.")
    items: list[T]


class StatusResponse(BaseModel):
    status: str
    detail: str | None = None

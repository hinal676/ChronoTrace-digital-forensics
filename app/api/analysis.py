"""Analysis endpoints exposing the anomaly-detection layer (spec 11, 12)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.ml import predict
from app.models.analysis import (
    AnalysisRequest,
    AnalysisResponse,
    DeviceRisk,
    ModelInfo,
)
from app.services import analysis_service

router = APIRouter(tags=["analysis"])

_NOT_TRAINED = (
    "No trained model is available. Train one with: python -m app.ml.train"
)


def _require_model() -> None:
    if not predict.is_trained():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_NOT_TRAINED
        )


@router.post(
    "/analysis",
    response_model=AnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Score a slice of traffic for unusual activity",
)
async def run_analysis(request: AnalysisRequest) -> AnalysisResponse:
    """Score filtered events and return the highest-risk ones.

    Scores are indicators of statistical unusualness, not verdicts: an event
    flagged ``requires_review`` needs an analyst, not a conclusion.
    """
    _require_model()
    try:
        result = await analysis_service.run_analysis(request)
    except predict.ModelNotTrainedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return AnalysisResponse(**result)


@router.get("/analysis", summary="List stored analyses")
async def list_analyses(
    limit: int = Query(20, ge=1, le=200), skip: int = Query(0, ge=0)
) -> dict:
    return await analysis_service.list_analyses(limit=limit, skip=skip)


@router.get("/analysis/model", response_model=ModelInfo, summary="Trained model metadata")
async def get_model_info() -> ModelInfo:
    """Report which model is loaded, its features and its risk thresholds."""
    return ModelInfo(**predict.model_info())


@router.post("/analysis/model/reload", summary="Reload the model from disk")
async def reload_model() -> dict:
    """Pick up a newly trained model without restarting the API."""
    _require_model()
    model = predict.reload_model()
    return {"status": "reloaded", "model_version": model.model_version}


@router.get(
    "/analysis/device/{device}",
    response_model=DeviceRisk,
    summary="Rolled-up risk for one device",
)
async def device_risk(
    device: str, limit: int = Query(1000, ge=1, le=20_000)
) -> DeviceRisk:
    _require_model()
    result = await analysis_service.score_device(device, limit=limit)
    if not result["event_count"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no outbound events for device {device}",
        )
    return DeviceRisk(**result)


@router.get(
    "/analysis/{analysis_id}",
    response_model=AnalysisResponse,
    summary="Fetch a stored analysis",
)
async def get_analysis(analysis_id: str) -> AnalysisResponse:
    document = await analysis_service.get_analysis(analysis_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no analysis with id {analysis_id}",
        )
    return AnalysisResponse(**document)

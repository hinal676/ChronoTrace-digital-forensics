"""Investigation endpoints: device-centred case files (spec 12)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.ml import predict
from app.models.common import StatusResponse
from app.models.investigation import Investigation, InvestigationRequest, InvestigationUpdate
from app.services import analysis_service

router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.post(
    "",
    response_model=Investigation,
    status_code=status.HTTP_201_CREATED,
    summary="Open an investigation into a device",
)
async def create_investigation(request: InvestigationRequest) -> Investigation:
    """Assemble a case file for one device.

    Combines its stored activity, its graph neighbourhood (BFS) and ML risk
    scoring into a single structured report a frontend can render directly.
    """
    if not predict.is_trained():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No trained model is available. Train one with: python -m app.ml.train",
        )
    document = await analysis_service.run_investigation(request)
    return Investigation(**document)


@router.get("", summary="List investigations")
async def list_investigations(
    device: str | None = Query(None),
    investigation_status: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=200),
    skip: int = Query(0, ge=0),
) -> dict:
    return await analysis_service.list_investigations(
        device=device, status=investigation_status, limit=limit, skip=skip
    )


@router.get("/{investigation_id}", response_model=Investigation, summary="Fetch an investigation")
async def get_investigation(investigation_id: str) -> Investigation:
    document = await analysis_service.get_investigation(investigation_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no investigation with id {investigation_id}",
        )
    return Investigation(**document)


@router.patch(
    "/{investigation_id}", response_model=Investigation, summary="Update case notes or status"
)
async def update_investigation(
    investigation_id: str, changes: InvestigationUpdate
) -> Investigation:
    document = await analysis_service.update_investigation(
        investigation_id, changes.model_dump(exclude_none=True)
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no investigation with id {investigation_id}",
        )
    return Investigation(**document)


@router.delete(
    "/{investigation_id}", response_model=StatusResponse, summary="Delete an investigation"
)
async def delete_investigation(investigation_id: str) -> StatusResponse:
    if not await analysis_service.delete_investigation(investigation_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no investigation with id {investigation_id}",
        )
    return StatusResponse(status="deleted", detail=investigation_id)

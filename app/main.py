"""ChronoTrace FastAPI application (spec 12).

Wires storage, the graph engine and the ML layer behind one REST surface::

    Network events -> normalizer -> MongoDB -> NetworkX graph -> BFS/DFS/Dijkstra/A*
                                            -> anomaly detection -> investigation results

Run with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from app.api import analysis, events, graph, investigations, timeline
from app.collector.normalizer import NormalizationError
from app.config import settings
from app.database import collections, connection
from app.ml import predict

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Connect to MongoDB and prepare indexes on startup; close cleanly on shutdown.

    A missing database is logged rather than fatal, so the service still starts and
    reports its state through ``/health`` instead of crash-looping.
    """
    try:
        await connection.connect()
        await collections.ensure_indexes()
    except PyMongoError as exc:
        logger.error("MongoDB unavailable at startup: %s", exc)

    if predict.is_trained():
        try:
            predict.get_model()
        except Exception as exc:  # noqa: BLE001 - never block startup on the model
            logger.warning("Could not preload risk model: %s", exc)
    else:
        logger.warning(
            "No trained model found. Analysis endpoints will return 503 until you run: "
            "python -m app.ml.train"
        )

    yield

    await connection.close()


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    lifespan=lifespan,
    summary="Intelligent digital investigation backend for network activity logs.",
    description=(
        "ChronoTrace ingests authorized network activity logs, stores them in MongoDB, "
        "represents device communication as a relationship graph, applies BFS, DFS, "
        "Dijkstra and A*, and scores traffic with unsupervised anomaly detection.\n\n"
        "**Risk scores are investigative indicators, not determinations of malicious "
        "activity.** Every flagged event requires analyst review."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(NormalizationError)
async def _normalization_error(request: Request, exc: NormalizationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": f"invalid network event: {exc}"},
    )


@app.exception_handler(connection.DatabaseNotConnectedError)
async def _db_not_connected(
    request: Request, exc: connection.DatabaseNotConnectedError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
    )


@app.exception_handler(PyMongoError)
async def _mongo_error(request: Request, exc: PyMongoError) -> JSONResponse:
    logger.error("MongoDB error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": f"database error: {exc}"},
    )


@app.exception_handler(predict.ModelNotTrainedError)
async def _model_error(request: Request, exc: predict.ModelNotTrainedError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
    )


@app.get("/", tags=["meta"], summary="Service banner")
async def root() -> dict:
    return {
        "name": settings.api_title,
        "version": settings.api_version,
        "description": "Intelligent digital investigation backend for network activity logs.",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["meta"], summary="Health and readiness")
async def health() -> dict:
    """Report database connectivity and whether a risk model is loaded."""
    database = await connection.ping()
    return {
        "status": "ok" if database.get("connected") else "degraded",
        "database": database,
        "model": {
            "trained": predict.is_trained(),
            "version": predict.get_model().model_version if predict.is_trained() else None,
        },
    }


app.include_router(events.router)
app.include_router(timeline.router)
app.include_router(graph.router)
app.include_router(analysis.router)
app.include_router(investigations.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port, reload=True)

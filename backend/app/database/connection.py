"""MongoDB connection lifecycle.

Uses PyMongo's native async driver (``AsyncMongoClient``, PyMongo >= 4.13) rather
than Motor, which MongoDB has deprecated in favour of this driver.
"""

from __future__ import annotations

import logging

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.config import settings

logger = logging.getLogger(__name__)

_client: AsyncMongoClient | None = None
_database: AsyncDatabase | None = None


class DatabaseNotConnectedError(RuntimeError):
    """Raised when the database is used before ``connect()`` succeeded."""


async def connect() -> AsyncDatabase:
    """Open the client and verify the server is reachable."""
    global _client, _database

    if _database is not None:
        return _database

    client: AsyncMongoClient = AsyncMongoClient(
        settings.mongo_uri,
        serverSelectionTimeoutMS=settings.mongo_timeout_ms,
        connectTimeoutMS=settings.mongo_timeout_ms,
        tz_aware=True,
    )
    # Fail fast and loudly rather than deferring the error to the first query.
    await client.admin.command("ping")

    _client = client
    _database = client[settings.mongo_db]
    logger.info("Connected to MongoDB database %r", settings.mongo_db)
    return _database


async def close() -> None:
    """Close the client and reset module state."""
    global _client, _database
    if _client is not None:
        await _client.close()
        logger.info("Closed MongoDB connection")
    _client = None
    _database = None


def get_database() -> AsyncDatabase:
    """Return the connected database, or raise if startup did not connect."""
    if _database is None:
        raise DatabaseNotConnectedError(
            "MongoDB is not connected. Check CHRONOTRACE_MONGO_URI and that the server is running."
        )
    return _database


def is_connected() -> bool:
    return _database is not None


async def ping() -> dict[str, object]:
    """Health probe used by ``GET /health``."""
    if _client is None:
        return {"connected": False, "error": "not connected"}
    try:
        await _client.admin.command("ping")
        return {"connected": True, "database": settings.mongo_db}
    except PyMongoError as exc:
        return {"connected": False, "error": str(exc)}

"""Shared fixtures.

Tests split into two groups: the pure layers (normalizer, graph, ML) run
anywhere, while anything touching storage is marked ``mongo`` and skips when no
server is reachable -- so the suite stays green on a machine without MongoDB
instead of reporting false failures.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.collector.normalizer import normalize_many  # noqa: E402
from app.config import settings  # noqa: E402
from app.graph.builder import build_graph  # noqa: E402

DATASET = PROJECT_ROOT / "data" / "chronotrace_network_5000.csv"

# Redirect every test to a dedicated database. The suite inserts fixtures and
# deletes events, so pointing it at the configured database would corrupt real
# investigation data. Mutating the settings singleton here works because
# `connection.connect()` reads the database name at call time, and this module is
# imported before any test opens a connection.
TEST_DB_SUFFIX = "_test"
if not settings.mongo_db.endswith(TEST_DB_SUFFIX):
    settings.mongo_db = f"{settings.mongo_db}{TEST_DB_SUFFIX}"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "mongo: requires a running MongoDB server")
    config.addinivalue_line("markers", "model: requires a trained model on disk")


@pytest.fixture(scope="session")
def raw_rows() -> list[dict[str, str]]:
    if not DATASET.exists():
        pytest.skip(f"dataset not found at {DATASET}")
    with open(DATASET, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="session")
def events(raw_rows: list[dict[str, str]]) -> list[dict]:
    normalized, rejected = normalize_many(raw_rows, source="dataset")
    assert not rejected, f"dataset failed to normalize: {rejected[:3]}"
    return normalized


@pytest.fixture(scope="session")
def graph(events: list[dict]):
    return build_graph(events)


@pytest.fixture(scope="session")
def sample_event() -> dict:
    """One raw row in the dataset's own column names and formats."""
    return {
        "Time": "1720001344",
        "Duration": "10540",
        "SrcDevice": "Comp679356",
        "DstDevice": "Comp654763",
        "Protocol": "6",
        "SrcPort": "Port62917",
        "DstPort": "443",
        "SrcPackets": "4636",
        "DstPackets": "9480",
        "SrcBytes": "3782976",
        "DstBytes": "6948840",
    }


@pytest.fixture(scope="session")
def mongo_available() -> bool:
    """Quick probe so DB-backed tests skip rather than hang."""
    try:
        from pymongo import MongoClient

        client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=750)
        client.admin.command("ping")
        client.close()
        return True
    except Exception:
        return False


@pytest.fixture
def require_mongo(mongo_available: bool) -> None:
    if not mongo_available:
        pytest.skip("no MongoDB server reachable at CHRONOTRACE_MONGO_URI")


@pytest.fixture
def require_model() -> None:
    from app.ml import predict

    if not predict.is_trained():
        pytest.skip("no trained model; run: python -m app.ml.train")

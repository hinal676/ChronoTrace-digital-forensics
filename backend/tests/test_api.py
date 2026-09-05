"""API tests.

Meta endpoints are exercised everywhere. Everything that touches storage is
marked ``mongo`` and skips when no server is reachable, so the suite reports
"skipped", not "failed", on a machine without MongoDB.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings

# Keep startup fast when no database is listening.
settings.mongo_timeout_ms = 800


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def seeded(client, mongo_available, events):
    """Load a slice of the dataset so the DB-backed endpoints have data."""
    if not mongo_available:
        pytest.skip("no MongoDB server reachable")
    response = client.post(
        "/events/bulk",
        json={"events": [_to_payload(event) for event in events[:400]], "source": "test"},
    )
    assert response.status_code == 201, response.text
    return events[:400]


def _to_payload(event: dict) -> dict:
    """Canonical document -> API ingestion payload."""
    return {
        "Time": event["timestamp"],
        "Duration": event["duration"],
        "SrcDevice": event["src_device"],
        "DstDevice": event["dst_device"],
        "Protocol": event["protocol"],
        "SrcPort": event["src_port"],
        "DstPort": event["dst_port"],
        "SrcPackets": event["src_packets"],
        "DstPackets": event["dst_packets"],
        "SrcBytes": event["src_bytes"],
        "DstBytes": event["dst_bytes"],
    }


class TestMeta:
    def test_root(self, client):
        body = client.get("/").json()
        assert body["name"] == settings.api_title
        assert body["docs"] == "/docs"

    def test_health_reports_subsystems(self, client):
        body = client.get("/health").json()
        assert body["status"] in {"ok", "degraded"}
        assert "database" in body and "model" in body

    def test_openapi_documents_every_router(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        for path in ("/events", "/timeline", "/graph/bfs", "/graph/dijkstra",
                     "/analysis", "/investigations", "/relationships/{device}"):
            assert path in paths


class TestValidation:
    """Input validation runs before any database access."""

    def test_rejects_missing_fields(self, client):
        assert client.post("/events", json={"Time": 1720001344}).status_code == 422

    def test_rejects_bad_port_label(self, client, events):
        payload = {**_to_payload(events[0]), "SrcPort": "not-a-port"}
        assert client.post("/events", json=payload).status_code == 422

    def test_accepts_dataset_port_label(self, client, events, mongo_available):
        payload = {**_to_payload(events[0]), "SrcPort": "Port62917"}
        response = client.post("/events", json=payload)
        assert response.status_code in ({201} if mongo_available else {201, 503})

    def test_rejects_negative_bytes(self, client, events):
        payload = {**_to_payload(events[0]), "SrcBytes": -5}
        assert client.post("/events", json=payload).status_code == 422

    def test_rejects_bad_sort_field(self, client):
        assert client.get("/events", params={"sort_by": "; drop"}).status_code in {400, 503}

    def test_rejects_out_of_range_depth(self, client):
        response = client.post("/graph/bfs", json={"source": "Comp1", "max_depth": 99})
        assert response.status_code == 422


@pytest.mark.mongo
class TestEvents:
    def test_ingest_is_idempotent(self, client, seeded):
        """Re-posting the same events upserts rather than duplicating."""
        payload = {"events": [_to_payload(event) for event in seeded[:20]], "source": "test"}
        first = client.post("/events/bulk", json=payload).json()
        second = client.post("/events/bulk", json=payload).json()
        assert second["inserted"] == 0
        assert second["duplicates"] == 20
        assert first["received"] == 20

    def test_list_returns_page_envelope(self, client, seeded):
        body = client.get("/events", params={"limit": 5}).json()
        assert body["count"] == 5 and body["total"] >= 400
        assert len(body["items"]) == 5

    def test_filter_by_src_device(self, client, seeded):
        device = seeded[0]["src_device"]
        body = client.get("/events", params={"src_device": device, "limit": 50}).json()
        assert body["total"] >= 1
        assert all(item["src_device"] == device for item in body["items"])

    def test_filter_by_protocol_and_port(self, client, seeded):
        body = client.get("/events", params={"protocol": 6, "dst_port": 443}).json()
        assert all(i["protocol"] == 6 and i["dst_port"] == 443 for i in body["items"])

    def test_filter_by_time_window(self, client, seeded):
        start = min(e["timestamp"] for e in seeded)
        end = start + 86400
        body = client.get("/events", params={"start_time": start, "end_time": end}).json()
        assert all(start <= i["timestamp"] <= end for i in body["items"])

    def test_filter_by_min_bytes(self, client, seeded):
        body = client.get("/events", params={"min_bytes": 10_000_000}).json()
        assert all(item["total_bytes"] >= 10_000_000 for item in body["items"])

    def test_device_filter_matches_either_end(self, client, seeded):
        device = seeded[0]["dst_device"]
        body = client.get("/events", params={"device": device}).json()
        assert all(
            item["src_device"] == device or item["dst_device"] == device
            for item in body["items"]
        )

    def test_pagination_does_not_repeat(self, client, seeded):
        first = client.get("/events", params={"limit": 10, "skip": 0}).json()["items"]
        second = client.get("/events", params={"limit": 10, "skip": 10}).json()["items"]
        assert {i["event_id"] for i in first}.isdisjoint({i["event_id"] for i in second})

    def test_get_and_delete_single_event(self, client, seeded):
        event_id = client.get("/events", params={"limit": 1}).json()["items"][0]["event_id"]
        assert client.get(f"/events/{event_id}").json()["event_id"] == event_id
        assert client.delete(f"/events/{event_id}").status_code == 200
        assert client.get(f"/events/{event_id}").status_code == 404

    def test_unknown_event_is_404(self, client, seeded):
        assert client.get("/events/evt_does_not_exist").status_code == 404

    def test_derived_fields_are_returned(self, client, seeded):
        item = client.get("/events", params={"limit": 1}).json()["items"][0]
        assert item["total_bytes"] == item["src_bytes"] + item["dst_bytes"]
        assert item["protocol_name"] in {"TCP", "UDP"}


@pytest.mark.mongo
class TestTimelineAndRelationships:
    def test_timeline_buckets(self, client, seeded):
        body = client.get("/timeline", params={"interval": 86400}).json()
        assert body["interval_seconds"] == 86400
        assert body["buckets"]
        starts = [bucket["bucket_start"] for bucket in body["buckets"]]
        assert starts == sorted(starts)

    def test_timeline_raw_is_time_ordered(self, client, seeded):
        body = client.get("/timeline", params={"raw": True, "limit": 50}).json()
        stamps = [event["timestamp"] for event in body["events"]]
        assert stamps == sorted(stamps)

    def test_relationships(self, client, seeded):
        device = seeded[0]["src_device"]
        body = client.get(f"/relationships/{device}").json()
        assert body["device"] == device
        assert body["summary"]["total_events"] > 0
        assert body["related"]

    def test_relationships_unknown_device_is_404(self, client, seeded):
        assert client.get("/relationships/NoSuchDevice").status_code == 404

    def test_devices_and_protocols(self, client, seeded):
        assert client.get("/devices").json()["total"] > 0
        assert client.get("/protocols").json()
        assert client.get("/ports", params={"limit": 5}).json()


@pytest.mark.mongo
class TestGraphAPI:
    def test_stats(self, client, seeded):
        client.post("/graph/rebuild")
        body = client.get("/graph/stats").json()
        assert body["node_count"] > 0 and body["edge_count"] > 0

    def test_bfs(self, client, seeded):
        source = seeded[0]["src_device"]
        body = client.post("/graph/bfs", json={"source": source, "max_depth": 2}).json()
        assert body["algorithm"] == "bfs"
        assert body["nodes"][0]["device"] == source
        assert body["levels"]

    def test_dfs(self, client, seeded):
        source = seeded[0]["src_device"]
        body = client.post("/graph/dfs", json={"source": source, "max_depth": 3}).json()
        assert body["algorithm"] == "dfs"
        assert body["order"][0] == source

    def test_dijkstra_and_astar_agree(self, client, seeded):
        source, target = seeded[0]["src_device"], seeded[0]["dst_device"]
        payload = {"source": source, "target": target, "weight": "strength"}
        first = client.post("/graph/dijkstra", json=payload).json()
        second = client.post("/graph/astar", json=payload).json()
        assert first["found"] == second["found"]
        if first["found"]:
            assert first["cost"] == pytest.approx(second["cost"], abs=1e-6)

    def test_dijkstra_alternatives(self, client, seeded):
        source, target = seeded[0]["src_device"], seeded[0]["dst_device"]
        body = client.post(
            "/graph/dijkstra", json={"source": source, "target": target, "k": 3}
        ).json()
        assert body["found"] is True

    def test_unknown_device_is_404(self, client, seeded):
        response = client.post("/graph/bfs", json={"source": "NoSuchDevice"})
        assert response.status_code == 404

    def test_neighborhood(self, client, seeded):
        device = seeded[0]["src_device"]
        body = client.get(f"/graph/neighborhood/{device}", params={"depth": 1}).json()
        assert body["device"] == device and body["nodes"]


@pytest.mark.mongo
class TestAnalysisAPI:
    def test_model_info(self, client, require_model):
        body = client.get("/analysis/model").json()
        assert body["trained"] is True
        assert body["features"]

    def test_run_analysis(self, client, seeded, require_model):
        body = client.post("/analysis", json={"limit": 200, "top_n": 5}).json()
        assert body["summary"]["analyzed_events"] > 0
        assert len(body["results"]) <= 5
        for result in body["results"]:
            assert 0.0 <= result["risk_score"] <= 1.0
            assert result["reasons"]

    def test_analysis_is_retrievable(self, client, seeded, require_model):
        created = client.post("/analysis", json={"limit": 100, "persist": True}).json()
        fetched = client.get(f"/analysis/{created['analysis_id']}").json()
        assert fetched["analysis_id"] == created["analysis_id"]

    def test_results_are_sorted_by_risk(self, client, seeded, require_model):
        body = client.post("/analysis", json={"limit": 300, "top_n": 20}).json()
        scores = [r["risk_score"] for r in body["results"]]
        assert scores == sorted(scores, reverse=True)

    def test_unknown_analysis_is_404(self, client, seeded):
        assert client.get("/analysis/ana_missing").status_code == 404

    def test_device_risk(self, client, seeded, require_model):
        device = seeded[0]["src_device"]
        body = client.get(f"/analysis/device/{device}").json()
        assert body["device"] == device
        assert body["classification"] in {
            "normal", "low_concern", "requires_review", "high_priority"
        }


@pytest.mark.mongo
class TestInvestigationsAPI:
    def test_full_lifecycle(self, client, seeded, require_model):
        device = seeded[0]["src_device"]
        created = client.post(
            "/investigations", json={"device": device, "depth": 2, "title": "Test case"}
        ).json()
        investigation_id = created["investigation_id"]

        assert created["device"] == device
        assert created["findings"]["observations"]
        assert created["findings"]["device_summary"]["total_events"] > 0

        fetched = client.get(f"/investigations/{investigation_id}").json()
        assert fetched["investigation_id"] == investigation_id

        updated = client.patch(
            f"/investigations/{investigation_id}",
            json={"status": "closed", "notes": "Reviewed."},
        ).json()
        assert updated["status"] == "closed" and updated["notes"] == "Reviewed."

        assert client.get("/investigations", params={"device": device}).json()["total"] >= 1
        assert client.delete(f"/investigations/{investigation_id}").status_code == 200
        assert client.get(f"/investigations/{investigation_id}").status_code == 404

    def test_unknown_investigation_is_404(self, client, seeded):
        assert client.get("/investigations/inv_missing").status_code == 404

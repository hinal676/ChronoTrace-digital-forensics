"""Tests for MongoDB query construction.

The database-backed endpoints cannot run without a server, but the *shape* of the
queries they send can be verified anywhere -- and a malformed filter is the most
likely defect in that layer. These run with no MongoDB present.
"""

from __future__ import annotations

import pytest

from app.services.event_service import EventFilter


class TestEventFilter:
    def test_empty_filter_matches_everything(self):
        assert EventFilter().to_query() == {}

    def test_exact_match_fields(self):
        query = EventFilter(
            src_device="Comp1", dst_device="Comp2", protocol=6,
            src_port=1234, dst_port=443, source="dataset",
        ).to_query()
        assert query == {
            "src_device": "Comp1", "dst_device": "Comp2", "protocol": 6,
            "src_port": 1234, "dst_port": 443, "source": "dataset",
        }

    def test_device_matches_either_end(self):
        query = EventFilter(device="Comp1").to_query()
        assert query["$or"] == [{"src_device": "Comp1"}, {"dst_device": "Comp1"}]

    def test_time_window_becomes_a_range(self):
        query = EventFilter(start_time=100, end_time=200).to_query()
        assert query["timestamp"] == {"$gte": 100, "$lte": 200}

    def test_open_ended_ranges(self):
        assert EventFilter(start_time=100).to_query()["timestamp"] == {"$gte": 100}
        assert EventFilter(end_time=200).to_query()["timestamp"] == {"$lte": 200}

    def test_byte_and_duration_bounds(self):
        query = EventFilter(min_bytes=1000, max_bytes=5000, min_duration=1.5).to_query()
        assert query["total_bytes"] == {"$gte": 1000, "$lte": 5000}
        assert query["duration"] == {"$gte": 1.5}

    def test_zero_is_a_real_bound_not_a_missing_value(self):
        """`0` is falsy; the filter must still emit it."""
        assert EventFilter(min_bytes=0).to_query()["total_bytes"] == {"$gte": 0}
        assert EventFilter(dst_port=0).to_query()["dst_port"] == 0
        assert EventFilter(protocol=0).to_query()["protocol"] == 0

    def test_none_values_are_omitted(self):
        query = EventFilter(src_device="Comp1", protocol=None, dst_port=None).to_query()
        assert query == {"src_device": "Comp1"}

    def test_combined_filters(self):
        query = EventFilter(
            src_device="Comp1", protocol=6, start_time=100, min_bytes=500
        ).to_query()
        assert set(query) == {"src_device", "protocol", "timestamp", "total_bytes"}


class TestFilterSemantics:
    """The query must select the same events an in-memory filter would."""

    def _matches(self, event: dict, query: dict) -> bool:
        """Minimal evaluator for the operators EventFilter emits."""
        for field, condition in query.items():
            if field == "$or":
                if not any(self._matches(event, clause) for clause in condition):
                    return False
            elif isinstance(condition, dict):
                value = event.get(field)
                if "$gte" in condition and value < condition["$gte"]:
                    return False
                if "$lte" in condition and value > condition["$lte"]:
                    return False
            elif event.get(field) != condition:
                return False
        return True

    @pytest.mark.parametrize(
        "kwargs,predicate",
        [
            ({"protocol": 17}, lambda e: e["protocol"] == 17),
            ({"dst_port": 443}, lambda e: e["dst_port"] == 443),
            ({"min_bytes": 10_000_000}, lambda e: e["total_bytes"] >= 10_000_000),
            ({"start_time": 1721000000}, lambda e: e["timestamp"] >= 1721000000),
            (
                {"start_time": 1721000000, "end_time": 1721500000},
                lambda e: 1721000000 <= e["timestamp"] <= 1721500000,
            ),
            ({"min_duration": 15000.0}, lambda e: e["duration"] >= 15000.0),
        ],
    )
    def test_query_selects_the_expected_events(self, events, kwargs, predicate):
        query = EventFilter(**kwargs).to_query()
        selected = {e["event_id"] for e in events if self._matches(e, query)}
        expected = {e["event_id"] for e in events if predicate(e)}
        assert selected == expected
        assert expected, "test filter should match at least one event"

    def test_device_filter_selects_both_directions(self, events):
        device = events[0]["src_device"]
        query = EventFilter(device=device).to_query()
        selected = {e["event_id"] for e in events if self._matches(e, query)}
        expected = {
            e["event_id"] for e in events
            if e["src_device"] == device or e["dst_device"] == device
        }
        assert selected == expected

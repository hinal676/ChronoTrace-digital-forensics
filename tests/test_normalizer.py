"""Tests for record normalization (spec 4, 5)."""

from __future__ import annotations

import pytest

from app.collector.normalizer import (
    CANONICAL_FIELDS,
    NormalizationError,
    make_event_id,
    normalize_event,
    normalize_many,
    parse_port,
    port_service,
    protocol_name,
)


class TestParsePort:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("Port62917", 62917),   # the dataset's SrcPort format
            ("port443", 443),
            ("Port_8080", 8080),
            ("  Port 22 ", 22),
            (443, 443),
            ("443", 443),
            (443.0, 443),
            (0, 0),
            (65535, 65535),
        ],
    )
    def test_accepts_labels_and_numbers(self, value, expected):
        assert parse_port(value) == expected

    @pytest.mark.parametrize("value", [None, "", "notaport", "Port", -1, 65536, True, float("nan")])
    def test_rejects_invalid(self, value):
        with pytest.raises(NormalizationError):
            parse_port(value)


class TestLookups:
    def test_known_protocols(self):
        assert protocol_name(6) == "TCP"
        assert protocol_name(17) == "UDP"
        assert protocol_name(1) == "ICMP"

    def test_unknown_protocol_falls_back(self):
        assert protocol_name(200) == "PROTO-200"

    def test_port_services(self):
        assert port_service(443) == "HTTPS"
        assert port_service(53) == "DNS"
        assert port_service(64999) is None


class TestNormalizeEvent:
    def test_maps_dataset_columns(self, sample_event):
        event = normalize_event(sample_event)
        assert event["timestamp"] == 1720001344
        assert event["src_device"] == "Comp679356"
        assert event["dst_device"] == "Comp654763"
        assert event["src_port"] == 62917       # "Port62917" -> int
        assert event["dst_port"] == 443
        assert event["protocol_name"] == "TCP"
        assert event["dst_service"] == "HTTPS"

    def test_accepts_canonical_names_too(self, sample_event):
        event = normalize_event(sample_event)
        # Feeding a normalized document back in must be a fixed point.
        again = normalize_event(event)
        assert again["event_id"] == event["event_id"]
        assert again["src_port"] == event["src_port"]

    def test_derived_features(self, sample_event):
        event = normalize_event(sample_event)
        assert event["total_packets"] == 4636 + 9480
        assert event["total_bytes"] == 3782976 + 6948840
        assert event["packet_ratio"] == pytest.approx(4636 / 9480, rel=1e-4)
        assert event["byte_ratio"] == pytest.approx(3782976 / 6948840, rel=1e-4)

    def test_epoch_converted_to_utc_datetime(self, sample_event):
        event = normalize_event(sample_event)
        assert event["event_time"].year == 2024
        assert event["event_time"].tzinfo is not None
        # The raw epoch is preserved alongside the derived timestamp (spec 4.1).
        assert event["timestamp"] == 1720001344

    def test_zero_denominator_ratios_stay_finite(self, sample_event):
        event = normalize_event({**sample_event, "DstPackets": "0", "DstBytes": "0"})
        assert event["packet_ratio"] == 4636.0
        assert event["byte_ratio"] == 3782976.0
        assert event["dst_bytes_per_packet"] == 0.0

    def test_zero_duration_does_not_divide_by_zero(self, sample_event):
        event = normalize_event({**sample_event, "Duration": "0"})
        assert event["bytes_per_second"] == float(event["total_bytes"])

    def test_output_uses_canonical_field_order(self, sample_event):
        event = normalize_event(sample_event)
        assert list(event) == [f for f in CANONICAL_FIELDS if f in event]

    @pytest.mark.parametrize(
        "missing",
        ["Time", "Duration", "SrcDevice", "DstDevice", "Protocol", "SrcPort", "DstPort",
         "SrcPackets", "DstPackets", "SrcBytes", "DstBytes"],
    )
    def test_missing_required_field_raises(self, sample_event, missing):
        broken = {k: v for k, v in sample_event.items() if k != missing}
        with pytest.raises(NormalizationError):
            normalize_event(broken)

    def test_negative_values_rejected(self, sample_event):
        with pytest.raises(NormalizationError):
            normalize_event({**sample_event, "SrcBytes": "-1"})

    def test_blank_device_rejected(self, sample_event):
        with pytest.raises(NormalizationError):
            normalize_event({**sample_event, "SrcDevice": "   "})

    def test_source_tag_recorded(self, sample_event):
        assert normalize_event(sample_event, source="collector")["source"] == "collector"


class TestEventId:
    def test_deterministic(self, sample_event):
        assert normalize_event(sample_event)["event_id"] == normalize_event(sample_event)["event_id"]

    def test_changes_with_content(self, sample_event):
        first = normalize_event(sample_event)["event_id"]
        second = normalize_event({**sample_event, "SrcBytes": "999"})["event_id"]
        assert first != second

    def test_explicit_id_preserved(self, sample_event):
        event = normalize_event({**sample_event, "event_id": "evt_custom"})
        assert event["event_id"] == "evt_custom"

    def test_id_derived_from_canonical_fields(self, sample_event):
        event = normalize_event(sample_event)
        assert event["event_id"] == make_event_id(event)


class TestNormalizeMany:
    def test_whole_dataset_normalizes(self, events):
        assert len(events) == 5000
        assert len({event["event_id"] for event in events}) == 5000

    def test_collects_bad_records(self, sample_event):
        good, bad = normalize_many([sample_event, {"Time": 1}, sample_event])
        assert len(good) == 2 and len(bad) == 1
        assert bad[0]["index"] == 1

    def test_strict_mode_raises(self, sample_event):
        with pytest.raises(NormalizationError):
            normalize_many([sample_event, {"Time": 1}], strict=True)

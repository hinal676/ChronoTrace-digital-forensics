"""Tests for the feature engineering and anomaly-detection layer (spec 11)."""

from __future__ import annotations

import numpy as np
import pytest

from app.ml.features import (
    FEATURE_COLUMNS,
    build_feature_frame,
    compute_device_profiles,
    profiles_from_json,
    profiles_to_json,
)
from app.ml.predict import score_events
from app.ml.train import train_model
from app.models.common import Classification


@pytest.fixture(scope="module")
def profiles(events):
    return compute_device_profiles(events)


@pytest.fixture(scope="module")
def trained(events):
    """Train on a subset -- fast, and independent of any model on disk."""
    pipeline, metadata = train_model(events[:2000], n_estimators=60, random_state=0)
    from app.ml.predict import RiskModel

    return RiskModel(pipeline, metadata)


class TestDeviceProfiles:
    def test_counts_match_events(self, events, profiles):
        assert sum(p["event_count"] for p in profiles.values()) == len(events)

    def test_unique_destinations(self, events, profiles):
        device = next(iter(profiles))
        expected = {e["dst_device"] for e in events if e["src_device"] == device}
        assert profiles[device]["unique_destinations"] == len(expected)

    def test_destination_only_devices_have_no_profile(self, events, profiles):
        """The five servers never initiate, so they never appear as a source."""
        assert "DNS" not in profiles

    def test_json_round_trip(self, profiles):
        restored = profiles_from_json(profiles_to_json(profiles))
        device = next(iter(profiles))
        assert restored[device]["event_count"] == profiles[device]["event_count"]
        assert restored[device]["destination_counts"] == profiles[device]["destination_counts"]


class TestFeatureFrame:
    def test_shape_and_columns(self, events):
        frame = build_feature_frame(events[:100])
        assert list(frame.columns) == list(FEATURE_COLUMNS)
        assert len(frame) == 100

    def test_indexed_by_event_id(self, events):
        frame = build_feature_frame(events[:10])
        assert list(frame.index) == [e["event_id"] for e in events[:10]]

    def test_no_nans_or_infinities(self, events):
        frame = build_feature_frame(events)
        assert not frame.isna().any().any()
        assert np.isfinite(frame.to_numpy(dtype=float)).all()

    def test_empty_input(self):
        assert build_feature_frame([]).empty

    def test_supplied_profiles_make_features_query_independent(self, events, profiles):
        """The same event must score identically alone and in a full batch.

        This is the reason profiles are persisted with the model rather than
        recomputed per request.
        """
        one = build_feature_frame([events[0]], profiles=profiles)
        many = build_feature_frame(events[:500], profiles=profiles)
        assert one.iloc[0].to_dict() == pytest.approx(many.iloc[0].to_dict())

    def test_unseen_device_falls_back_to_batch_stats(self, events, profiles):
        novel = {**events[0], "src_device": "BrandNewHost", "event_id": "evt_new"}
        frame = build_feature_frame([novel], profiles=profiles)
        assert len(frame) == 1
        assert frame.iloc[0]["device_event_count_log"] > 0

    def test_high_volume_event_has_larger_volume_features(self, events):
        biggest = max(events, key=lambda e: e["src_bytes"])
        typical = min(events, key=lambda e: e["src_bytes"])
        frame = build_feature_frame([biggest, typical])
        assert frame.iloc[0]["src_bytes_log"] > frame.iloc[1]["src_bytes_log"]


class TestTraining:
    def test_metadata_is_complete(self, trained):
        for key in ("model_version", "features", "score_quantiles", "feature_percentiles",
                    "thresholds", "device_profiles"):
            assert key in trained.metadata

    def test_refuses_tiny_corpus(self, events):
        with pytest.raises(ValueError):
            train_model(events[:10])

    def test_calibration_table_is_sorted(self, trained):
        assert np.all(np.diff(trained.quantiles) >= 0)


class TestScoring:
    def test_scores_are_bounded(self, events, trained):
        results = score_events(events[:300], model=trained)
        assert len(results) == 300
        assert all(0.0 <= r["risk_score"] <= 1.0 for r in results)

    def test_every_result_has_a_band_and_reasons(self, events, trained):
        for result in score_events(events[:100], model=trained):
            assert isinstance(result["classification"], Classification)
            assert result["reasons"]

    def test_empty_input(self, trained):
        assert score_events([], model=trained) == []

    def test_scoring_is_deterministic(self, events, trained):
        first = score_events(events[:50], model=trained)
        second = score_events(events[:50], model=trained)
        assert [r["risk_score"] for r in first] == [r["risk_score"] for r in second]

    def test_ranks_known_outliers_above_ordinary_traffic(self, events, trained):
        """The dataset carries no label, so the injected high-volume transfers
        (>100 MB outbound, ~1.4% of rows) serve as a pseudo ground truth."""
        results = score_events(events, model=trained)
        risks = np.array([r["risk_score"] for r in results])
        outlier = np.array([e["src_bytes"] > 1e8 for e in events])
        assert outlier.sum() > 0

        from sklearn.metrics import roc_auc_score

        assert roc_auc_score(outlier, risks) > 0.90
        # The worst offenders should surface near the top of the queue.
        top = np.argsort(-risks)[:200]
        assert outlier[top].sum() >= 0.7 * outlier.sum()

    def test_ordinary_traffic_is_not_mass_flagged(self, events, trained):
        """Absolute calibration: a clean slice must not fill the top bands.

        A percentile-rank score would force a fixed share of any batch into
        `high_priority`; this asserts the score is anchored to the training
        distribution instead.
        """
        clean = [e for e in events if e["src_bytes"] <= 1e8]
        results = score_events(clean, model=trained)
        flagged = sum(
            1 for r in results
            if r["classification"] in (Classification.REQUIRES_REVIEW, Classification.HIGH_PRIORITY)
        )
        assert flagged < 0.05 * len(clean)

    def test_reasons_explain_a_large_transfer(self, events, trained):
        biggest = max(events, key=lambda e: e["src_bytes"])
        result = score_events([biggest], model=trained)[0]
        assert result["risk_score"] > 0.5
        assert any("outbound" in reason.lower() or "volume" in reason.lower()
                   for reason in result["reasons"])
        assert result["contributing_features"]

    def test_no_response_traffic_is_reported(self, events, trained):
        silent = next((e for e in events if e["dst_packets"] == 0), None)
        if silent is None:
            pytest.skip("no zero-response events in the dataset")
        result = score_events([silent], model=trained)[0]
        assert any("No response traffic" in reason for reason in result["reasons"])

    def test_classification_bands_follow_thresholds(self, trained):
        assert trained.classify(0.95) is Classification.HIGH_PRIORITY
        assert trained.classify(0.80) is Classification.REQUIRES_REVIEW
        assert trained.classify(0.60) is Classification.LOW_CONCERN
        assert trained.classify(0.10) is Classification.NORMAL

    def test_risk_mapping_is_monotone(self, trained):
        """Higher isolation (lower raw score) must never mean lower risk."""
        raw = np.linspace(trained.quantiles[0] - 0.1, trained.quantiles[-1] + 0.1, 200)
        risks = trained.to_risk(raw)
        assert np.all(np.diff(risks) <= 1e-12)

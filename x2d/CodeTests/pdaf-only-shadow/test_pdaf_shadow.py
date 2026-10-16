import unittest

from pdaf_shadow import (Decision, FrameSample, Gate, Rect, Zone,
                         evaluate_shadow, evaluate_temporal_shadow)


ROI = Rect(0, 0, 10000, 10000)
GATE = Gate(min_zones=2, max_zones=512, min_confidence=500, min_coverage_permille=800,
            max_frame_lag=1, max_spread_steps=40, max_move_steps=300)


def zone(left, right, target, confidence=800, frame=10, direction=None):
    if direction is None:
        direction = (target > 500) - (target < 500)
    return Zone(Rect(left, 0, right, 10000), frame, confidence, target, direction)


def run(zones, **changes):
    args = dict(frame_id=10, current_steps=500, far_steps=0,
                near_steps=1000, gate=GATE)
    args.update(changes)
    return evaluate_shadow(zones, ROI, **args)


class PdafShadowTests(unittest.TestCase):
    def test_unequal_zones_use_geometry_not_array_index(self):
        result = run([zone(0, 6000, 700), zone(6000, 10000, 710)])
        self.assertEqual(result, Decision(True, "shadow_only", 700, 2, 1000))

    def test_sparse_coverage_falls_back(self):
        result = run([zone(0, 2000, 700), zone(2000, 4000, 710)])
        self.assertEqual(result.reason, "insufficient_roi_coverage")
        self.assertTrue(result.stock_path_required)
        self.assertIsNone(result.shadow_target_steps)

    def test_overlapping_regions_do_not_double_count_coverage(self):
        result = run([zone(0, 6000, 700), zone(2000, 6000, 710)])
        self.assertEqual(result.coverage_permille, 600)
        self.assertTrue(result.stock_path_required)

    def test_stale_frame_falls_back(self):
        self.assertEqual(run([zone(0, 5000, 700, frame=8),
                              zone(5000, 10000, 710)]).reason,
                         "stale_or_future_frame")

    def test_low_confidence_falls_back(self):
        self.assertEqual(run([zone(0, 5000, 700, confidence=100),
                              zone(5000, 10000, 710)]).reason,
                         "too_few_valid_zones")

    def test_disagreeing_targets_fall_back(self):
        self.assertEqual(run([zone(0, 5000, 600),
                              zone(5000, 10000, 800)]).reason,
                         "inconsistent_zone_targets")

    def test_lens_bounds_and_movement_gate(self):
        self.assertEqual(run([zone(0, 5000, 1100),
                              zone(5000, 10000, 1100)]).reason,
                         "target_outside_lens_limits")
        self.assertEqual(run([zone(0, 5000, 900),
                              zone(5000, 10000, 900)]).reason,
                         "movement_gate")

    def test_malformed_data_fails_closed(self):
        self.assertEqual(run([zone(0, 5000, 700),
                              Zone(Rect(5000, 0, 12000, 10000), 10, 800, 710, 1)]).reason,
                         "invalid_zone")
        self.assertEqual(run(None).reason, "missing_zones")
        self.assertEqual(run([zone(0, 5000, 700), zone(5000, 10000, 710)],
                             gate=Gate(1, 512, 500, 800, 1, 40, 300)).reason,
                         "invalid_limits_or_gate")
        self.assertEqual(run([zone(0, 5000, 700), zone(5000, 10000, 710)],
                             gate=Gate(2, 1, 500, 800, 1, 40, 300)).reason,
                         "invalid_limits_or_gate")

    def test_zone_count_is_bounded(self):
        self.assertEqual(run([zone(0, 5000, 700), zone(5000, 10000, 710),
                              zone(0, 10000, 705)],
                             gate=Gate(2, 2, 500, 800, 1, 40, 300)).reason,
                         "too_many_zones")

    def test_direction_requires_consensus_and_target_agreement(self):
        self.assertEqual(run([zone(0, 5000, 700),
                              zone(5000, 10000, 710, direction=-1)]).reason,
                         "inconsistent_zone_directions")
        self.assertEqual(run([zone(0, 5000, 700, direction=-1),
                              zone(5000, 10000, 710, direction=-1)]).reason,
                         "direction_target_mismatch")

    def test_observed_first_frame_drift_is_rejected_offline(self):
        # Values are transcribed from one stock far-focus log. These are NOT
        # real normalized Zone results; this tests only the temporal gate.
        first_three = [FrameSample(i, Decision(True, "shadow_only", target, 2, 900))
                       for i, target in enumerate((313, 293, 172), start=100)]
        self.assertEqual(evaluate_temporal_shadow(first_three, current_frame=102).reason,
                         "unstable_target_over_time")
        late_three = [FrameSample(i, Decision(True, "shadow_only", target, 2, 900))
                      for i, target in enumerate((90, 83, 78), start=200)]
        result = evaluate_temporal_shadow(late_three, current_frame=202)
        self.assertEqual(result.shadow_target_steps, 83)
        self.assertTrue(result.stock_path_required)

    def test_temporal_gate_rejects_gaps_and_prior_failure(self):
        valid = Decision(True, "shadow_only", 700, 2, 900)
        fallback = Decision(True, "too_few_valid_zones", None, 1, 200)
        self.assertEqual(evaluate_temporal_shadow(
            [FrameSample(1, valid), FrameSample(3, valid), FrameSample(4, valid)],
            current_frame=4).reason, "nonconsecutive_frames")
        self.assertEqual(evaluate_temporal_shadow(
            [FrameSample(1, valid), FrameSample(2, fallback), FrameSample(3, valid)],
            current_frame=3).reason, "unstable_or_rejected_frame")


if __name__ == "__main__":
    unittest.main()

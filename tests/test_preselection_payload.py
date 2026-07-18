import unittest

import numpy as np

from fs_sweep_app_spline import SweepSheet
from preselection_shortlist import (
    build_preselection_payload_safe,
    _compute_exact_peak_x_ranking,
    _compute_peak_x_ranking,
    _ranked_rows_payload,
)


class RankedPayloadTests(unittest.TestCase):
    def test_global_ranked_payload_uses_array_shape_and_score_order(self):
        payload = _ranked_rows_payload(
            [
                {"case_id": "A", "score": 2.0, "zmax": 20.0, "harmonic": 3},
                {"case_id": "B", "score": 4.0, "zmax": 10.0, "harmonic": 2},
            ],
            top_n_scope="global",
        )

        self.assertEqual(payload["top_n_scope"], "global")
        self.assertEqual(payload["case_ids"], ["B", "A"])
        self.assertEqual(payload["scores"], [4.0, 2.0])
        self.assertEqual(payload["harmonic"], [2, 3])

    def test_per_harmonic_payload_keeps_same_case_on_multiple_harmonics(self):
        payload = _ranked_rows_payload(
            [
                {"case_id": "A", "score": 2.0, "zmax": 20.0, "harmonic": 3},
                {"case_id": "A", "score": 5.0, "zmax": 50.0, "harmonic": 2},
            ],
            top_n_scope="per_harmonic",
        )

        self.assertEqual(payload["top_n_scope"], "per_harmonic")
        self.assertEqual(payload["case_ids"], ["A", "A"])
        self.assertEqual(payload["scores"], [5.0, 2.0])
        self.assertEqual(payload["harmonic"], [2, 3])

    def test_safe_payload_has_the_browser_compact_contract(self):
        freq = np.arange(0.0, 361.0, 1.0)
        cases = ("B__L", "A__L")
        r_vals = np.column_stack([np.ones_like(freq), np.full_like(freq, 2.0)])
        x_vals = np.column_stack([
            -np.exp(-np.square((freq - 180.0) / 20.0)) * 100.0,
            np.cos(freq / 40.0) * 20.0,
        ])
        payload = build_preselection_payload_safe(
            {
                "R1": SweepSheet(freq, cases, r_vals),
                "X1": SweepSheet(freq, cases, x_vals),
            },
            list(cases),
            fundamentals_hz=(60.0,),
            sequence_sheets=("R1", "X1"),
        )

        self.assertEqual(payload["format"], "compact_v6")
        node = payload["by_f1"]["60"]
        self.assertEqual(node["case_ids"], ["A__L", "B__L"])
        self.assertEqual(set(node), {
            "format", "case_ids", "energinet", "band_sample_counts", "iec_modes",
            "peak_z_modes", "peak_z_band_modes", "peak_x_modes", "peak_x_band_modes",
            "risk_modes", "outlier_modes",
        })
        for metric in ("z2", "z3", "z4", "f2", "f3", "f4"):
            self.assertEqual(len(node["energinet"][metric]), len(node["case_ids"]))
        for modes_name in (
            "peak_z_modes", "peak_z_band_modes", "peak_x_modes", "peak_x_band_modes",
            "risk_modes", "outlier_modes",
        ):
            for mode in ("all", "capacitive"):
                ranked = node[modes_name][mode]
                self.assertEqual(len(ranked["case_idx"]), len(ranked["scores"]))
                self.assertEqual(len(ranked["case_idx"]), len(ranked["zmax"]))
                self.assertEqual(len(ranked["case_idx"]), len(ranked["harmonic"]))
                self.assertTrue(all(0 <= idx < len(node["case_ids"]) for idx in ranked["case_idx"]))

    def test_peak_x_ranking_uses_harmonic_bands_and_capacitive_mode(self):
        x_map = {
            "A": np.asarray([1.0, -20.0, 4.0, -1.0]),
            "B": np.asarray([2.0, -5.0, -30.0, 3.0]),
            "C": np.asarray([50.0, 4.0, 2.0, 1.0]),
        }
        band_indices = {3: np.asarray([1, 2], dtype=int)}

        full = _compute_peak_x_ranking(x_map, ["A", "B", "C"], band_indices, capacitive_only=False)
        cap = _compute_peak_x_ranking(x_map, ["A", "B", "C"], band_indices, capacitive_only=True)

        self.assertEqual(full["top_n_scope"], "per_harmonic")
        self.assertEqual(full["case_ids"], ["B", "A", "C"])
        self.assertEqual(full["scores"], [30.0, 20.0, 4.0])
        self.assertEqual(cap["case_ids"], ["B", "A"])
        self.assertEqual(cap["scores"], [30.0, 20.0])

    def test_exact_peak_x_ranking_uses_harmonic_center_points(self):
        freq = np.asarray([60.0, 120.0, 180.0, 240.0, 300.0, 360.0])
        x_map = {
            "A": np.asarray([1.0, -20.0, -100.0, 1.0, 1.0, 1.0]),
            "B": np.asarray([1.0, -90.0, -80.0, 1.0, 1.0, 1.0]),
            "C": np.asarray([1.0, 10.0, 60.0, 1.0, 1.0, 1.0]),
        }

        full = _compute_exact_peak_x_ranking(freq, x_map, ["A", "B", "C"], 60.0, range(2, 7))
        cap = _compute_exact_peak_x_ranking(
            freq,
            x_map,
            ["A", "B", "C"],
            60.0,
            range(2, 7),
            capacitive_only=True,
        )

        self.assertEqual(full["top_n_scope"], "per_harmonic")
        self.assertEqual(full["case_ids"][:3], ["B", "A", "C"])
        self.assertEqual(full["harmonic"][:3], [2, 2, 2])
        self.assertEqual(cap["case_ids"][:4], ["B", "A", "A", "B"])
        self.assertEqual(cap["harmonic"][:4], [2, 2, 3, 3])

    def test_build_payload_includes_compact_peak_x_candidates(self):
        freq = np.arange(0.0, 361.0, 1.0)
        cases = ("A__L", "B__L", "C__L")
        r_vals = np.column_stack([
            np.ones_like(freq),
            np.full_like(freq, 2.0),
            np.full_like(freq, 3.0),
        ])
        x_vals = np.column_stack([
            np.sin(freq / 30.0) * 10.0,
            np.cos(freq / 40.0) * 20.0,
            -np.exp(-np.square((freq - 180.0) / 20.0)) * 100.0,
        ])
        data = {
            "R1": SweepSheet(freq, cases, r_vals),
            "X1": SweepSheet(freq, cases, x_vals),
            "R0": SweepSheet(freq, cases, r_vals),
            "X0": SweepSheet(freq, cases, x_vals),
        }

        payload = build_preselection_payload_safe(
            data,
            list(cases),
            fundamentals_hz=(60.0,),
            sequence_sheets=("R1", "X1"),
        )
        node = payload["by_f1"]["60"]

        self.assertGreater(len(node["peak_x_modes"]["all"]["case_idx"]), 0)
        self.assertGreater(len(node["peak_x_modes"]["capacitive"]["case_idx"]), 0)
        self.assertGreater(len(node["peak_x_band_modes"]["all"]["case_idx"]), 0)
        self.assertGreater(len(node["peak_x_band_modes"]["capacitive"]["case_idx"]), 0)
        self.assertGreater(len(node["peak_z_modes"]["all"]["case_idx"]), 0)
        self.assertGreater(len(node["peak_z_band_modes"]["all"]["case_idx"]), 0)

    def test_preselection_supports_a_single_active_sequence_pair(self):
        freq = np.arange(0.0, 361.0, 1.0)
        cases = ("A__L", "B__L")
        r_vals = np.column_stack([np.ones_like(freq), np.full_like(freq, 2.0)])
        x_vals = np.column_stack([
            -np.exp(-np.square((freq - 180.0) / 20.0)) * 100.0,
            np.cos(freq / 40.0) * 20.0,
        ])
        data = {
            "R1": SweepSheet(freq, cases, r_vals),
            "X1": SweepSheet(freq, cases, x_vals),
        }

        payload = build_preselection_payload_safe(
            data,
            list(cases),
            fundamentals_hz=(60.0,),
            sequence_sheets=("R1", "X1"),
        )

        self.assertTrue(payload["available"])
        self.assertIn("60", payload["by_f1"])


if __name__ == "__main__":
    unittest.main()

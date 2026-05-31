import unittest

import numpy as np

from fs_sweep_app_spline import SweepSheet, _compact_preselection_payload
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

    def test_compact_payload_accepts_ranked_array_shape(self):
        ranked = _ranked_rows_payload(
            [{"case_id": "B", "score": 4.0, "zmax": 10.0, "harmonic": 2}],
            top_n_scope="global",
        )
        compact = _compact_preselection_payload(
            {
                "available": True,
                "cases_count": 1,
                "by_f1": {
                    "50": {
                        "energinet_metrics": {},
                        "band_sample_counts": {"2": 3},
                        "iec_modes": {
                            "all": {
                                "iec_case_ids": ["B"],
                                "iec_vertex_orders": {"B": [2, 4]},
                                "iec_vertex_zmax": {"B": {"2": 10.0, "4": 40.0}},
                                "n_env": 6,
                            },
                            "capacitive": {
                                "iec_case_ids": [],
                                "iec_vertex_orders": {},
                                "iec_vertex_zmax": {},
                                "n_env": 6,
                            },
                        },
                        "peak_z_modes": {"all": ranked, "capacitive": ranked},
                        "peak_z_band_modes": {"all": ranked, "capacitive": ranked},
                        "peak_x_modes": {"all": ranked, "capacitive": ranked},
                        "peak_x_band_modes": {"all": ranked, "capacitive": ranked},
                        "risk_modes": {"all": ranked, "capacitive": ranked},
                        "outlier_modes": {"all": ranked, "capacitive": ranked},
                    }
                },
            }
        )

        node = compact["by_f1"]["50"]
        self.assertEqual(compact["format"], "compact_v6")
        self.assertEqual(node["case_ids"], ["B"])
        self.assertEqual(node["iec_modes"]["all"]["case_idx"], [0])
        self.assertEqual(node["iec_modes"]["all"]["vertex_orders"], [[2, 4]])
        self.assertEqual(node["iec_modes"]["all"]["vertex_zmax"], [[10.0, 40.0]])
        self.assertEqual(node["iec_modes"]["all"]["top_n_scope"], "per_harmonic")
        self.assertEqual(node["risk_modes"]["all"]["case_idx"], [0])
        self.assertEqual(node["risk_modes"]["all"]["scores"], [4.0])
        self.assertEqual(node["peak_z_band_modes"]["all"]["case_idx"], [0])
        self.assertEqual(node["peak_x_band_modes"]["all"]["case_idx"], [0])

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

        raw = build_preselection_payload_safe(
            data,
            list(cases),
            fundamentals_hz=(60.0,),
            sequence_sheets=("R1", "X1"),
        )
        compact = _compact_preselection_payload(raw)
        node = compact["by_f1"]["60"]

        self.assertGreater(len(node["peak_x_modes"]["all"]["case_idx"]), 0)
        self.assertGreater(len(node["peak_x_modes"]["capacitive"]["case_idx"]), 0)
        self.assertGreater(len(node["peak_x_band_modes"]["all"]["case_idx"]), 0)
        self.assertGreater(len(node["peak_x_band_modes"]["capacitive"]["case_idx"]), 0)
        self.assertGreater(len(node["peak_z_modes"]["all"]["case_idx"]), 0)
        self.assertGreater(len(node["peak_z_band_modes"]["all"]["case_idx"]), 0)


if __name__ == "__main__":
    unittest.main()

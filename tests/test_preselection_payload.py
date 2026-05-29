import unittest

from fs_sweep_app_spline import _compact_preselection_payload
from preselection_shortlist import _ranked_rows_payload


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
                        "risk_modes": {"all": ranked, "capacitive": ranked},
                        "outlier_modes": {"all": ranked, "capacitive": ranked},
                    }
                },
            }
        )

        node = compact["by_f1"]["50"]
        self.assertEqual(compact["format"], "compact_v3")
        self.assertEqual(node["case_ids"], ["B"])
        self.assertEqual(node["iec_modes"]["all"]["case_idx"], [0])
        self.assertEqual(node["iec_modes"]["all"]["vertex_orders"], [[2, 4]])
        self.assertEqual(node["iec_modes"]["all"]["vertex_zmax"], [[10.0, 40.0]])
        self.assertEqual(node["iec_modes"]["all"]["top_n_scope"], "per_harmonic")
        self.assertEqual(node["risk_modes"]["all"]["case_idx"], [0])
        self.assertEqual(node["risk_modes"]["all"]["scores"], [4.0])


if __name__ == "__main__":
    unittest.main()

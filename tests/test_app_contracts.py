import os
import tempfile
import unittest

import numpy as np
import pandas as pd

from fs_sweep_app_spline import (
    SweepSheet,
    _local_workbook_cache_stamp,
    build_rx_scatter_animated,
    load_fs_sweep_xlsx_cached,
)
from preselection_shortlist import _compute_harmonic_max_points, _sheet_metadata


class AppContractTests(unittest.TestCase):
    def test_sheet_metadata_keeps_the_compact_value_matrix(self):
        sheet = SweepSheet(
            frequency_hz=np.asarray([50.0, 100.0]),
            case_ids=("A",),
            values=np.asarray([[1.0], [2.0]], dtype=np.float32),
        )

        _freq, _case_ids, values = _sheet_metadata(sheet, "R1")

        self.assertIs(values, sheet.values)
        self.assertEqual(values.dtype, np.float32)

    def test_harmonic_points_accept_reused_band_indices(self):
        freq = np.asarray([100.0, 110.0, 120.0, 150.0])
        r_map = {"A": np.asarray([1.0, 2.0, 3.0, 4.0])}
        x_map = {"A": np.asarray([-2.0, -3.0, -4.0, 5.0])}

        band_indices, _all_points = _compute_harmonic_max_points(
            freq, r_map, x_map, ["A"], 50.0, range(2, 4)
        )
        _fresh_bands, fresh_capacitive = _compute_harmonic_max_points(
            freq, r_map, x_map, ["A"], 50.0, range(2, 4), capacitive_only=True
        )
        reused_bands, reused_capacitive = _compute_harmonic_max_points(
            freq,
            r_map,
            x_map,
            ["A"],
            50.0,
            range(2, 4),
            capacitive_only=True,
            band_indices=band_indices,
        )

        self.assertEqual(set(reused_bands), set(band_indices))
        self.assertEqual(reused_capacitive, fresh_capacitive)

    def test_scatter_metadata_matches_slider_trace_contract(self):
        freq = np.asarray([50.0, 100.0, 150.0])
        r_sheet = SweepSheet(freq, ("A", "B"), np.asarray([[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]]))
        x_sheet = SweepSheet(freq, ("A", "B"), np.asarray([[-1.0, -4.0], [-2.0, -5.0], [-3.0, -6.0]]))

        fig, step_count = build_rx_scatter_animated(
            r_sheet,
            x_sheet,
            ["A", "B"],
            "Positive",
            {"A": "#000000", "B": "#ffffff"},
            plot_height=400,
            use_auto_width=False,
            figure_width_px=1000,
        )

        contract = fig.layout.meta["rx_single_trace"]
        self.assertEqual(step_count, 3)
        self.assertEqual(contract["freq_hz"], [50.0, 100.0, 150.0])
        self.assertEqual(contract["point_count"], 2)
        self.assertEqual(len(contract["x_flat"]), step_count * contract["point_count"])
        self.assertEqual(len(contract["y_flat"]), step_count * contract["point_count"])
        self.assertEqual(len(fig.data[0].x), contract["point_count"])
        self.assertLessEqual(fig.layout.xaxis.range[0], 1.0)
        self.assertGreaterEqual(fig.layout.xaxis.range[1], 6.0)

    def test_cached_loader_refreshes_when_the_local_workbook_stamp_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "sweep.xlsx")
            self._write_workbook(path, 1.0)
            load_fs_sweep_xlsx_cached.clear()
            first_stamp = _local_workbook_cache_stamp(path)
            first = load_fs_sweep_xlsx_cached(path, first_stamp)

            self._write_workbook(path, 9.0)
            second_stat = os.stat(path)
            next_mtime_ns = max(second_stat.st_mtime_ns + 1, first_stamp[0] + 1)
            os.utime(path, ns=(next_mtime_ns, next_mtime_ns))
            second_stamp = _local_workbook_cache_stamp(path)
            second = load_fs_sweep_xlsx_cached(path, second_stamp)

            self.assertNotEqual(first_stamp, second_stamp)
            self.assertEqual(float(first["R1"].values[0, 0]), 1.0)
            self.assertEqual(float(second["R1"].values[0, 0]), 9.0)
            load_fs_sweep_xlsx_cached.clear()

    @staticmethod
    def _write_workbook(path, value):
        frame = pd.DataFrame({"Frequency (Hz)": [50.0, 100.0], "A": [value, value + 1.0]})
        with pd.ExcelWriter(path) as writer:
            frame.to_excel(writer, sheet_name="R1", index=False)
            frame.to_excel(writer, sheet_name="X1", index=False)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

REQUIRED_SHEETS: Tuple[str, str, str, str] = ("R1", "X1", "R0", "X0")
ENERGINET_DEFAULT_THRESHOLDS_BY_F1: Dict[int, Dict[int, float]] = {
    50: {2: 400.0, 3: 600.0, 4: 2400.0},
    60: {2: 450.0, 3: 800.0, 4: 3000.0},
}
# Backward-compatible alias for existing imports (50 Hz defaults).
ENERGINET_DEFAULT_THRESHOLDS: Dict[int, float] = dict(ENERGINET_DEFAULT_THRESHOLDS_BY_F1[50])
BAND_HALF_WIDTH_FACTOR = 0.2

LIMITATION_NOTE = (
    "Low-order resonance / TOV screening only (f1-relative up to the available sweep range). "
    "Not defensible for kHz switching-overvoltage ranking from 6th-harmonic-limited sweeps."
)


def default_energinet_thresholds_for_f1(f1_hz: float) -> Dict[int, float]:
    key = int(round(float(f1_hz)))
    if key not in ENERGINET_DEFAULT_THRESHOLDS_BY_F1:
        key = 50
    return dict(ENERGINET_DEFAULT_THRESHOLDS_BY_F1[key])


def _sheet_arrays_payload(sheet: Any, sheet_name: str) -> Optional[Tuple[np.ndarray, List[str], np.ndarray]]:
    if sheet is None:
        return None
    has_attrs = (
        hasattr(sheet, "frequency_hz")
        and hasattr(sheet, "case_ids")
        and hasattr(sheet, "values")
    )
    if not has_attrs:
        return None
    freq = np.asarray(getattr(sheet, "frequency_hz"), dtype=float)
    case_ids = [str(v) for v in tuple(getattr(sheet, "case_ids"))]
    values = np.asarray(getattr(sheet, "values"), dtype=float)
    if values.ndim != 2:
        raise ValueError(f"Sheet '{sheet_name}' values must be a 2-D matrix.")
    if values.shape[0] != freq.shape[0]:
        raise ValueError(f"Sheet '{sheet_name}' frequency/value row mismatch.")
    if values.shape[1] != len(case_ids):
        raise ValueError(f"Sheet '{sheet_name}' case/value column mismatch.")
    return freq, case_ids, values


def _sheet_case_columns(df: Any, sheet_name: str = "") -> List[str]:
    payload = _sheet_arrays_payload(df, sheet_name)
    if payload is not None:
        _freq, case_ids, _values = payload
        return [str(c) for c in case_ids]
    raise ValueError(f"Unsupported sheet type for '{sheet_name}'.")


def _frequency_vector(df: Any, sheet_name: str) -> np.ndarray:
    payload = _sheet_arrays_payload(df, sheet_name)
    if payload is not None:
        freq = np.asarray(payload[0], dtype=float)
        if freq.size == 0:
            raise ValueError(f"Sheet '{sheet_name}' has empty frequency column.")
        if not np.all(np.isfinite(freq)):
            raise ValueError(f"Sheet '{sheet_name}' has non-numeric frequency values.")
        return freq
    raise ValueError(f"Unsupported sheet type for '{sheet_name}'.")


def _validate_input_tables(data: Dict[str, Any]) -> Tuple[np.ndarray, List[str], Dict[str, np.ndarray]]:
    missing = [s for s in REQUIRED_SHEETS if s not in data or data[s] is None]
    if missing:
        raise ValueError(f"Missing required sheets: {', '.join(missing)}.")

    row_orders: Dict[str, np.ndarray] = {}
    ref_freq_sorted: Optional[np.ndarray] = None
    ref_cases: Optional[List[str]] = None

    for name in REQUIRED_SHEETS:
        df = data[name]
        freq = _frequency_vector(df, name)
        order = np.argsort(freq, kind="mergesort")
        freq_sorted = freq[order]
        if np.unique(freq_sorted).size != freq_sorted.size:
            raise ValueError(f"Sheet '{name}' has duplicated frequency values; deterministic band selection requires unique frequencies.")
        cases = _sheet_case_columns(df, name)
        if not cases:
            raise ValueError("No case columns found in required sheets.")

        row_orders[name] = order
        if ref_freq_sorted is None:
            ref_freq_sorted = freq_sorted
            ref_cases = list(cases)
            continue
        if freq_sorted.shape != ref_freq_sorted.shape or not np.allclose(freq_sorted, ref_freq_sorted, rtol=0.0, atol=1e-9):
            raise ValueError("Frequency column mismatch across required sheets (after sorting by frequency).")
        if list(cases) != list(ref_cases):
            raise ValueError("Case columns mismatch across required sheets.")

    if ref_freq_sorted is None or ref_cases is None:
        raise ValueError("Unable to validate required sheets.")
    return ref_freq_sorted, list(ref_cases), row_orders


def _extract_case_arrays(
    df: Any,
    cases: Sequence[str],
    sheet_name: str,
    row_order: Optional[np.ndarray] = None,
) -> Dict[str, np.ndarray]:
    out: Dict[str, np.ndarray] = {}
    payload = _sheet_arrays_payload(df, sheet_name)
    if payload is not None:
        _freq, case_ids, values = payload
        index_by_case = {str(cid): i for i, cid in enumerate(case_ids)}
        for case in cases:
            cid = str(case)
            if cid not in index_by_case:
                raise ValueError(f"Case '{case}' not found in sheet '{sheet_name}'.")
            arr = np.asarray(values[:, int(index_by_case[cid])], dtype=float)
            if row_order is not None:
                if arr.shape[0] != row_order.shape[0]:
                    raise ValueError(f"Row-count mismatch while sorting case '{case}' in sheet '{sheet_name}'.")
                arr = arr[row_order]
            out[cid] = arr
        return out

    raise ValueError(f"Unsupported sheet type for '{sheet_name}'.")


def _band_indices(freq: np.ndarray, center_hz: float, half_width_hz: float) -> np.ndarray:
    lo = float(center_hz) - float(half_width_hz)
    hi = float(center_hz) + float(half_width_hz)
    return np.where((freq >= lo) & (freq <= hi))[0]


def _max_mag_index_in_band(
    r_arr: np.ndarray,
    x_arr: np.ndarray,
    freq: np.ndarray,
    band_idx: np.ndarray,
) -> Optional[int]:
    if band_idx.size == 0:
        return None
    r = r_arr[band_idx]
    x = x_arr[band_idx]
    mags = np.sqrt(np.square(r) + np.square(x))
    valid = np.isfinite(mags)
    if not np.any(valid):
        return None
    valid_local = np.where(valid)[0]
    valid_mags = mags[valid_local]
    max_mag = float(np.nanmax(valid_mags))
    tol = 1e-12 * max(1.0, abs(max_mag))
    max_local = valid_local[np.where(np.isclose(valid_mags, max_mag, rtol=0.0, atol=tol))[0]]
    if max_local.size == 0:
        max_local = valid_local[np.where(valid_mags == max_mag)[0]]
    if max_local.size == 0:
        return None
    global_candidates = band_idx[max_local]
    if global_candidates.size == 1:
        return int(global_candidates[0])
    f_candidates = freq[global_candidates]
    return int(global_candidates[int(np.argmin(f_candidates))])


def _compute_harmonic_max_points(
    freq: np.ndarray,
    r_map: Dict[str, np.ndarray],
    x_map: Dict[str, np.ndarray],
    cases: Sequence[str],
    f1_hz: float,
    n_values: Sequence[int],
) -> Tuple[Dict[int, np.ndarray], Dict[int, Dict[str, Dict[str, float]]]]:
    band_half = BAND_HALF_WIDTH_FACTOR * float(f1_hz)
    unique_n = sorted({int(n) for n in n_values if int(n) >= 1})
    band_indices = {int(n): _band_indices(freq, float(n) * float(f1_hz), band_half) for n in unique_n}
    points_by_n: Dict[int, Dict[str, Dict[str, float]]] = {int(n): {} for n in unique_n}

    for n in unique_n:
        b_idx = band_indices[n]
        if b_idx.size == 0:
            continue
        for case in cases:
            case_id = str(case)
            idx_star = _max_mag_index_in_band(r_map[case_id], x_map[case_id], freq, b_idx)
            if idx_star is None:
                continue
            r_val = float(r_map[case_id][idx_star])
            x_val = float(x_map[case_id][idx_star])
            if not np.isfinite(r_val) or not np.isfinite(x_val):
                continue
            zmax = float(np.sqrt(r_val ** 2 + x_val ** 2))
            points_by_n[n][case_id] = {
                "idx": float(idx_star),
                "r": r_val,
                "x": x_val,
                "zmax": zmax,
                "freq": float(freq[idx_star]),
            }

    return band_indices, points_by_n


def _cross(o: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _convex_hull(points: Iterable[Tuple[float, float]]) -> List[Tuple[float, float]]:
    pts = sorted(set((float(p[0]), float(p[1])) for p in points))
    if len(pts) <= 1:
        return pts

    lower: List[Tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: List[Tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def _compute_energinet_metrics(
    freq: np.ndarray,
    r_map: Dict[str, np.ndarray],
    x_map: Dict[str, np.ndarray],
    cases: Sequence[str],
    f1_hz: float,
    band_indices: Optional[Dict[int, np.ndarray]] = None,
    harmonic_points: Optional[Dict[int, Dict[str, Dict[str, float]]]] = None,
) -> Dict[str, object]:
    if band_indices is None or harmonic_points is None:
        band_indices, harmonic_points = _compute_harmonic_max_points(freq, r_map, x_map, cases, f1_hz, (2, 3, 4))

    metrics_by_case: Dict[str, Dict[str, Optional[float]]] = {}
    for case in cases:
        case_id = str(case)
        row: Dict[str, Optional[float]] = {}
        for n in (2, 3, 4):
            point = harmonic_points.get(int(n), {}).get(case_id)
            if point is None:
                row[f"zmax_band_{n}"] = None
                row[f"f_at_zmax_band_{n}"] = None
            else:
                zmax = float(point["zmax"])
                row[f"zmax_band_{n}"] = zmax if np.isfinite(zmax) else None
                row[f"f_at_zmax_band_{n}"] = float(point["freq"])
        metrics_by_case[case_id] = row

    return {
        "energinet_metrics": metrics_by_case,
        "band_sample_counts": {str(n): int(band_indices.get(n, np.asarray([], dtype=int)).size) for n in (2, 3, 4)},
    }


def _compute_iec_vertices(
    freq: np.ndarray,
    r_map: Dict[str, np.ndarray],
    x_map: Dict[str, np.ndarray],
    cases: Sequence[str],
    f1_hz: float,
    capacitive_only: bool = False,
    band_indices: Optional[Dict[int, np.ndarray]] = None,
    harmonic_points: Optional[Dict[int, Dict[str, Dict[str, float]]]] = None,
) -> Dict[str, object]:
    freq_max = float(np.nanmax(freq))
    n_env = int(min(6, np.floor(freq_max / float(f1_hz))))
    if n_env < 2:
        return {
            "iec_case_ids": [],
            "iec_first_harmonic": {},
            "iec_vertex_orders": {},
            "n_env": int(max(0, n_env)),
        }

    vertex_orders: Dict[str, List[int]] = {str(c): [] for c in cases}
    if harmonic_points is None:
        band_indices, harmonic_points = _compute_harmonic_max_points(
            freq,
            r_map,
            x_map,
            cases,
            f1_hz,
            range(2, n_env + 1),
        )
    if band_indices is None:
        band_half = BAND_HALF_WIDTH_FACTOR * float(f1_hz)
        band_indices = {n: _band_indices(freq, float(n) * float(f1_hz), band_half) for n in range(2, n_env + 1)}

    for n in range(2, n_env + 1):
        b_idx = band_indices.get(int(n), np.asarray([], dtype=int))
        if b_idx.size == 0:
            continue

        case_points: Dict[str, Tuple[float, float]] = {}
        point_to_cases: Dict[Tuple[float, float], List[str]] = {}
        for case_id, point in harmonic_points.get(int(n), {}).items():
            r_val = float(point["r"])
            x_val = float(point["x"])
            if bool(capacitive_only) and x_val >= 0.0:
                continue
            p = (r_val, x_val)
            case_points[case_id] = p
            point_to_cases.setdefault(p, []).append(case_id)

        if not case_points:
            continue

        unique_points = sorted(point_to_cases.keys(), key=lambda p: (p[0], p[1]))
        selected_points: List[Tuple[float, float]] = []
        if len(unique_points) < 3:
            selected_points = list(unique_points)
        else:
            hull_pts = _convex_hull(unique_points)
            selected_points = list(hull_pts)

        selected: List[str] = []
        for sp in selected_points:
            selected.extend(point_to_cases.get(sp, []))
        selected_cases = sorted(set(selected))

        for case_id in selected_cases:
            vertex_orders.setdefault(case_id, []).append(int(n))

    vertex_orders_clean = {
        str(case_id): sorted(set(int(v) for v in h_list))
        for case_id, h_list in vertex_orders.items()
        if h_list
    }
    first_harmonic = {
        str(case_id): int(min(h_list))
        for case_id, h_list in vertex_orders_clean.items()
    }
    selected_case_ids = sorted(first_harmonic.keys())
    return {
        "iec_case_ids": selected_case_ids,
        "iec_first_harmonic": first_harmonic,
        "iec_vertex_orders": vertex_orders_clean,
        "n_env": int(n_env),
    }


def build_preselection_payload(
    data: Dict[str, Any],
    cases: Sequence[str],
    fundamentals_hz: Sequence[float] = (50.0, 60.0),
    sequence_sheets: Tuple[str, str] = ("R1", "X1"),
) -> Dict[str, object]:
    freq, all_case_ids, row_orders = _validate_input_tables(data)
    r_sheet, x_sheet = str(sequence_sheets[0]), str(sequence_sheets[1])
    if r_sheet not in data or x_sheet not in data:
        raise ValueError(f"Missing required sequence sheets for preselection: {r_sheet}/{x_sheet}.")
    all_case_set = set(str(c) for c in all_case_ids)

    chosen_cases: List[str] = []
    seen: set[str] = set()
    for case in cases:
        case_id = str(case)
        if case_id in all_case_set and case_id not in seen:
            chosen_cases.append(case_id)
            seen.add(case_id)
    if not chosen_cases:
        raise ValueError("No selected-location cases are available in validated sheets.")

    r_map = _extract_case_arrays(data[r_sheet], chosen_cases, r_sheet, row_order=row_orders.get(r_sheet))
    x_map = _extract_case_arrays(data[x_sheet], chosen_cases, x_sheet, row_order=row_orders.get(x_sheet))

    by_f1: Dict[str, Dict[str, object]] = {}
    for f1 in fundamentals_hz:
        f1_val = float(f1)
        if f1_val not in (50.0, 60.0):
            raise ValueError(f"Unsupported fundamental frequency in configuration: {f1_val}.")
        f1_key = str(int(round(f1_val)))
        freq_max = float(np.nanmax(freq))
        n_env = int(min(6, np.floor(freq_max / float(f1_val)))) if np.isfinite(freq_max) and f1_val > 0 else 0
        max_n = int(max(4, n_env))
        band_indices, harmonic_points = _compute_harmonic_max_points(
            freq,
            r_map,
            x_map,
            chosen_cases,
            f1_val,
            range(2, max_n + 1),
        )
        energinet = _compute_energinet_metrics(
            freq,
            r_map,
            x_map,
            chosen_cases,
            f1_val,
            band_indices=band_indices,
            harmonic_points=harmonic_points,
        )
        iec_all = _compute_iec_vertices(
            freq,
            r_map,
            x_map,
            chosen_cases,
            f1_val,
            capacitive_only=False,
            band_indices=band_indices,
            harmonic_points=harmonic_points,
        )
        iec_capacitive = _compute_iec_vertices(
            freq,
            r_map,
            x_map,
            chosen_cases,
            f1_val,
            capacitive_only=True,
            band_indices=band_indices,
            harmonic_points=harmonic_points,
        )
        by_f1[f1_key] = {
            "energinet_metrics": dict(energinet["energinet_metrics"]),
            "band_sample_counts": dict(energinet["band_sample_counts"]),
            "iec_modes": {
                "all": {
                    "iec_case_ids": list(iec_all["iec_case_ids"]),
                    "iec_first_harmonic": dict(iec_all["iec_first_harmonic"]),
                    "iec_vertex_orders": dict(iec_all["iec_vertex_orders"]),
                    "n_env": int(iec_all["n_env"]),
                },
                "capacitive": {
                    "iec_case_ids": list(iec_capacitive["iec_case_ids"]),
                    "iec_first_harmonic": dict(iec_capacitive["iec_first_harmonic"]),
                    "iec_vertex_orders": dict(iec_capacitive["iec_vertex_orders"]),
                    "n_env": int(iec_capacitive["n_env"]),
                },
            },
        }

    return {
        "available": True,
        "error": "",
        "limitation_note": str(LIMITATION_NOTE),
        "cases_count": int(len(chosen_cases)),
        "by_f1": by_f1,
    }


def build_preselection_payload_safe(
    data: Dict[str, Any],
    cases: Sequence[str],
    fundamentals_hz: Sequence[float] = (50.0, 60.0),
    sequence_sheets: Tuple[str, str] = ("R1", "X1"),
) -> Dict[str, object]:
    try:
        return build_preselection_payload(
            data,
            cases,
            fundamentals_hz=fundamentals_hz,
            sequence_sheets=sequence_sheets,
        )
    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
            "limitation_note": str(LIMITATION_NOTE),
            "cases_count": int(len(cases)),
            "by_f1": {},
        }

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
RANKED_METHOD_N_MIN = 2
RANKED_METHOD_N_MAX = 6
OUTLIER_MAD_Z_THRESHOLD = 3.5
OUTLIER_PERCENTILE_FALLBACK = 95.0

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


def _nearest_index(freq: np.ndarray, target_hz: float) -> Optional[int]:
    freq_arr = np.asarray(freq, dtype=float)
    if freq_arr.size == 0:
        return None
    pos = int(np.searchsorted(freq_arr, float(target_hz), side="left"))
    if pos <= 0:
        return 0
    if pos >= freq_arr.size:
        return int(freq_arr.size - 1)
    left = float(freq_arr[pos - 1])
    right = float(freq_arr[pos])
    return int(pos - 1 if abs(float(target_hz) - left) <= abs(right - float(target_hz)) else pos)


def _max_mag_index_in_band(
    r_arr: np.ndarray,
    x_arr: np.ndarray,
    freq: np.ndarray,
    band_idx: np.ndarray,
    capacitive_only: bool = False,
) -> Optional[int]:
    if band_idx.size == 0:
        return None
    r = r_arr[band_idx]
    x = x_arr[band_idx]
    mags = np.sqrt(np.square(r) + np.square(x))
    valid = np.isfinite(mags)
    if bool(capacitive_only):
        valid = valid & np.isfinite(x) & (x < 0.0)
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
    capacitive_only: bool = False,
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
            idx_star = _max_mag_index_in_band(
                r_map[case_id],
                x_map[case_id],
                freq,
                b_idx,
                capacitive_only=bool(capacitive_only),
            )
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
            "iec_vertex_zmax": {},
            "n_env": int(max(0, n_env)),
        }

    vertex_orders: Dict[str, List[int]] = {str(c): [] for c in cases}
    vertex_zmax: Dict[str, Dict[str, float]] = {str(c): {} for c in cases}
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
            point = harmonic_points.get(int(n), {}).get(case_id, {})
            zmax = float(point.get("zmax", np.nan)) if isinstance(point, dict) else np.nan
            if np.isfinite(zmax):
                vertex_zmax.setdefault(case_id, {})[str(int(n))] = float(zmax)

    vertex_orders_clean = {
        str(case_id): sorted(set(int(v) for v in h_list))
        for case_id, h_list in vertex_orders.items()
        if h_list
    }
    first_harmonic = {
        str(case_id): int(min(h_list))
        for case_id, h_list in vertex_orders_clean.items()
    }
    vertex_zmax_clean: Dict[str, Dict[str, float]] = {}
    for case_id, h_list in vertex_orders_clean.items():
        z_src = vertex_zmax.get(str(case_id), {})
        z_out: Dict[str, float] = {}
        for n in h_list:
            try:
                z_val = float(z_src.get(str(int(n)), np.nan))
            except Exception:
                continue
            if np.isfinite(z_val):
                z_out[str(int(n))] = float(z_val)
        vertex_zmax_clean[str(case_id)] = z_out
    selected_case_ids = sorted(first_harmonic.keys())
    return {
        "iec_case_ids": selected_case_ids,
        "iec_first_harmonic": first_harmonic,
        "iec_vertex_orders": vertex_orders_clean,
        "iec_vertex_zmax": vertex_zmax_clean,
        "n_env": int(n_env),
    }


def _ranked_rows_payload(rows: Sequence[Dict[str, object]], top_n_scope: str = "global") -> Dict[str, object]:
    scope = "per_harmonic" if str(top_n_scope) == "per_harmonic" else "global"
    clean_rows: List[Dict[str, object]] = []
    seen: set[object] = set()
    for row in rows:
        cid = str(row.get("case_id", ""))
        score = float(row.get("score", 0.0))
        zmax = float(row.get("zmax", 0.0))
        harmonic = int(row.get("harmonic", 0))
        if not cid or harmonic < 1 or not np.isfinite(score):
            continue
        key: object = (cid, harmonic) if scope == "per_harmonic" else cid
        if key in seen:
            continue
        seen.add(key)
        clean_rows.append(
            {
                "case_id": cid,
                "score": float(score),
                "zmax": float(zmax) if np.isfinite(zmax) else 0.0,
                "harmonic": int(harmonic),
            }
        )
    if scope == "per_harmonic":
        clean_rows.sort(
            key=lambda r: (
                int(r["harmonic"]),
                -float(r["score"]),
                -float(r["zmax"]),
                str(r["case_id"]),
            )
        )
    else:
        clean_rows.sort(
            key=lambda r: (
                -float(r["score"]),
                -float(r["zmax"]),
                int(r["harmonic"]),
                str(r["case_id"]),
            )
        )
    return {
        "case_ids": [str(r["case_id"]) for r in clean_rows],
        "scores": [float(r["score"]) for r in clean_rows],
        "zmax": [float(r["zmax"]) for r in clean_rows],
        "harmonic": [int(r["harmonic"]) for r in clean_rows],
        "top_n_scope": scope,
    }


def _compute_peak_z_ranking(
    harmonic_points: Dict[int, Dict[str, Dict[str, float]]],
    cases: Sequence[str],
) -> Dict[str, object]:
    case_set = {str(c) for c in cases}
    rows: List[Dict[str, object]] = []
    for n in sorted(harmonic_points.keys()):
        for case_id, point in harmonic_points.get(int(n), {}).items():
            cid = str(case_id)
            if cid not in case_set:
                continue
            z = float(point.get("zmax", 0.0))
            if not np.isfinite(z):
                continue
            rows.append({"case_id": cid, "score": z, "zmax": z, "harmonic": int(n)})
    return _ranked_rows_payload(rows, top_n_scope="per_harmonic")


def _compute_exact_peak_z_ranking(
    freq: np.ndarray,
    r_map: Dict[str, np.ndarray],
    x_map: Dict[str, np.ndarray],
    cases: Sequence[str],
    f1_hz: float,
    n_values: Sequence[int],
    capacitive_only: bool = False,
) -> Dict[str, object]:
    case_set = {str(c) for c in cases}
    rows: List[Dict[str, object]] = []
    freq_arr = np.asarray(freq, dtype=float)
    if freq_arr.size == 0:
        return _ranked_rows_payload(rows, top_n_scope="per_harmonic")
    freq_min = float(np.nanmin(freq_arr))
    freq_max = float(np.nanmax(freq_arr))
    for n in sorted({int(v) for v in n_values if int(v) >= 1}):
        target_hz = float(n) * float(f1_hz)
        if not np.isfinite(target_hz) or target_hz < freq_min or target_hz > freq_max:
            continue
        idx = _nearest_index(freq_arr, target_hz)
        if idx is None:
            continue
        for case in cases:
            cid = str(case)
            if cid not in case_set or cid not in r_map or cid not in x_map:
                continue
            r_arr = np.asarray(r_map[cid], dtype=float)
            x_arr = np.asarray(x_map[cid], dtype=float)
            if idx >= r_arr.size or idx >= x_arr.size:
                continue
            r_val = float(r_arr[idx])
            x_val = float(x_arr[idx])
            if not np.isfinite(r_val) or not np.isfinite(x_val):
                continue
            if bool(capacitive_only) and x_val >= 0.0:
                continue
            z = float(np.sqrt(r_val ** 2 + x_val ** 2))
            rows.append({"case_id": cid, "score": z, "zmax": z, "harmonic": int(n)})
    return _ranked_rows_payload(rows, top_n_scope="per_harmonic")


def _compute_peak_x_ranking(
    x_map: Dict[str, np.ndarray],
    cases: Sequence[str],
    band_indices: Dict[int, np.ndarray],
    capacitive_only: bool = False,
) -> Dict[str, object]:
    case_set = {str(c) for c in cases}
    rows: List[Dict[str, object]] = []
    for n in sorted(int(k) for k in band_indices.keys()):
        b_idx = band_indices.get(int(n), np.asarray([], dtype=int))
        if b_idx.size == 0:
            continue
        for case in cases:
            cid = str(case)
            if cid not in case_set or cid not in x_map:
                continue
            x_vals = np.asarray(x_map[cid], dtype=float)[b_idx]
            valid = np.isfinite(x_vals)
            if bool(capacitive_only):
                valid = valid & (x_vals < 0.0)
                scores = np.where(valid, -x_vals, np.nan)
            else:
                scores = np.where(valid, np.abs(x_vals), np.nan)
            if not np.any(np.isfinite(scores)):
                continue
            score = float(np.nanmax(scores))
            tol = 1e-12 * max(1.0, abs(score))
            local_idx_candidates = np.where(np.isclose(scores, score, rtol=0.0, atol=tol))[0]
            if local_idx_candidates.size == 0:
                local_idx_candidates = np.where(scores == score)[0]
            if local_idx_candidates.size == 0:
                continue
            rows.append(
                {
                    "case_id": cid,
                    "score": score,
                    "zmax": score,
                    "harmonic": int(n),
                }
            )
    return _ranked_rows_payload(rows, top_n_scope="per_harmonic")


def _compute_exact_peak_x_ranking(
    freq: np.ndarray,
    x_map: Dict[str, np.ndarray],
    cases: Sequence[str],
    f1_hz: float,
    n_values: Sequence[int],
    capacitive_only: bool = False,
) -> Dict[str, object]:
    case_set = {str(c) for c in cases}
    rows: List[Dict[str, object]] = []
    freq_arr = np.asarray(freq, dtype=float)
    if freq_arr.size == 0:
        return _ranked_rows_payload(rows, top_n_scope="per_harmonic")
    freq_min = float(np.nanmin(freq_arr))
    freq_max = float(np.nanmax(freq_arr))
    for n in sorted({int(v) for v in n_values if int(v) >= 1}):
        target_hz = float(n) * float(f1_hz)
        if not np.isfinite(target_hz) or target_hz < freq_min or target_hz > freq_max:
            continue
        idx = _nearest_index(freq_arr, target_hz)
        if idx is None:
            continue
        for case in cases:
            cid = str(case)
            if cid not in case_set or cid not in x_map:
                continue
            x_arr = np.asarray(x_map[cid], dtype=float)
            if idx >= x_arr.size:
                continue
            x_val = float(x_arr[idx])
            if not np.isfinite(x_val):
                continue
            if bool(capacitive_only):
                if x_val >= 0.0:
                    continue
                score = -x_val
            else:
                score = abs(x_val)
            rows.append({"case_id": cid, "score": float(score), "zmax": float(score), "harmonic": int(n)})
    return _ranked_rows_payload(rows, top_n_scope="per_harmonic")


def _robust_scale(values: np.ndarray) -> Tuple[float, float]:
    vals = np.asarray(values, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return 0.0, 0.0
    med = float(np.nanmedian(vals))
    mad = float(np.nanmedian(np.abs(vals - med)))
    scale = 1.4826 * mad
    if not np.isfinite(scale) or scale <= 1e-12:
        scale = 0.0
    return med, scale


def _cohort_stats_by_harmonic(
    harmonic_points: Dict[int, Dict[str, Dict[str, float]]]
) -> Dict[int, Dict[str, float]]:
    stats: Dict[int, Dict[str, float]] = {}
    for n, points in harmonic_points.items():
        z_vals = np.asarray(
            [float(p.get("zmax", np.nan)) for p in points.values()],
            dtype=float,
        )
        z_vals = z_vals[np.isfinite(z_vals)]
        if z_vals.size == 0:
            continue
        med, scale = _robust_scale(z_vals)
        p95 = float(np.nanpercentile(z_vals, 95.0))
        if not np.isfinite(p95) or p95 <= 0:
            p95 = float(np.nanmax(z_vals)) if z_vals.size else 0.0
        stats[int(n)] = {
            "median": float(med),
            "scale": float(scale),
            "p95": float(p95),
        }
    return stats


def _compute_risk_ranking(
    harmonic_points: Dict[int, Dict[str, Dict[str, float]]],
    cases: Sequence[str],
    f1_hz: float,
) -> Dict[str, object]:
    case_set = {str(c) for c in cases}
    stats = _cohort_stats_by_harmonic(harmonic_points)
    rows_by_case: Dict[str, Dict[str, object]] = {}
    area_by_case: Dict[str, float] = {str(c): 0.0 for c in cases}
    area_den = 0.0
    point_scores: Dict[str, List[Tuple[float, float, int]]] = {str(c): [] for c in cases}

    for n, points in harmonic_points.items():
        st = stats.get(int(n))
        if not st:
            continue
        med = float(st["median"])
        scale = float(st["scale"])
        p95 = max(float(st["p95"]), 1e-12)
        area_den += p95
        for cid_raw, point in points.items():
            cid = str(cid_raw)
            if cid not in case_set:
                continue
            z = float(point.get("zmax", np.nan))
            r_val = abs(float(point.get("r", np.nan)))
            freq_val = float(point.get("freq", np.nan))
            if not np.isfinite(z):
                continue
            peak_component = z / p95
            if scale > 0:
                prominence_component = max(0.0, (z - med) / scale) / 5.0
            else:
                prominence_component = max(0.0, (z - med) / max(abs(med), 1.0))
            excess = max(0.0, z - med)
            area_by_case[cid] = area_by_case.get(cid, 0.0) + excess
            damping_component = np.log1p(z / max(r_val, 1.0)) / 5.0 if np.isfinite(r_val) else 0.0
            harmonic_center = float(n) * float(f1_hz)
            proximity_component = 0.0
            if np.isfinite(freq_val) and harmonic_center > 0:
                rel = abs(freq_val - harmonic_center) / max(BAND_HALF_WIDTH_FACTOR * float(f1_hz), 1e-12)
                proximity_component = max(0.0, 1.0 - min(1.0, rel))
            point_score = (
                0.35 * peak_component
                + 0.20 * prominence_component
                + 0.15 * damping_component
                + 0.10 * proximity_component
            )
            point_scores.setdefault(cid, []).append((float(point_score), z, int(n)))

    area_norm_den = max(area_den, 1e-12)
    for cid, scores in point_scores.items():
        if not scores:
            continue
        best_point = max(scores, key=lambda x: (x[0], x[1], -x[2]))
        area_component = area_by_case.get(cid, 0.0) / area_norm_den
        total_score = float(best_point[0]) + 0.20 * float(area_component)
        rows_by_case[cid] = {
            "case_id": cid,
            "score": total_score,
            "zmax": float(best_point[1]),
            "harmonic": int(best_point[2]),
        }

    return _ranked_rows_payload(list(rows_by_case.values()), top_n_scope="global")


def _compute_outlier_ranking(
    harmonic_points: Dict[int, Dict[str, Dict[str, float]]],
    cases: Sequence[str],
) -> Dict[str, object]:
    case_set = {str(c) for c in cases}
    rows_by_case: Dict[str, Dict[str, object]] = {}
    for n, points in harmonic_points.items():
        vals_by_case: Dict[str, float] = {}
        for cid_raw, point in points.items():
            cid = str(cid_raw)
            if cid not in case_set:
                continue
            z = float(point.get("zmax", np.nan))
            if np.isfinite(z):
                vals_by_case[cid] = z
        vals = np.asarray(list(vals_by_case.values()), dtype=float)
        if vals.size < 3:
            continue
        med, scale = _robust_scale(vals)
        if scale > 0:
            for cid, z in vals_by_case.items():
                robust_z = (z - med) / scale
                if robust_z < OUTLIER_MAD_Z_THRESHOLD:
                    continue
                old = rows_by_case.get(cid)
                if old is None or robust_z > float(old["score"]):
                    rows_by_case[cid] = {
                        "case_id": cid,
                        "score": float(robust_z),
                        "zmax": float(z),
                        "harmonic": int(n),
                    }
        else:
            threshold = float(np.nanpercentile(vals, OUTLIER_PERCENTILE_FALLBACK))
            if not np.isfinite(threshold):
                continue
            for cid, z in vals_by_case.items():
                if z < threshold or z <= med:
                    continue
                score = z / max(threshold, 1e-12)
                old = rows_by_case.get(cid)
                if old is None or score > float(old["score"]):
                    rows_by_case[cid] = {
                        "case_id": cid,
                        "score": float(score),
                        "zmax": float(z),
                        "harmonic": int(n),
                    }
    return _ranked_rows_payload(list(rows_by_case.values()), top_n_scope="global")


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
        harmonic_range = range(2, max_n + 1)
        band_indices, harmonic_points = _compute_harmonic_max_points(
            freq,
            r_map,
            x_map,
            chosen_cases,
            f1_val,
            harmonic_range,
        )
        _band_indices_cap, harmonic_points_capacitive = _compute_harmonic_max_points(
            freq,
            r_map,
            x_map,
            chosen_cases,
            f1_val,
            harmonic_range,
            capacitive_only=True,
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
            band_indices=band_indices,
            harmonic_points=harmonic_points,
        )
        iec_capacitive = _compute_iec_vertices(
            freq,
            r_map,
            x_map,
            chosen_cases,
            f1_val,
            band_indices=band_indices,
            harmonic_points=harmonic_points_capacitive,
        )
        peak_z_exact_all = _compute_exact_peak_z_ranking(
            freq, r_map, x_map, chosen_cases, f1_val, harmonic_range, capacitive_only=False
        )
        peak_z_exact_capacitive = _compute_exact_peak_z_ranking(
            freq, r_map, x_map, chosen_cases, f1_val, harmonic_range, capacitive_only=True
        )
        peak_z_band_all = _compute_peak_z_ranking(harmonic_points, chosen_cases)
        peak_z_band_capacitive = _compute_peak_z_ranking(harmonic_points_capacitive, chosen_cases)
        peak_x_exact_all = _compute_exact_peak_x_ranking(
            freq, x_map, chosen_cases, f1_val, harmonic_range, capacitive_only=False
        )
        peak_x_exact_capacitive = _compute_exact_peak_x_ranking(
            freq, x_map, chosen_cases, f1_val, harmonic_range, capacitive_only=True
        )
        peak_x_band_all = _compute_peak_x_ranking(x_map, chosen_cases, band_indices, capacitive_only=False)
        peak_x_band_capacitive = _compute_peak_x_ranking(x_map, chosen_cases, band_indices, capacitive_only=True)
        risk_all = _compute_risk_ranking(harmonic_points, chosen_cases, f1_val)
        risk_capacitive = _compute_risk_ranking(harmonic_points_capacitive, chosen_cases, f1_val)
        outlier_all = _compute_outlier_ranking(harmonic_points, chosen_cases)
        outlier_capacitive = _compute_outlier_ranking(harmonic_points_capacitive, chosen_cases)
        by_f1[f1_key] = {
            "energinet_metrics": dict(energinet["energinet_metrics"]),
            "band_sample_counts": dict(energinet["band_sample_counts"]),
            "iec_modes": {
                "all": {
                    "iec_case_ids": list(iec_all["iec_case_ids"]),
                    "iec_first_harmonic": dict(iec_all["iec_first_harmonic"]),
                    "iec_vertex_orders": dict(iec_all["iec_vertex_orders"]),
                    "iec_vertex_zmax": dict(iec_all.get("iec_vertex_zmax", {})),
                    "n_env": int(iec_all["n_env"]),
                },
                "capacitive": {
                    "iec_case_ids": list(iec_capacitive["iec_case_ids"]),
                    "iec_first_harmonic": dict(iec_capacitive["iec_first_harmonic"]),
                    "iec_vertex_orders": dict(iec_capacitive["iec_vertex_orders"]),
                    "iec_vertex_zmax": dict(iec_capacitive.get("iec_vertex_zmax", {})),
                    "n_env": int(iec_capacitive["n_env"]),
                },
            },
            "peak_z_modes": {
                "all": dict(peak_z_exact_all),
                "capacitive": dict(peak_z_exact_capacitive),
            },
            "peak_z_band_modes": {
                "all": dict(peak_z_band_all),
                "capacitive": dict(peak_z_band_capacitive),
            },
            "peak_x_modes": {
                "all": dict(peak_x_exact_all),
                "capacitive": dict(peak_x_exact_capacitive),
            },
            "peak_x_band_modes": {
                "all": dict(peak_x_band_all),
                "capacitive": dict(peak_x_band_capacitive),
            },
            "risk_modes": {
                "all": dict(risk_all),
                "capacitive": dict(risk_capacitive),
            },
            "outlier_modes": {
                "all": dict(outlier_all),
                "capacitive": dict(outlier_capacitive),
            },
        }

    return {
        "available": True,
        "error": "",
        "limitation_note": str(LIMITATION_NOTE),
        "cases_count": int(len(chosen_cases)),
        "by_f1": by_f1,
    }


def _to_finite_float_or_none(raw: object) -> Optional[float]:
    try:
        v = float(raw)
    except Exception:
        return None
    return float(v) if np.isfinite(v) else None


def _to_nonnegative_int(raw: object) -> int:
    try:
        v = int(round(float(raw)))
    except Exception:
        return 0
    return max(0, int(v))


def _compact_iec_mode_payload(mode_payload: Dict[str, object], case_index: Dict[str, int]) -> Dict[str, object]:
    vertex_orders_raw = mode_payload.get("iec_vertex_orders")
    vertex_orders = vertex_orders_raw if isinstance(vertex_orders_raw, dict) else {}
    vertex_zmax_raw = mode_payload.get("iec_vertex_zmax")
    vertex_zmax = vertex_zmax_raw if isinstance(vertex_zmax_raw, dict) else {}
    ids_raw = mode_payload.get("iec_case_ids")
    if isinstance(ids_raw, list):
        ids = [str(v) for v in ids_raw if str(v) != ""]
    else:
        ids = sorted([str(k) for k in vertex_orders.keys() if str(k) != ""])

    case_idx: List[int] = []
    orders_out: List[List[int]] = []
    zmax_out: List[List[Optional[float]]] = []
    seen_case_ids = set()
    for cid in ids:
        if cid in seen_case_ids:
            continue
        seen_case_ids.add(cid)
        idx = case_index.get(str(cid))
        if idx is None:
            continue
        ord_src = vertex_orders.get(str(cid))
        ord_list = ord_src if isinstance(ord_src, list) else []
        ord_clean: List[int] = []
        seen_orders = set()
        for hv_raw in ord_list:
            hv = _to_nonnegative_int(hv_raw)
            if hv < 1 or hv in seen_orders:
                continue
            seen_orders.add(hv)
            ord_clean.append(int(hv))
        zmax_src = vertex_zmax.get(str(cid))
        zmax_by_harmonic = zmax_src if isinstance(zmax_src, dict) else {}
        zmax_clean: List[Optional[float]] = []
        for hv in ord_clean:
            zmax_raw = zmax_by_harmonic.get(str(int(hv)), zmax_by_harmonic.get(int(hv)))
            zmax = _to_finite_float_or_none(zmax_raw)
            zmax_clean.append(zmax)
        case_idx.append(int(idx))
        orders_out.append(ord_clean)
        zmax_out.append(zmax_clean)

    return {
        "case_idx": case_idx,
        "vertex_orders": orders_out,
        "vertex_zmax": zmax_out,
        "n_env": int(_to_nonnegative_int(mode_payload.get("n_env", 0))),
        "top_n_scope": "per_harmonic",
    }


def _compact_ranked_mode_payload(mode_payload: Dict[str, object], case_index: Dict[str, int]) -> Dict[str, object]:
    ids_raw = mode_payload.get("case_ids")
    ids = [str(v) for v in ids_raw] if isinstance(ids_raw, list) else []
    scores_raw = mode_payload.get("scores")
    zmax_raw = mode_payload.get("zmax")
    harmonic_raw = mode_payload.get("harmonic")
    scores = scores_raw if isinstance(scores_raw, list) else []
    zmax_list = zmax_raw if isinstance(zmax_raw, list) else []
    harmonic_list = harmonic_raw if isinstance(harmonic_raw, list) else []

    case_idx: List[int] = []
    scores_out: List[float] = []
    zmax_out: List[float] = []
    harmonic_out: List[int] = []
    seen_rows = set()
    for i, cid_raw in enumerate(ids):
        cid = str(cid_raw)
        if not cid:
            continue
        idx = case_index.get(cid)
        if idx is None:
            continue
        score = _to_finite_float_or_none(scores[i] if i < len(scores) else None)
        if score is None:
            continue
        zmax = _to_finite_float_or_none(zmax_list[i] if i < len(zmax_list) else None)
        harmonic = _to_nonnegative_int(harmonic_list[i] if i < len(harmonic_list) else 0)
        row_key = (cid, int(harmonic))
        if row_key in seen_rows:
            continue
        seen_rows.add(row_key)
        case_idx.append(int(idx))
        scores_out.append(float(score))
        zmax_out.append(float(zmax if zmax is not None else 0.0))
        harmonic_out.append(int(harmonic))

    return {
        "case_idx": case_idx,
        "scores": scores_out,
        "zmax": zmax_out,
        "harmonic": harmonic_out,
        "top_n_scope": str(mode_payload.get("top_n_scope", "global")),
    }


def _compact_preselection_payload(payload: Dict[str, object]) -> Dict[str, object]:
    if not isinstance(payload, dict):
        return {
            "available": False,
            "error": "Invalid preselection payload shape.",
            "limitation_note": "",
            "cases_count": 0,
            "format": "compact_v6",
            "by_f1": {},
        }

    if str(payload.get("format", "")) == "compact_v6":
        return dict(payload)

    out: Dict[str, object] = {
        "available": bool(payload.get("available", False)),
        "error": str(payload.get("error", "")),
        "limitation_note": str(payload.get("limitation_note", "")),
        "cases_count": int(_to_nonnegative_int(payload.get("cases_count", 0))),
        "format": "compact_v6",
        "by_f1": {},
    }

    by_f1_raw = payload.get("by_f1")
    by_f1_out: Dict[str, Dict[str, object]] = {}
    if isinstance(by_f1_raw, dict):
        for f1_key, base_node_raw in by_f1_raw.items():
            if not isinstance(base_node_raw, dict):
                continue

            metrics_raw = base_node_raw.get("energinet_metrics")
            metrics = metrics_raw if isinstance(metrics_raw, dict) else {}
            case_ids = sorted([str(cid) for cid in metrics.keys() if str(cid) != ""])

            iec_modes_raw = base_node_raw.get("iec_modes")
            iec_modes = iec_modes_raw if isinstance(iec_modes_raw, dict) else {}
            all_src = iec_modes.get("all")
            capacitive_src = iec_modes.get("capacitive")
            all_node = all_src if isinstance(all_src, dict) else base_node_raw
            capacitive_node = capacitive_src if isinstance(capacitive_src, dict) else all_node
            ranked_sources: List[Dict[str, object]] = []
            for modes_name in (
                "peak_z_modes",
                "peak_z_band_modes",
                "peak_x_modes",
                "peak_x_band_modes",
                "risk_modes",
                "outlier_modes",
            ):
                modes_raw = base_node_raw.get(modes_name)
                modes = modes_raw if isinstance(modes_raw, dict) else {}
                for ranked_node_raw in (modes.get("all"), modes.get("capacitive")):
                    if isinstance(ranked_node_raw, dict):
                        ranked_sources.append(ranked_node_raw)

            for mode_node in (all_node, capacitive_node):
                mode_ids = mode_node.get("iec_case_ids") if isinstance(mode_node, dict) else None
                if isinstance(mode_ids, list):
                    for cid in mode_ids:
                        c = str(cid)
                        if c and c not in case_ids:
                            case_ids.append(c)
            for ranked_node in ranked_sources:
                ranked_ids = ranked_node.get("case_ids")
                if isinstance(ranked_ids, list):
                    for cid in ranked_ids:
                        c = str(cid)
                        if c and c not in case_ids:
                            case_ids.append(c)
            case_ids = sorted(case_ids)
            case_index = {cid: i for i, cid in enumerate(case_ids)}
            ranked_modes: Dict[str, Dict[str, object]] = {}
            for modes_name in (
                "peak_z_modes",
                "peak_z_band_modes",
                "peak_x_modes",
                "peak_x_band_modes",
                "risk_modes",
                "outlier_modes",
            ):
                modes_raw = base_node_raw.get(modes_name)
                modes = modes_raw if isinstance(modes_raw, dict) else {}
                all_mode = modes.get("all")
                cap_mode = modes.get("capacitive")
                ranked_modes[modes_name] = {
                    "all": _compact_ranked_mode_payload(
                        all_mode if isinstance(all_mode, dict) else {},
                        case_index,
                    ),
                    "capacitive": _compact_ranked_mode_payload(
                        cap_mode if isinstance(cap_mode, dict) else {},
                        case_index,
                    ),
                }

            z2: List[Optional[float]] = []
            z3: List[Optional[float]] = []
            z4: List[Optional[float]] = []
            f2: List[Optional[float]] = []
            f3: List[Optional[float]] = []
            f4: List[Optional[float]] = []
            for cid in case_ids:
                row_raw = metrics.get(cid)
                row = row_raw if isinstance(row_raw, dict) else {}
                z2.append(_to_finite_float_or_none(row.get("zmax_band_2")))
                z3.append(_to_finite_float_or_none(row.get("zmax_band_3")))
                z4.append(_to_finite_float_or_none(row.get("zmax_band_4")))
                f2.append(_to_finite_float_or_none(row.get("f_at_zmax_band_2")))
                f3.append(_to_finite_float_or_none(row.get("f_at_zmax_band_3")))
                f4.append(_to_finite_float_or_none(row.get("f_at_zmax_band_4")))

            band_counts_raw = base_node_raw.get("band_sample_counts")
            band_counts_in = band_counts_raw if isinstance(band_counts_raw, dict) else {}
            band_counts = {
                str(k): int(_to_nonnegative_int(v))
                for k, v in band_counts_in.items()
            }

            by_f1_out[str(f1_key)] = {
                "format": "compact_v6",
                "case_ids": list(case_ids),
                "energinet": {
                    "z2": z2,
                    "z3": z3,
                    "z4": z4,
                    "f2": f2,
                    "f3": f3,
                    "f4": f4,
                },
                "band_sample_counts": band_counts,
                "iec_modes": {
                    "all": _compact_iec_mode_payload(all_node, case_index),
                    "capacitive": _compact_iec_mode_payload(capacitive_node, case_index),
                },
                "peak_z_modes": ranked_modes["peak_z_modes"],
                "peak_z_band_modes": ranked_modes["peak_z_band_modes"],
                "peak_x_modes": ranked_modes["peak_x_modes"],
                "peak_x_band_modes": ranked_modes["peak_x_band_modes"],
                "risk_modes": ranked_modes["risk_modes"],
                "outlier_modes": ranked_modes["outlier_modes"],
            }
    out["by_f1"] = by_f1_out
    return out


def build_preselection_payload_safe(
    data: Dict[str, Any],
    cases: Sequence[str],
    fundamentals_hz: Sequence[float] = (50.0, 60.0),
    sequence_sheets: Tuple[str, str] = ("R1", "X1"),
) -> Dict[str, object]:
    try:
        raw_payload = build_preselection_payload(
            data,
            cases,
            fundamentals_hz=fundamentals_hz,
            sequence_sheets=sequence_sheets,
        )
        return _compact_preselection_payload(raw_payload)
    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
            "limitation_note": str(LIMITATION_NOTE),
            "cases_count": int(len(cases)),
            "format": "compact_v6",
            "by_f1": {},
        }

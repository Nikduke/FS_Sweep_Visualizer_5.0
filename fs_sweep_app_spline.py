import io
import os
import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple, Optional, Union

# Main app baseline with JS-side interactive case controls.

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import plotly.colors as pc
import plotly.graph_objects as go
from plotly.basedatatypes import BaseTraceType
from preselection_shortlist import (
    ENERGINET_DEFAULT_THRESHOLDS,
    build_preselection_payload_safe,
    default_energinet_thresholds_for_f1,
)

PLOTLY_LEGEND_SUPPORTS_MAXHEIGHT = "maxheight" in getattr(go.layout.Legend(), "_valid_props", set())


# ---- Page config ----
st.set_page_config(page_title="FS Sweep Visualizer", layout="wide")

# =============================================================================
# Settings (single place to tune defaults)
#
# Preference: use named constants grouped by purpose (lowest code churn and most
# readable in a single-file Streamlit app). Keep `STYLE` as a dict because it
# maps directly to Plotly layout fields.
# =============================================================================

# ---- Style (applies to on-page AND exports) ----
STYLE = {
    "font_family": "Open Sans, verdana, arial, sans-serif",
    "font_color": "#000000",
    "base_font_size_px": 14,
    "tick_font_size_px": 14,
    "axis_title_font_size_px": 16,
    "legend_font_size_px": 14,
    "bold_axis_titles": True,
    # Space between tick labels and axis title (px). Set to None to use auto heuristic.
    "xaxis_title_standoff_px": None,
    "yaxis_title_standoff_px": None,
}

# ---- Layout (web view) ----
# NOTE: Keep the bottom legend layout; axis overlap is handled by title standoff + margins.
DEFAULT_FIGURE_WIDTH_PX = 1400
TOP_MARGIN_PX = 40
BOTTOM_AXIS_PX = 60
LEFT_MARGIN_PX = 60
RIGHT_MARGIN_PX = 20

# Layout heuristics (auto margins based on font sizes)
BOTTOM_AXIS_TICK_MULT = 2.4
BOTTOM_AXIS_TITLE_MULT = 1.6
LEFT_MARGIN_TICK_MULT = 4.4
LEFT_MARGIN_TITLE_MULT = 1.6
AXIS_TITLE_STANDOFF_TICK_MULT = 1.1
AXIS_TITLE_STANDOFF_MIN_PX = 10

# ---- Legend sizing (web + export) ----
LEGEND_PADDING_PX = 18  # extra padding used in export legend margin/layout
WEB_LEGEND_EXTRA_PAD_PX = 10  # web-only safety pad to reduce last-row clipping
WEB_LEGEND_VIEWPORT_PX = 500  # fixed visible legend viewport under web line plots

# ---- Performance / computation ----
DEFAULT_SPLINE_SMOOTHING = 1.0
SPLINE_SMOOTHING_MIN = 0.0
SPLINE_SMOOTHING_MAX = 1.3
SPLINE_SMOOTHING_STEP = 0.05
XR_EPS = 1e-9  # treat |R| < XR_EPS as invalid for X/R
XR_EPS_DISPLAY = "1e-9"  # shown in UI text (keep in sync with XR_EPS)
SHEET_VALUE_DTYPE = np.float32  # compact in-memory numeric representation for large uploads
FIGURE_CACHE_MAX_ITEMS_ENV = "FS_SWEEP_MAX_FIGURE_CACHE_ITEMS"
FIGURE_CACHE_LRU_STATE_KEY = "figure_cache_lru"
LINE_X_AXIS_UNIT = "hz"

# ---- Export ----
EXPORT_IMAGE_SCALE = 4  # modebar + full-legend export
EXPORT_FALLBACK_COLOR = "#444"

# Full-legend export (JS layout heuristics)
EXPORT_LEGEND_ROW_HEIGHT_FACTOR = 1.25
EXPORT_SAMPLE_LINE_MIN_PX = 18
EXPORT_SAMPLE_LINE_MULT = 1.8
EXPORT_SAMPLE_GAP_MIN_PX = 6
EXPORT_SAMPLE_GAP_MULT = 0.6
EXPORT_TEXT_PAD_MIN_PX = 8
EXPORT_TEXT_PAD_MULT = 0.8
EXPORT_LEGEND_TAIL_FONT_MULT = 0.35
EXPORT_LEGEND_ROW_Y_OFFSET = 0.6
EXPORT_COL_PADDING_MAX_PX = 12
EXPORT_COL_PADDING_FRAC = 0.06

# ---- App behavior ----
UPLOAD_SHA1_PREFIX_LEN = 10

# Session-state cache keys that are scoped by `{data_id}` and can be pruned for old files.
STATE_CACHE_KEY_PREFIXES = (
    "location_select:",
    "uploaded_data:",
    "preselection_payload:",
    "line_fig_sig:",
    "line_fig_cache:",
    "line_fig_meta:",
    "rx_filter_sig:",
    "rx_fig_sig:",
    "rx_fig_cache:",
    "rx_fig_steps:",
    "selection_bind_nonce:",
    "chart_context_tracker:",
)
SEQUENCE_RENDER_CACHE_PREFIXES = (
    "line_fig_sig:",
    "line_fig_cache:",
    "line_fig_meta:",
    "rx_filter_sig:",
    "rx_fig_sig:",
    "rx_fig_cache:",
    "rx_fig_steps:",
)

# ---- Color shading (clustered color palette) ----
COLOR_FALLBACK_RGB255 = (68, 68, 68)
COLOR_LIGHTEN_MAX_T = 0.40
COLOR_DARKEN_MAX_T = 0.25

# ---- Interactive selection styling ----
SELECTED_LINE_WIDTH = 2.5
DIM_LINE_WIDTH = 1.0
DIM_LINE_OPACITY = 0.35
DIM_LINE_COLOR = "#B8B8B8"
SELECTED_MARKER_SIZE = 10.0
DIM_MARKER_OPACITY = 0.28

# ---- R vs X scatter ----
RX_SCATTER_HEIGHT_FACTOR = 1.5
RX_TOOLBAR_INITIAL_HEIGHT_PX = 220
SELECTION_MODE_AXIS_FONT_COLOR = "#6B7280"
SELECTION_MODE_AXIS_TITLE_FONT_SIZE_PX = 14
SELECTION_MODE_TICK_FONT_SIZE_PX = 12
SELECTION_MODE_LINE_MARGIN_BOTTOM_PX = 72

_plotly_selection_bridge = components.declare_component(
    "plotly_selection_bridge_v16",
    path=str(os.path.join(os.path.dirname(__file__), "plotly_selection_bridge")),
)

_plotly_export_button = components.declare_component(
    "plotly_export_button_v2",
    path=str(os.path.join(os.path.dirname(__file__), "plotly_export_button")),
)

_plotly_rx_toolbar = components.declare_component(
    "plotly_rx_toolbar_v2",
    path=str(os.path.join(os.path.dirname(__file__), "plotly_rx_toolbar")),
)


@dataclass
class SweepSheet:
    frequency_hz: np.ndarray
    case_ids: Tuple[str, ...]
    values: np.ndarray
    _prepared: Optional[Tuple[np.ndarray, Dict[str, np.ndarray]]] = field(default=None, init=False, repr=False)

    def prepared_arrays(self) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
        if self._prepared is None:
            fmap: Dict[str, np.ndarray] = {}
            n_cases = int(self.values.shape[1]) if self.values.ndim == 2 else 0
            for i, cid in enumerate(self.case_ids):
                if i >= n_cases:
                    break
                fmap[str(cid)] = self.values[:, i]
            self._prepared = (self.frequency_hz, fmap)
        return self._prepared


SheetLike = Union[pd.DataFrame, SweepSheet]


@dataclass
class AppRenderContext:
    data_id: str
    upload_nonce: int
    seq_label: str
    f_base: float
    plot_height: int
    figure_width_px: int
    enable_spline: bool
    smooth: float
    selection_reset_token: int
    df_r: Optional[SheetLike]
    df_x: Optional[SheetLike]
    location_cases: List[str]
    selected_location: str
    chart_id: str
    show_plot_rx: bool
    show_plot_x: bool
    show_plot_r: bool
    show_plot_xr: bool
    show_plot_z: bool
    selection_mode_layout: bool
    render_auto_width: bool
    preselection_payload: Dict[str, object]
    cases_meta: List[Dict[str, object]]
    part_labels: List[str]
    color_by_options: List[str]
    color_maps: Dict[str, List[str]]
    auto_color_part_label: str
    case_colors_line: Dict[str, str]
    case_colors_scatter: Dict[str, str]
    cases_sig: str
    line_colors_sig: str
    scatter_colors_sig: str
    interactive_controls_area: object


def plotly_selection_bridge(
    data_id: str,
    chart_id: str,
    plot_ids: List[str],
    cases_meta: List[Dict[str, object]],
    part_labels: List[str],
    color_by_options: List[str],
    color_maps: Dict[str, List[str]],
    auto_color_part_label: str = "",
    color_by_default: str = "Auto",
    show_only_default: bool = False,
    selected_marker_size: float = float(SELECTED_MARKER_SIZE),
    dim_marker_opacity: float = float(DIM_MARKER_OPACITY),
    selected_line_width: float = float(SELECTED_LINE_WIDTH),
    dim_line_width: float = float(DIM_LINE_WIDTH),
    dim_line_opacity: float = float(DIM_LINE_OPACITY),
    dim_line_color: str = str(DIM_LINE_COLOR),
    f_base: float = 50.0,
    n_min: float = 0.0,
    n_max: float = 1.0,
    show_harmonics_default: bool = True,
    bin_width_hz_default: float = 0.0,
    rx_status_dom_id: str = "",
    rx_freq_steps: int = 0,
    preselection_payload: Optional[Dict[str, object]] = None,
    energinet_t2_default: float = float(ENERGINET_DEFAULT_THRESHOLDS[2]),
    energinet_t3_default: float = float(ENERGINET_DEFAULT_THRESHOLDS[3]),
    energinet_t4_default: float = float(ENERGINET_DEFAULT_THRESHOLDS[4]),
    reset_token: int = 0,
    selection_reset_token: int = 0,
    render_nonce: int = 0,
    enable_selection: bool = True,
    spline_enabled: bool = False,
) -> None:
    _plotly_selection_bridge(  # type: ignore[misc]
        data_id=str(data_id),
        chart_id=str(chart_id),
        plot_ids=list(plot_ids or []),
        cases_meta=list(cases_meta or []),
        part_labels=list(part_labels or []),
        color_by_options=list(color_by_options or []),
        color_maps=dict(color_maps or {}),
        auto_color_part_label=str(auto_color_part_label or ""),
        color_by_default=str(color_by_default),
        show_only_default=bool(show_only_default),
        selected_marker_size=float(selected_marker_size),
        dim_marker_opacity=float(dim_marker_opacity),
        selected_line_width=float(selected_line_width),
        dim_line_width=float(dim_line_width),
        dim_line_opacity=float(dim_line_opacity),
        dim_line_color=str(dim_line_color),
        f_base=float(f_base),
        n_min=float(n_min),
        n_max=float(n_max),
        show_harmonics_default=bool(show_harmonics_default),
        bin_width_hz_default=float(bin_width_hz_default),
        rx_status_dom_id=str(rx_status_dom_id),
        rx_freq_steps=int(rx_freq_steps),
        preselection_payload=dict(preselection_payload or {}),
        energinet_t2_default=float(energinet_t2_default),
        energinet_t3_default=float(energinet_t3_default),
        energinet_t4_default=float(energinet_t4_default),
        reset_token=int(reset_token),
        selection_reset_token=int(selection_reset_token),
        render_nonce=int(render_nonce),
        enable_selection=bool(enable_selection),
        spline_enabled=bool(spline_enabled),
        key=f"plotly_selection_bridge:{data_id}:{chart_id}",
        height=180,
        default=0,
    )


def _note_upload_change() -> None:
    # Called by st.file_uploader(on_change=...): triggers client-state reset on upload actions.
    st.session_state["upload_nonce"] = int(st.session_state.get("upload_nonce", 0)) + 1
    up = st.session_state.get("xlsx_uploader")
    if up is None:
        st.session_state.pop("uploaded_file_sha1_10", None)
        return
    try:
        st.session_state["uploaded_file_sha1_10"] = hashlib.sha1(up.getvalue()).hexdigest()[: int(UPLOAD_SHA1_PREFIX_LEN)]
    except Exception:
        st.session_state.pop("uploaded_file_sha1_10", None)


def _session_key_matches_data_id(key: str, prefix: str, data_id: str) -> bool:
    base = f"{str(prefix)}{str(data_id)}"
    return str(key) == base or str(key).startswith(f"{base}:")


def _pop_session_keys_matching(predicate: Callable[[str], bool]) -> int:
    removed = 0
    for key in list(st.session_state.keys()):
        k = str(key)
        if not predicate(k):
            continue
        st.session_state.pop(k, None)
        removed += 1
    return int(removed)


def _env_int(name: str, default: int, min_value: int = 0) -> int:
    raw = os.environ.get(str(name), "")
    try:
        value = int(str(raw).strip()) if str(raw).strip() else int(default)
    except Exception:
        value = int(default)
    return max(int(min_value), int(value))


def _stable_string_list_sig(values: List[str]) -> str:
    h = hashlib.sha1()
    for value in values:
        b = str(value).encode("utf-8", errors="replace")
        h.update(len(b).to_bytes(4, "little", signed=False))
        h.update(b)
    return h.hexdigest()[:16]


def _stable_case_color_sig(cases: List[str], case_colors: Dict[str, str]) -> str:
    h = hashlib.sha1()
    for case in cases:
        c = str(case)
        color = str(case_colors.get(c, "#1f77b4"))
        for value in (c, color):
            b = value.encode("utf-8", errors="replace")
            h.update(len(b).to_bytes(4, "little", signed=False))
            h.update(b)
    return h.hexdigest()[:16]


def _touch_figure_cache_key(fig_key: str, related_keys: List[str]) -> None:
    max_items = _env_int(FIGURE_CACHE_MAX_ITEMS_ENV, 8, min_value=0)
    if max_items <= 0:
        return

    raw_lru = st.session_state.get(FIGURE_CACHE_LRU_STATE_KEY)
    lru: Dict[str, List[str]] = dict(raw_lru) if isinstance(raw_lru, dict) else {}
    fig_key_s = str(fig_key)
    lru.pop(fig_key_s, None)
    lru[fig_key_s] = [str(k) for k in related_keys if str(k)]

    for cached_fig_key in list(lru.keys()):
        if cached_fig_key not in st.session_state and cached_fig_key != fig_key_s:
            lru.pop(cached_fig_key, None)

    while len(lru) > max_items:
        old_fig_key = next(iter(lru))
        old_related = lru.pop(old_fig_key, [])
        if old_fig_key == fig_key_s:
            lru[old_fig_key] = old_related
            break
        st.session_state.pop(old_fig_key, None)
        for key in old_related:
            st.session_state.pop(str(key), None)

    st.session_state[FIGURE_CACHE_LRU_STATE_KEY] = lru


def _prune_data_scoped_session_state(current_data_id: str) -> None:
    """
    Remove stale session-state entries for previous data files.

    Keys listed in `STATE_CACHE_KEY_PREFIXES` are expected to be shaped as:
      `{prefix}{data_id}:...`
    """
    did = str(current_data_id or "")
    if not did:
        return

    def should_prune(k: str) -> bool:
        for prefix in STATE_CACHE_KEY_PREFIXES:
            if not k.startswith(prefix):
                continue
            return not _session_key_matches_data_id(k, prefix, did)
        return False

    _pop_session_keys_matching(should_prune)


def _preselection_cache_key(data_id: str, seq_label: str, location_value: str) -> str:
    return f"preselection_payload:{data_id}:{seq_label}:{location_value}"


def _uploaded_workbook_live_cache_key(data_id: str) -> str:
    return f"uploaded_data:{data_id}:workbook"


def _is_sweep_workbook(value: object) -> bool:
    return (
        isinstance(value, dict)
        and len(value) > 0
        and all(isinstance(k, str) and isinstance(v, SweepSheet) for k, v in value.items())
    )


def _selection_bind_nonce_key(data_id: str, chart_id: str) -> str:
    return f"selection_bind_nonce:{data_id}:{chart_id}"


def _chart_context_tracker_key(data_id: str) -> str:
    return f"chart_context_tracker:{data_id}"


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
            "format": "compact_v4",
            "by_f1": {},
        }

    if str(payload.get("format", "")) == "compact_v4":
        return dict(payload)

    out: Dict[str, object] = {
        "available": bool(payload.get("available", False)),
        "error": str(payload.get("error", "")),
        "limitation_note": str(payload.get("limitation_note", "")),
        "cases_count": int(_to_nonnegative_int(payload.get("cases_count", 0))),
        "format": "compact_v4",
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
            for modes_name in ("peak_z_modes", "peak_x_modes", "risk_modes", "outlier_modes"):
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
            for modes_name in ("peak_z_modes", "peak_x_modes", "risk_modes", "outlier_modes"):
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
                "format": "compact_v4",
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
                "peak_x_modes": ranked_modes["peak_x_modes"],
                "risk_modes": ranked_modes["risk_modes"],
                "outlier_modes": ranked_modes["outlier_modes"],
            }
    out["by_f1"] = by_f1_out
    return out


def _evict_sequence_render_caches(data_id: str, seq_label: str) -> None:
    did = str(data_id or "")
    seq = str(seq_label or "")
    if not did or not seq:
        return

    def should_evict(k: str) -> bool:
        return any(k.startswith(f"{prefix}{did}:{seq}:") for prefix in SEQUENCE_RENDER_CACHE_PREFIXES)

    _pop_session_keys_matching(should_evict)


def _prune_chart_scoped_session_state(
    data_id: str,
    seq_label: str,
    selected_location: str,
    chart_id: str,
) -> None:
    did = str(data_id or "")
    seq = str(seq_label or "")
    loc = str(selected_location or "")
    cid = str(chart_id or "")
    if not did:
        return

    current_preselection_key = _preselection_cache_key(did, seq, loc)
    current_nonce_key = _selection_bind_nonce_key(did, cid)
    current_chart_context_key = _chart_context_tracker_key(did)
    current_location_select_key = f"location_select:{did}:{seq}"

    def should_prune(k: str) -> bool:
        if k.startswith(f"selection_bind_nonce:{did}:") and k != current_nonce_key:
            return True
        if k.startswith(f"preselection_payload:{did}:") and k != current_preselection_key:
            return True
        if k.startswith(f"chart_context_tracker:{did}") and k != current_chart_context_key:
            return True
        if k.startswith(f"location_select:{did}:") and k != current_location_select_key:
            return True

        for prefix in SEQUENCE_RENDER_CACHE_PREFIXES:
            if not k.startswith(prefix):
                continue
            return not k.startswith(f"{prefix}{did}:{seq}:")
        return False

    _pop_session_keys_matching(should_prune)


def _maybe_evict_caches_on_chart_switch(
    data_id: str,
    seq_label: str,
    selected_location: str,
    chart_id: str,
) -> None:
    did = str(data_id or "")
    seq = str(seq_label or "")
    loc = str(selected_location or "")
    if not did or not seq:
        return

    tracker_key = _chart_context_tracker_key(did)
    prev_chart = str(st.session_state.get(tracker_key, "") or "")
    cur_chart = str(chart_id or "")
    if prev_chart and cur_chart and prev_chart != cur_chart:
        _evict_sequence_render_caches(did, seq)
        st.session_state.pop(_preselection_cache_key(did, seq, loc), None)
    st.session_state[tracker_key] = cur_chart


def _clamp_int(val: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(val)))


def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    r, g, b = (int(_clamp_int(c, 0, 255)) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _mix_rgb(a: Tuple[int, int, int], b: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    tt = float(max(0.0, min(1.0, t)))
    return (
        int(round(a[0] + (b[0] - a[0]) * tt)),
        int(round(a[1] + (b[1] - a[1]) * tt)),
        int(round(a[2] + (b[2] - a[2]) * tt)),
    )


def _parse_color_to_rgb255(color: str) -> Tuple[int, int, int]:
    """
    Accept Plotly palette entries in either hex ("#rrggbb") or "rgb(...)" / "rgba(...)" form.
    """
    c = str(color).strip()
    if not c:
        return tuple(int(v) for v in COLOR_FALLBACK_RGB255)
    if c.startswith("#"):
        return tuple(int(v) for v in pc.hex_to_rgb(c))
    if c.lower().startswith("rgb"):
        tup = pc.unlabel_rgb(c)
        if len(tup) >= 3:
            return (int(round(tup[0])), int(round(tup[1])), int(round(tup[2])))
    # handle hex without '#'
    c2 = c.lstrip().lower()
    if len(c2) in (3, 6) and all(ch in "0123456789abcdef" for ch in c2):
        if len(c2) == 3:
            c2 = "".join([ch * 2 for ch in c2])
        return tuple(int(v) for v in pc.hex_to_rgb(f"#{c2}"))
    return tuple(int(v) for v in COLOR_FALLBACK_RGB255)


def _shade_hex(base_hex: str, position: float) -> str:
    """
    Create a shade variant of a base color.

    `position` in [-1..1]:
      - negative => darken toward black
      - positive => lighten toward white
    """
    base_rgb = _parse_color_to_rgb255(base_hex)
    p = float(max(-1.0, min(1.0, position)))
    if p >= 0:
        # Lighten
        return _rgb_to_hex(_mix_rgb(base_rgb, (255, 255, 255), t=p * float(COLOR_LIGHTEN_MAX_T)))
    # Darken
    return _rgb_to_hex(_mix_rgb(base_rgb, (0, 0, 0), t=(-p) * float(COLOR_DARKEN_MAX_T)))


def build_clustered_case_colors(cases: List[str], hue_part_override: Optional[int] = None) -> Dict[str, str]:
    """
    Assign colors so related cases cluster by hue, with lighter/darker shades inside each cluster.

    Location suffix (after `__`) is ignored for grouping.
    """
    if not cases:
        return {}

    bases = [split_case_location(c)[0] for c in cases]
    split_parts = [str(b).split("_") for b in bases]
    max_parts = max((len(p) for p in split_parts), default=0)
    if max_parts <= 0:
        # Fallback to simple palette
        palette = pc.qualitative.Safe or pc.qualitative.Plotly or ["#1f77b4"]
        return {
            c: palette[i % len(palette)]
            for i, c in enumerate(sorted(cases))
        }

    # Normalize parts (pad with "")
    parts_norm = [p + [""] * (max_parts - len(p)) for p in split_parts]

    # Pick "hue part":
    # - If hue_part_override is provided and valid, use it.
    # - Otherwise, use the most varying part (ties => earlier part).
    uniq_counts = [len(set(row[i] for row in parts_norm)) for i in range(max_parts)]
    if hue_part_override is not None and 0 <= int(hue_part_override) < int(max_parts):
        hue_part = int(hue_part_override)
        varying = [i for i, n in enumerate(uniq_counts) if n > 1]
        rest = [i for i in varying if i != hue_part]
        shade_part = sorted(rest, key=lambda i: (-uniq_counts[i], i))[0] if rest else None
    else:
        varying = [i for i, n in enumerate(uniq_counts) if n > 1]
        if not varying:
            hue_part = 0
            shade_part = None
        else:
            hue_part = sorted(varying, key=lambda i: (-uniq_counts[i], i))[0]
            rest = [i for i in varying if i != hue_part]
            shade_part = sorted(rest, key=lambda i: (-uniq_counts[i], i))[0] if rest else None

    # Use a combined palette so we have enough distinct hues if there are many groups.
    palette = []
    for pal in (
        getattr(pc.qualitative, "Safe", None),
        getattr(pc.qualitative, "D3", None),
        getattr(pc.qualitative, "Plotly", None),
        getattr(pc.qualitative, "Dark24", None),
        getattr(pc.qualitative, "Light24", None),
    ):
        if pal:
            palette.extend(list(pal))
    if not palette:
        palette = ["#1f77b4"]

    # Group cases
    rows = []
    for case, parts in zip(cases, parts_norm):
        group = parts[hue_part]
        shade_key = parts[shade_part] if shade_part is not None else ""
        rows.append((str(group), str(shade_key), str(case)))

    groups = sorted(set(r[0] for r in rows))
    group_color = {g: palette[i % len(palette)] for i, g in enumerate(groups)}

    case_colors: Dict[str, str] = {}
    for g in groups:
        group_rows = [r for r in rows if r[0] == g]
        group_rows_sorted = sorted(group_rows, key=lambda r: (r[1], r[2]))
        k = len(group_rows_sorted)
        # Spread shades from darker to lighter.
        positions = np.linspace(-1.0, 1.0, k) if k > 1 else np.array([0.0])
        for (row, pos) in zip(group_rows_sorted, positions):
            _group, _shade_key, case = row
            case_colors[case] = _shade_hex(group_color[g], float(pos))

    return case_colors


@st.cache_data(show_spinner=False)
def cached_clustered_case_colors(cases: Tuple[str, ...], hue_part_override: int) -> Dict[str, str]:
    # hue_part_override: -1 => auto; otherwise 0-based case-part index.
    return build_clustered_case_colors(list(cases), None if int(hue_part_override) < 0 else int(hue_part_override))


# ---- Data loading ----
def _find_frequency_column(df: pd.DataFrame) -> Optional[object]:
    for c in df.columns:
        c_norm = str(c).strip().lower().replace(" ", "")
        if c_norm in ["frequency(hz)", "frequencyhz", "frequency_"]:
            return c
        if str(c).strip().lower() in ["frequency (hz)", "frequency"]:
            return c
    if "Frequency (Hz)" in df.columns:
        return "Frequency (Hz)"
    return None


def _sheet_from_dataframe(df: pd.DataFrame, sheet_name: str) -> SweepSheet:
    freq_col = _find_frequency_column(df)
    if freq_col is None:
        raise ValueError(f"Sheet '{sheet_name}' missing 'Frequency (Hz)' column")
    src = df.rename(columns={freq_col: "Frequency (Hz)"})
    freq_raw = pd.to_numeric(src["Frequency (Hz)"], errors="coerce").to_numpy(dtype=np.float64, copy=False)
    finite_mask = np.isfinite(freq_raw)
    freq = freq_raw[finite_mask]
    if freq.size == 0:
        raise ValueError(f"Sheet '{sheet_name}' has empty or invalid frequency column.")

    case_cols = [str(c) for c in src.columns if str(c) != "Frequency (Hz)"]
    n_rows = int(freq.shape[0])
    n_cases = int(len(case_cols))
    if n_cases > 0:
        numeric_cases = src.loc[finite_mask, case_cols].apply(pd.to_numeric, errors="coerce")
        values = numeric_cases.to_numpy(dtype=SHEET_VALUE_DTYPE, copy=True)
        if values.shape != (n_rows, n_cases):
            raise ValueError(f"Sheet '{sheet_name}' row/column count mismatch after numeric conversion.")
    else:
        values = np.empty((n_rows, 0), dtype=SHEET_VALUE_DTYPE)

    return SweepSheet(
        frequency_hz=freq.astype(np.float64, copy=False),
        case_ids=tuple(case_cols),
        values=values,
    )


def _load_fs_sweep_xlsx_impl(path_or_buf) -> Dict[str, SweepSheet]:
    out: Dict[str, SweepSheet] = {}
    xls = pd.ExcelFile(path_or_buf)
    for name in ["R1", "X1", "R0", "X0"]:
        if name not in xls.sheet_names:
            continue
        df = pd.read_excel(xls, sheet_name=name)
        out[name] = _sheet_from_dataframe(df, name)
    return out


@st.cache_data(show_spinner=False)
def load_fs_sweep_xlsx_cached(path_or_buf) -> Dict[str, SweepSheet]:
    return _load_fs_sweep_xlsx_impl(path_or_buf)


def list_case_columns(df: Optional[SheetLike]) -> List[str]:
    if df is None:
        return []
    if isinstance(df, SweepSheet):
        return [str(c) for c in df.case_ids]
    return [c for c in df.columns if c != "Frequency (Hz)"]


def split_case_location(name: str) -> Tuple[str, Optional[str]]:
    if "__" in str(name):
        base, loc = str(name).split("__", 1)
        loc = loc if loc else None
        return base, loc
    return str(name), None


def display_case_name(name: str) -> str:
    base, _ = split_case_location(name)
    return base


def sheet_frequency_values(sheet: Optional[SheetLike]) -> Optional[np.ndarray]:
    if sheet is None:
        return None
    if isinstance(sheet, SweepSheet):
        return np.asarray(sheet.frequency_hz, dtype=np.float64)
    if "Frequency (Hz)" not in sheet.columns:
        return None
    return pd.to_numeric(sheet["Frequency (Hz)"], errors="coerce").to_numpy(dtype=np.float64, copy=False)


def prepare_sheet_arrays(df: SheetLike) -> Tuple[np.ndarray, Dict[object, np.ndarray]]:
    if isinstance(df, SweepSheet):
        freq_hz, fmap = df.prepared_arrays()
        return np.asarray(freq_hz, dtype=np.float64), {str(k): np.asarray(v) for k, v in fmap.items()}

    cached = getattr(df, "attrs", {}).get("__prepared_arrays__")
    if cached is not None:
        return cached

    freq_hz = df["Frequency (Hz)"].to_numpy(copy=False)
    series_map: Dict[object, np.ndarray] = {}
    for c in df.columns:
        if c == "Frequency (Hz)":
            continue
        series_map[c] = df[c].to_numpy(copy=False)
    return freq_hz, series_map


@st.cache_data(show_spinner=False)
def split_case_parts(cases: List[str]) -> Tuple[List[List[str]], List[str]]:
    if not cases:
        return [], []
    temp_parts: List[Tuple[List[str], str]] = []
    max_parts = 0
    for name in cases:
        base_name, location = split_case_location(name)
        base_parts = str(base_name).split("_")
        max_parts = max(max_parts, len(base_parts))
        temp_parts.append((base_parts, location or ""))

    normalized: List[List[str]] = []
    for base_parts, location in temp_parts:
        padded = list(base_parts)
        if len(padded) < max_parts:
            padded.extend([""] * (max_parts - len(padded)))
        padded.append(location or "")
        normalized.append(padded)

    labels = [f"Case part {i+1}" for i in range(max_parts)] + ["Location"]
    return normalized, labels


@st.cache_data(show_spinner=False)
def build_js_case_metadata(cases: Tuple[str, ...]) -> Tuple[List[Dict[str, object]], List[str]]:
    if not cases:
        return [], []
    parts_matrix, part_labels = split_case_parts(list(cases))
    if not part_labels:
        return [], []

    labels_no_loc = list(part_labels[:-1]) if part_labels[-1] == "Location" else list(part_labels)
    part_width = len(labels_no_loc)
    out: List[Dict[str, object]] = []
    for case, row in zip(cases, parts_matrix):
        parts = [str(v) for v in row[:part_width]]
        out.append(
            {
                "case_id": str(case),
                "display_case": str(display_case_name(case)),
                "parts": parts,
            }
        )
    return out, labels_no_loc


@st.cache_data(show_spinner=False)
def _infer_auto_hue_part_label(cases: Tuple[str, ...], part_count: int) -> str:
    # Mirrors Auto hue-part choice used by build_clustered_case_colors(..., hue_part_override=None).
    if not cases or int(part_count) <= 0:
        return ""

    bases = [split_case_location(c)[0] for c in cases]
    split_parts = [str(b).split("_") for b in bases]
    max_parts = max((len(p) for p in split_parts), default=0)
    if max_parts <= 0:
        return ""

    parts_norm = [p + [""] * (max_parts - len(p)) for p in split_parts]
    uniq_counts = [len(set(row[i] for row in parts_norm)) for i in range(max_parts)]
    varying = [i for i, n in enumerate(uniq_counts) if n > 1]
    hue_part = 0 if not varying else sorted(varying, key=lambda i: (-uniq_counts[i], i))[0]
    hue_part = max(0, min(int(part_count) - 1, int(hue_part)))
    return f"Case part {int(hue_part) + 1}"


@st.cache_data(show_spinner=False)
def build_js_color_maps(cases: Tuple[str, ...], part_count: int) -> Tuple[List[str], Dict[str, List[str]], str]:
    options = ["Auto"] + [f"Case part {i}" for i in range(1, int(part_count) + 1)]
    color_maps: Dict[str, List[str]] = {}
    for idx, label in enumerate(options):
        hue_idx = -1 if idx == 0 else idx - 1
        cmap = cached_clustered_case_colors(cases, int(hue_idx))
        color_maps[label] = [str(cmap.get(str(case), "#1f77b4")) for case in cases]
    auto_color_part_label = _infer_auto_hue_part_label(cases, int(part_count))
    return options, color_maps, auto_color_part_label


def _case_color_map_from_array(cases: List[str], colors: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for idx, case in enumerate(cases):
        color = colors[idx] if idx < len(colors) else "#1f77b4"
        out[str(case)] = str(color or "#1f77b4")
    return out


def list_location_values(cases: List[str]) -> List[str]:
    vals = sorted({str(split_case_location(c)[1] or "") for c in cases})
    return vals if vals else [""]


def filter_cases_by_location(cases: List[str], location_value: str) -> List[str]:
    loc = str(location_value or "")
    return [c for c in cases if str(split_case_location(c)[1] or "") == loc]


def compute_common_n_range(f_series: List[Optional[np.ndarray]], f_base: float) -> Tuple[float, float]:
    vals: List[float] = []
    for s in f_series:
        if s is None:
            continue
        v = np.asarray(s, dtype=np.float64)
        v = v[np.isfinite(v)]
        if v.size > 0:
            vals.extend([float(np.min(v)) / f_base, float(np.max(v)) / f_base])
    if not vals:
        return 0.0, 1.0
    lo, hi = float(np.nanmin(vals)), float(np.nanmax(vals))
    return (0.0, 1.0) if (not np.isfinite(lo) or not np.isfinite(hi) or lo >= hi) else (lo, hi)


def _harmonic_tick_arrays(n_lo: float, n_hi: float, f_base: float) -> Tuple[List[float], List[str]]:
    fb = float(f_base)
    if not np.isfinite(fb) or fb <= 0:
        return [], []
    lo = float(n_lo)
    hi = float(n_hi)
    if not np.isfinite(lo) or not np.isfinite(hi) or lo >= hi:
        lo, hi = 0.0, 1.0
    k0 = int(max(0, np.floor(lo)))
    k1 = int(max(k0 + 1, np.ceil(hi)))
    ticks = [float(k * fb) for k in range(k0, k1 + 1)]
    labels = [str(k) for k in range(k0, k1 + 1)]
    return ticks, labels


def _apply_line_harmonic_xaxis(fig: go.Figure, f_base: float, n_lo: float, n_hi: float) -> None:
    fb = float(f_base)
    x_lo = float(n_lo) * fb
    x_hi = float(n_hi) * fb
    tickvals, ticktext = _harmonic_tick_arrays(float(n_lo), float(n_hi), fb)
    fig.update_layout(
        meta={
            **(dict(fig.layout.meta) if isinstance(fig.layout.meta, dict) else {}),
            "line_x_unit": LINE_X_AXIS_UNIT,
            "f_base": float(fb),
        }
    )
    fig.update_xaxes(
        range=[float(x_lo), float(x_hi)],
        tickmode="array",
        tickvals=tickvals,
        ticktext=ticktext,
    )


def make_spline_traces(
    df: SheetLike,
    cases: List[str],
    f_base: float,
    y_title: str,
    smooth: float,
    enable_spline: bool,
    strip_location_suffix: bool,
    case_colors: Dict[str, str],
) -> Tuple[List[BaseTraceType], Optional[np.ndarray]]:
    if df is None:
        return [], None
    cd, y_map = prepare_sheet_arrays(df)
    freq_hz = np.asarray(cd, dtype=np.float64)
    traces: List[BaseTraceType] = []
    TraceCls = go.Scatter if enable_spline else go.Scattergl
    for case in cases:
        y = y_map.get(case)
        if y is None:
            continue
        color = str(case_colors.get(case, "#1f77b4"))
        line_cfg = dict(color=color)
        mode = "lines"
        tr = TraceCls(
            x=freq_hz,
            y=y,
            mode=mode,
            name=display_case_name(case) if strip_location_suffix else str(case),
            meta={
                "kind": "line",
                "case_id": str(case),
                "display_case": str(display_case_name(case)),
                "legend_color": color,
                "x_unit": LINE_X_AXIS_UNIT,
                "f_base": float(f_base),
            },
            line=line_cfg,
            opacity=1.0,
            showlegend=True,
            hovertemplate=(
                "Case=%{fullData.name}<br>f=%{x:.1f} Hz" + f"<br>{y_title}=%{{y}}<extra></extra>"
            ),
        )
        if enable_spline and isinstance(tr, go.Scatter):
            spline_line = dict(
                shape="spline",
                smoothing=float(smooth),
                color=color,
            )
            tr.update(line=spline_line)
        traces.append(tr)
    return traces, np.asarray(cd, dtype=np.float64)


def apply_common_layout(
    fig: go.Figure,
    plot_height: int,
    y_title: str,
    legend_entrywidth: int,
    use_auto_width: bool,
    figure_width_px: int,
):
    font_base = dict(family=STYLE["font_family"], color=STYLE["font_color"])
    # Keep legend under the plot with a fixed viewport region.
    # Plot-area height semantics from `Plot area height (px)` are preserved.
    bottom_axis_px = int(
        max(
            int(BOTTOM_AXIS_PX),
            int(
                round(
                    float(STYLE["tick_font_size_px"]) * float(BOTTOM_AXIS_TICK_MULT)
                    + float(STYLE["axis_title_font_size_px"]) * float(BOTTOM_AXIS_TITLE_MULT)
                )
            ),
        )
    )
    legend_viewport_px = int(max(120, int(WEB_LEGEND_VIEWPORT_PX)))
    legend_reserve_px = int(legend_viewport_px + int(WEB_LEGEND_EXTRA_PAD_PX))
    total_height = int(plot_height) + int(TOP_MARGIN_PX) + int(bottom_axis_px) + int(legend_reserve_px)
    legend_y = -float(bottom_axis_px + 6) / float(max(1, int(plot_height)))

    # Y-axis overlap fix: grow left margin with font sizes.
    left_margin_px = int(
        max(
            int(LEFT_MARGIN_PX),
            int(
                round(
                    float(STYLE["tick_font_size_px"]) * float(LEFT_MARGIN_TICK_MULT)
                    + float(STYLE["axis_title_font_size_px"]) * float(LEFT_MARGIN_TITLE_MULT)
                )
            ),
        )
    )

    legend_cfg = dict(
        orientation="h",
        yanchor="top",
        y=legend_y,
        xanchor="center",
        x=0.5,
        entrywidth=int(legend_entrywidth),
        entrywidthmode="pixels",
        traceorder="normal",
        font=dict(**font_base, size=int(STYLE["legend_font_size_px"])),
    )
    if PLOTLY_LEGEND_SUPPORTS_MAXHEIGHT:
        legend_cfg["maxheight"] = int(legend_viewport_px)

    fig.update_layout(
        autosize=bool(use_auto_width),
        height=total_height,
        showlegend=True,
        font=dict(
            **font_base,
            size=int(STYLE["base_font_size_px"]),
        ),
        margin=dict(
            l=left_margin_px,
            r=RIGHT_MARGIN_PX,
            t=TOP_MARGIN_PX,
            b=int(bottom_axis_px) + int(legend_reserve_px),
        ),
        margin_autoexpand=False,
        legend=legend_cfg,
    )
    if not use_auto_width:
        fig.update_layout(width=int(figure_width_px), autosize=False)

    x_title = "Harmonic number n = f / f_base"
    y_title_txt = str(y_title)
    if bool(STYLE.get("bold_axis_titles", True)):
        x_title = f"<b>{x_title}</b>"
        y_title_txt = f"<b>{y_title_txt}</b>"

    axis_title_font = dict(**font_base, size=int(STYLE["axis_title_font_size_px"]))
    tick_font = dict(**font_base, size=int(STYLE["tick_font_size_px"]))

    x_title_standoff = STYLE.get("xaxis_title_standoff_px")
    if x_title_standoff is None:
        x_title_standoff = int(
            max(
                int(AXIS_TITLE_STANDOFF_MIN_PX),
                round(float(STYLE["tick_font_size_px"]) * float(AXIS_TITLE_STANDOFF_TICK_MULT)),
            )
        )
    else:
        x_title_standoff = int(x_title_standoff)

    y_title_standoff = STYLE.get("yaxis_title_standoff_px")
    if y_title_standoff is None:
        y_title_standoff = int(
            max(
                int(AXIS_TITLE_STANDOFF_MIN_PX),
                round(float(STYLE["tick_font_size_px"]) * float(AXIS_TITLE_STANDOFF_TICK_MULT)),
            )
        )
    else:
        y_title_standoff = int(y_title_standoff)
    fig.update_xaxes(
        title_text=x_title,
        tick0=1,
        dtick=1,
        title_font=axis_title_font,
        tickfont=tick_font,
        automargin=True,
        title_standoff=x_title_standoff,
    )
    fig.update_yaxes(
        title_text=y_title_txt,
        title_font=axis_title_font,
        tickfont=tick_font,
        automargin=True,
        title_standoff=y_title_standoff,
    )


def apply_selection_mode_line_layout(fig: go.Figure, y_title: str, target_height: int) -> None:
    """
    Compact side-by-side selection view: no legend reserve and softer default-like axes.
    Normal stacked layout keeps `apply_common_layout` untouched.
    """
    current_margin = fig.layout.margin
    left_margin = int(current_margin.l) if current_margin and current_margin.l is not None else int(LEFT_MARGIN_PX)
    right_margin = int(current_margin.r) if current_margin and current_margin.r is not None else int(RIGHT_MARGIN_PX)
    top_margin = int(current_margin.t) if current_margin and current_margin.t is not None else int(TOP_MARGIN_PX)
    axis_title_font = dict(
        family=STYLE["font_family"],
        color=str(SELECTION_MODE_AXIS_FONT_COLOR),
        size=int(SELECTION_MODE_AXIS_TITLE_FONT_SIZE_PX),
    )
    tick_font = dict(
        family=STYLE["font_family"],
        color=str(SELECTION_MODE_AXIS_FONT_COLOR),
        size=int(SELECTION_MODE_TICK_FONT_SIZE_PX),
    )
    fig.update_layout(
        height=int(target_height),
        showlegend=False,
        margin=dict(
            l=int(left_margin),
            r=int(right_margin),
            t=int(top_margin),
            b=int(SELECTION_MODE_LINE_MARGIN_BOTTOM_PX),
        ),
        margin_autoexpand=False,
    )
    fig.update_xaxes(
        title_text="Harmonic number n = f / f_base",
        title_font=axis_title_font,
        tickfont=tick_font,
    )
    fig.update_yaxes(
        title_text=str(y_title),
        title_font=axis_title_font,
        tickfont=tick_font,
    )


def build_plot_spline(df: Optional[SheetLike], cases: List[str], f_base: float, plot_height: int, y_title: str,
                      smooth: float, enable_spline: bool, legend_entrywidth: int, strip_location_suffix: bool,
                      use_auto_width: bool, figure_width_px: int, case_colors: Dict[str, str],
                      ) -> Tuple[go.Figure, Optional[np.ndarray]]:
    traces, f_series = make_spline_traces(
        df,
        cases,
        f_base,
        y_title,
        smooth,
        enable_spline,
        strip_location_suffix,
        case_colors,
    )
    fig = go.Figure(data=traces)
    apply_common_layout(fig, plot_height, y_title, legend_entrywidth, use_auto_width, figure_width_px)
    return fig, f_series


def build_x_over_r_spline(df_r: Optional[SheetLike], df_x: Optional[SheetLike], cases: List[str], f_base: float,
                          plot_height: int, seq_label: str, smooth: float, legend_entrywidth: int,
                          enable_spline: bool,
                          strip_location_suffix: bool, use_auto_width: bool, figure_width_px: int,
                          case_colors: Dict[str, str],
                          ) -> Tuple[go.Figure, Optional[np.ndarray], int, int]:
    xr_dropped = 0
    xr_total = 0
    f_series = None
    eps = float(XR_EPS)
    TraceCls = go.Scatter if enable_spline else go.Scattergl
    traces: List[BaseTraceType] = []
    if df_r is not None and df_x is not None:
        cd, r_map = prepare_sheet_arrays(df_r)
        _cd2, x_map = prepare_sheet_arrays(df_x)
        freq_hz = np.asarray(cd, dtype=np.float64)
        both = [c for c in cases if (c in r_map and c in x_map)]
        f_series = sheet_frequency_values(df_r)
        for case in both:
            r = r_map[case]
            x = x_map[case]
            denom_ok = np.abs(r) >= eps
            bad = (~denom_ok) | np.isnan(r) | np.isnan(x)
            y = np.where(denom_ok, x / r, np.nan)
            xr_dropped += int(np.count_nonzero(bad))
            xr_total += int(r.size)
            color = str(case_colors.get(case, "#1f77b4"))
            line_cfg = dict(color=color)
            mode = "lines"
            tr = TraceCls(
                x=freq_hz,
                y=y,
                mode=mode,
                name=display_case_name(case) if strip_location_suffix else str(case),
                meta={
                    "kind": "line",
                    "case_id": str(case),
                    "display_case": str(display_case_name(case)),
                    "legend_color": color,
                    "x_unit": LINE_X_AXIS_UNIT,
                    "f_base": float(f_base),
                },
                line=line_cfg,
                opacity=1.0,
                showlegend=True,
                hovertemplate=(
                    "Case=%{fullData.name}<br>f=%{x:.1f} Hz<br>X/R=%{y}<extra></extra>"
                ),
            )
            if enable_spline and isinstance(tr, go.Scatter):
                spline_line = dict(
                    shape="spline",
                    smoothing=float(smooth),
                    color=color,
                )
                tr.update(line=spline_line)
            traces.append(tr)
    fig = go.Figure(data=traces)
    y_title = "X1/R1 (unitless)" if seq_label == "Positive" else "X0/R0 (unitless)"
    apply_common_layout(fig, plot_height, y_title, legend_entrywidth, use_auto_width, figure_width_px)
    return fig, f_series, xr_dropped, xr_total


def build_z_spline(df_r: Optional[SheetLike], df_x: Optional[SheetLike], cases: List[str], f_base: float,
                   plot_height: int, seq_label: str, smooth: float, legend_entrywidth: int,
                   enable_spline: bool,
                   strip_location_suffix: bool, use_auto_width: bool, figure_width_px: int,
                   case_colors: Dict[str, str],
                   ) -> Tuple[go.Figure, Optional[np.ndarray]]:
    f_series = None
    TraceCls = go.Scatter if enable_spline else go.Scattergl
    traces: List[BaseTraceType] = []
    if df_r is not None and df_x is not None:
        cd, r_map = prepare_sheet_arrays(df_r)
        _cd2, x_map = prepare_sheet_arrays(df_x)
        freq_hz = np.asarray(cd, dtype=np.float64)
        both = [c for c in cases if (c in r_map and c in x_map)]
        f_series = sheet_frequency_values(df_r)
        y_title = "Z1 (\u03A9)" if seq_label == "Positive" else "Z0 (\u03A9)"
        for case in both:
            r = np.asarray(r_map[case], dtype=np.float64)
            x = np.asarray(x_map[case], dtype=np.float64)
            valid = np.isfinite(r) & np.isfinite(x)
            y = np.where(valid, np.sqrt(np.square(r) + np.square(x)), np.nan)
            color = str(case_colors.get(case, "#1f77b4"))
            line_cfg = dict(color=color)
            tr = TraceCls(
                x=freq_hz,
                y=y,
                mode="lines",
                name=display_case_name(case) if strip_location_suffix else str(case),
                meta={
                    "kind": "line",
                    "case_id": str(case),
                    "display_case": str(display_case_name(case)),
                    "legend_color": color,
                    "x_unit": LINE_X_AXIS_UNIT,
                    "f_base": float(f_base),
                },
                line=line_cfg,
                opacity=1.0,
                showlegend=True,
                hovertemplate=(
                    "Case=%{fullData.name}<br>f=%{x:.1f} Hz" + f"<br>{y_title}=%{{y}}<extra></extra>"
                ),
            )
            if enable_spline and isinstance(tr, go.Scatter):
                tr.update(line=dict(shape="spline", smoothing=float(smooth), color=color))
            traces.append(tr)
    fig = go.Figure(data=traces)
    y_title = "Z1 (\u03A9)" if seq_label == "Positive" else "Z0 (\u03A9)"
    apply_common_layout(fig, plot_height, y_title, legend_entrywidth, use_auto_width, figure_width_px)
    return fig, f_series


def _nearest_indices_for_targets(freq: np.ndarray, targets: np.ndarray) -> np.ndarray:
    freq_arr = np.asarray(freq, dtype=np.float64)
    target_arr = np.asarray(targets, dtype=np.float64)
    if freq_arr.size == 0 or target_arr.size == 0:
        return np.zeros((target_arr.size,), dtype=int)
    if freq_arr.size == 1:
        return np.zeros((target_arr.size,), dtype=int)
    finite_freq = np.isfinite(freq_arr)
    if not np.any(finite_freq):
        return np.zeros((target_arr.size,), dtype=int)
    finite_sorted = np.all(np.isfinite(freq_arr)) and bool(np.all(np.diff(freq_arr) >= 0))
    if not finite_sorted:
        finite_positions = np.where(finite_freq)[0]
        finite_values = freq_arr[finite_positions]
        return np.array(
            [int(finite_positions[int(np.argmin(np.abs(finite_values - float(v))))]) for v in target_arr],
            dtype=int,
        )

    pos = np.searchsorted(freq_arr, target_arr, side="left")
    pos = np.clip(pos, 1, int(freq_arr.size) - 1)
    left = freq_arr[pos - 1]
    right = freq_arr[pos]
    use_left = np.abs(target_arr - left) <= np.abs(right - target_arr)
    return np.where(use_left, pos - 1, pos).astype(int, copy=False)


def build_rx_scatter_animated(
    df_r: Optional[SheetLike],
    df_x: Optional[SheetLike],
    cases: List[str],
    seq_label: str,
    case_colors: Dict[str, str],
    plot_height: int,
    axis_cases: Optional[List[str]] = None,
) -> Tuple[go.Figure, int]:
    fig = go.Figure()
    if df_r is None or df_x is None or not cases:
        fig.update_layout(height=500)
        return fig, 0

    fr, r_map = prepare_sheet_arrays(df_r)
    fx, x_map = prepare_sheet_arrays(df_x)
    if fr.size == 0 or fx.size == 0:
        fig.update_layout(height=500)
        return fig, 0

    freq_candidates = sorted(
        {
            float(v)
            for v in np.concatenate([fr[np.isfinite(fr)], fx[np.isfinite(fx)]], axis=0)
            if np.isfinite(v)
        }
    )
    if not freq_candidates:
        fig.update_layout(height=500)
        return fig, 0
    init_idx = int(min(len(freq_candidates) - 1, max(0, len(freq_candidates) // 2)))
    freq_candidates_arr = np.asarray(freq_candidates, dtype=float)

    case_arrays: List[Tuple[str, np.ndarray, np.ndarray]] = []

    for case in cases:
        r_arr = r_map.get(case)
        x_arr = x_map.get(case)
        if r_arr is None or x_arr is None:
            continue
        case_arrays.append((str(case), r_arr, x_arr))
    point_case_ids: List[str] = [str(case) for case, _, _ in case_arrays]
    point_display_names: List[str] = [str(display_case_name(case)) for case in point_case_ids]
    point_colors: List[str] = [str(case_colors.get(case, "#1f77b4")) for case in point_case_ids]
    point_customdata: List[List[object]] = [
        [str(case_id), str(display_name)]
        for case_id, display_name in zip(point_case_ids, point_display_names)
    ]
    if not case_arrays:
        fig.update_layout(height=500)
        return fig, 0

    axis_case_list = list(axis_cases) if axis_cases is not None else list(cases)
    axis_r_arrays = [np.asarray(r_map[str(case)]) for case in axis_case_list if str(case) in r_map]
    axis_x_arrays = [np.asarray(x_map[str(case)]) for case in axis_case_list if str(case) in x_map]
    r_global_min = r_global_max = x_global_min = x_global_max = None
    if axis_r_arrays:
        r_axis_matrix = np.column_stack(axis_r_arrays)
        r_axis_finite = r_axis_matrix[np.isfinite(r_axis_matrix)]
        if r_axis_finite.size > 0:
            r_global_min = float(np.min(r_axis_finite))
            r_global_max = float(np.max(r_axis_finite))
    if axis_x_arrays:
        x_axis_matrix = np.column_stack(axis_x_arrays)
        x_axis_finite = x_axis_matrix[np.isfinite(x_axis_matrix)]
        if x_axis_finite.size > 0:
            x_global_min = float(np.min(x_axis_finite))
            x_global_max = float(np.max(x_axis_finite))

    # Precompute nearest R/X row indices for each slider frequency once.
    idx_r_for_freq = _nearest_indices_for_targets(fr, freq_candidates_arr)
    idx_x_for_freq = _nearest_indices_for_targets(fx, freq_candidates_arr)

    r_matrix = np.column_stack([np.asarray(r_arr) for _case, r_arr, _x_arr in case_arrays])
    x_matrix = np.column_stack([np.asarray(x_arr) for _case, _r_arr, x_arr in case_arrays])
    r_steps = r_matrix[idx_r_for_freq, :]
    x_steps = x_matrix[idx_x_for_freq, :]
    finite_steps = np.isfinite(r_steps) & np.isfinite(x_steps)
    r_steps = np.where(finite_steps, r_steps, np.nan)
    x_steps = np.where(finite_steps, x_steps, np.nan)

    x_flat_by_step = r_steps.ravel(order="C").tolist()
    y_flat_by_step = x_steps.ravel(order="C").tolist()

    tr0 = dict(
        type="scatter",
        x=r_steps[int(init_idx), :].tolist(),
        y=x_steps[int(init_idx), :].tolist(),
        mode="markers",
        name="Cases",
        customdata=point_customdata,
        ids=point_case_ids,
        hovertemplate="Case=%{customdata[1]}<br>R=%{x}<br>X=%{y}<extra></extra>",
        marker=dict(
            color=point_colors,
            size=float(SELECTED_MARKER_SIZE),
            opacity=1.0,
            line=dict(width=0),
        ),
        showlegend=False,
        meta={"kind": "points"},
    )
    fig.add_trace(go.Scatter(**tr0))

    slider_steps = [
        dict(
            method="skip",
            args=[int(i)],
            label=f"{float(f_sel):.1f}",
        )
        for i, f_sel in enumerate(freq_candidates)
    ]

    shapes: List[dict] = [
        dict(type="line", xref="x", yref="paper", x0=0, x1=0, y0=0, y1=1, line=dict(color="rgba(0,0,0,0.45)", width=1)),
        dict(type="line", xref="paper", yref="y", x0=0, x1=1, y0=0, y1=0, line=dict(color="rgba(0,0,0,0.45)", width=1)),
    ]
    fig.update_layout(
        xaxis_title=f"R{1 if seq_label == 'Positive' else 0} (Ohm)",
        yaxis_title=f"X{1 if seq_label == 'Positive' else 0} (Ohm)",
        meta={
            "rx_single_trace": {
                "enabled": True,
                "version": 2,
                "freq_hz": [float(v) for v in freq_candidates],
                "point_count": int(len(point_case_ids)),
                "order": "step-major",
                "x_flat": x_flat_by_step,
                "y_flat": y_flat_by_step,
                "seq_label": str(seq_label),
            }
        },
        height=max(420, int(round(float(plot_height) * float(RX_SCATTER_HEIGHT_FACTOR)))),
        margin=dict(
            l=LEFT_MARGIN_PX,
            r=RIGHT_MARGIN_PX,
            t=TOP_MARGIN_PX,
            b=SELECTION_MODE_LINE_MARGIN_BOTTOM_PX,
        ),
        margin_autoexpand=False,
        dragmode="zoom",
        # Keep click handling deterministic in custom JS stager.
        # Using "event" avoids Plotly's built-in selection-state side effects.
        clickmode="event",
        shapes=shapes,
        sliders=[
            dict(
                active=int(init_idx),
                currentvalue=dict(prefix="Frequency (Hz): "),
                pad=dict(t=20),
                steps=slider_steps,
            )
        ],
    )

    if (
        r_global_min is not None and r_global_max is not None and np.isfinite(r_global_min) and np.isfinite(r_global_max)
        and x_global_min is not None and x_global_max is not None and np.isfinite(x_global_min) and np.isfinite(x_global_max)
    ):
        rx_pad = max(1e-12, 0.04 * max(1e-12, float(r_global_max - r_global_min)))
        xx_pad = max(1e-12, 0.04 * max(1e-12, float(x_global_max - x_global_min)))
        fig.update_xaxes(range=[float(r_global_min - rx_pad), float(r_global_max + rx_pad)])
        fig.update_yaxes(range=[float(x_global_min - xx_pad), float(x_global_max + xx_pad)])
    fig.update_xaxes(zeroline=False)
    fig.update_yaxes(zeroline=False)
    return fig, len(freq_candidates)


def _make_plot_item(
    kind: str,
    fig: go.Figure,
    f_ref: Optional[np.ndarray],
    filename: str,
    chart_key: str,
) -> Dict[str, object]:
    return {
        "kind": str(kind),
        "fig": fig,
        "f_ref": f_ref,
        "filename": str(filename),
        "chart_key": str(chart_key),
    }


def _render_client_png_download(
    filename: str,
    scale: int,
    button_label: str,
    plot_height: int,
    legend_entrywidth: int,
    plot_index: int,
    state_key: str = "",
    selected_case_legend: bool = False,
):
    export_contract = {
        "filename": str(filename),
        "button_label": str(button_label),
        "scale": int(scale),
        "plot_height": int(plot_height),
        "legend_entrywidth": int(legend_entrywidth),
        "plot_index": int(plot_index),
        "state_key": str(state_key),
        "selected_case_legend": bool(selected_case_legend),
        "top_margin_px": int(TOP_MARGIN_PX),
        "bottom_axis_px": int(BOTTOM_AXIS_PX),
        "legend_padding_px": int(LEGEND_PADDING_PX),
        "fallback_legend_font_size": int(STYLE["legend_font_size_px"]),
        "legend_font_family": str(STYLE["font_family"]),
        "legend_font_color": str(STYLE["font_color"]),
        "left_margin_px": int(LEFT_MARGIN_PX),
        "right_margin_px": int(RIGHT_MARGIN_PX),
        "tick_font_size_px": int(STYLE["tick_font_size_px"]),
        "axis_title_font_size_px": int(STYLE["axis_title_font_size_px"]),
        "left_margin_tick_mult": float(LEFT_MARGIN_TICK_MULT),
        "left_margin_title_mult": float(LEFT_MARGIN_TITLE_MULT),
        "export_legend_row_height_factor": float(EXPORT_LEGEND_ROW_HEIGHT_FACTOR),
        "export_sample_line_min_px": int(EXPORT_SAMPLE_LINE_MIN_PX),
        "export_sample_line_mult": float(EXPORT_SAMPLE_LINE_MULT),
        "export_sample_gap_min_px": int(EXPORT_SAMPLE_GAP_MIN_PX),
        "export_sample_gap_mult": float(EXPORT_SAMPLE_GAP_MULT),
        "export_text_pad_min_px": int(EXPORT_TEXT_PAD_MIN_PX),
        "export_text_pad_mult": float(EXPORT_TEXT_PAD_MULT),
        "export_legend_tail_font_mult": float(EXPORT_LEGEND_TAIL_FONT_MULT),
        "export_legend_row_y_offset": float(EXPORT_LEGEND_ROW_Y_OFFSET),
        "export_col_padding_max_px": int(EXPORT_COL_PADDING_MAX_PX),
        "export_col_padding_frac": float(EXPORT_COL_PADDING_FRAC),
        "export_fallback_color": str(EXPORT_FALLBACK_COLOR),
    }
    key_payload = json.dumps(
        {
            "filename": str(filename),
            "button_label": str(button_label),
            "state_key": str(state_key),
            "selected_case_legend": bool(selected_case_legend),
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    key_hash = hashlib.sha1(key_payload.encode("utf-8")).hexdigest()[:10]
    _plotly_export_button(  # type: ignore[misc]
        export_contract=dict(export_contract),
        key=f"plotly_export_button:{key_hash}",
        height=30,
        default=0,
    )


def _render_rx_client_step_buttons(plot_index: int, data_id: str, chart_id: str) -> None:
    key_payload = f"{plot_index}|{data_id}|{chart_id}"
    key_hash = hashlib.sha1(key_payload.encode("utf-8")).hexdigest()[:10]
    _plotly_rx_toolbar(  # type: ignore[misc]
        plot_index=int(plot_index),
        data_id=str(data_id),
        chart_id=str(chart_id),
        key=f"plotly_rx_toolbar:{key_hash}",
        height=int(RX_TOOLBAR_INITIAL_HEIGHT_PX),
        default=0,
    )


def _load_data_source(default_path: str) -> Tuple[Dict[str, SweepSheet], str]:
    """
    Resolve active workbook source and a stable data_id for cache scoping.
    """
    up = st.sidebar.file_uploader(
        "Upload Excel",
        type=["xlsx"],
        key="xlsx_uploader",
        on_change=_note_upload_change,
        help="If empty, loads 'FS_sweep.xlsx' from this folder.",
    )
    st.sidebar.markdown("---")

    data_id = "unknown"
    if up is not None:
        raw_bytes: Optional[bytes] = None
        upload_size_mb = float(getattr(up, "size", 0) or 0) / (1024.0 * 1024.0)
        if upload_size_mb >= 20.0:
            st.sidebar.info("Large file detected: first load can take longer.")
        try:
            cached = st.session_state.get("uploaded_file_sha1_10")
            if cached:
                data_id = str(cached)
            else:
                raw_bytes = up.getvalue()
                data_id = hashlib.sha1(raw_bytes).hexdigest()[:10]
        except Exception:
            data_id = f"upload:{getattr(up, 'name', 'file')}"

        upload_live_cache_key = _uploaded_workbook_live_cache_key(str(data_id))
        cached_workbook = st.session_state.get(upload_live_cache_key)
        if _is_sweep_workbook(cached_workbook):
            return cached_workbook, data_id

        if raw_bytes is None:
            try:
                raw_bytes = up.getvalue()
            except Exception:
                raw_bytes = None
        with st.spinner("Loading workbook..."):
            if raw_bytes is not None:
                data = _load_fs_sweep_xlsx_impl(io.BytesIO(raw_bytes))
            else:
                data = _load_fs_sweep_xlsx_impl(up)
        st.session_state[upload_live_cache_key] = data
        return data, data_id

    if os.path.exists(default_path):
        with st.spinner("Loading workbook..."):
            data = load_fs_sweep_xlsx_cached(default_path)
        try:
            data_id = f"local:{int(os.path.getmtime(default_path))}"
        except Exception:
            data_id = "local"
        st.sidebar.info(f"Loaded local file: {default_path}")
        return data, data_id

    st.warning("Upload an Excel file or place 'FS_sweep.xlsx' here.")
    st.stop()


def _render_global_controls(seq_key: str, container: Optional[object] = None) -> Dict[str, object]:
    """
    Render Streamlit-side controls that intentionally trigger reruns.
    """
    if st.session_state.get(seq_key) not in ("Positive", "Zero"):
        st.session_state[seq_key] = "Positive"

    ui = container if container is not None else st.sidebar
    ui.caption("Plot sizing and slower rendering options.")
    seq_label = str(st.session_state.get(seq_key, "Positive"))
    seq = ("R1", "X1") if seq_label == "Positive" else ("R0", "X0")

    base_freq_key = "base_frequency_hz_control"
    base_freq_val = int(st.session_state.get(base_freq_key, 50))
    if base_freq_val not in (50, 60):
        base_freq_val = 50
        st.session_state[base_freq_key] = 50
    f_base = float(base_freq_val)
    plot_height = ui.slider("Plot area height (px)", min_value=100, max_value=1000, value=400, step=25)
    use_auto_width = ui.checkbox("Auto width (fit container)", value=True)
    figure_width_px = DEFAULT_FIGURE_WIDTH_PX
    if not use_auto_width:
        figure_width_px = ui.slider("Figure width (px)", min_value=800, max_value=2200, value=DEFAULT_FIGURE_WIDTH_PX, step=50)

    enable_spline = ui.checkbox("Spline (slow)", value=False)
    spline_selection_reset_key = "selection_reset_nonce:spline_toggle"
    spline_prev_state_key = "selection_reset_prev_spline"
    prev_spline_state = st.session_state.get(spline_prev_state_key, None)
    if prev_spline_state is None:
        st.session_state[spline_prev_state_key] = bool(enable_spline)
    elif bool(prev_spline_state) != bool(enable_spline):
        st.session_state[spline_selection_reset_key] = int(st.session_state.get(spline_selection_reset_key, 0)) + 1
        st.session_state[spline_prev_state_key] = bool(enable_spline)
    selection_reset_token = int(st.session_state.get(spline_selection_reset_key, 0))

    smooth = float(DEFAULT_SPLINE_SMOOTHING)
    if enable_spline:
        prev_smooth = st.session_state.get("spline_smoothing", float(DEFAULT_SPLINE_SMOOTHING))
        try:
            prev_smooth_f = float(prev_smooth)
        except Exception:
            prev_smooth_f = float(DEFAULT_SPLINE_SMOOTHING)
        prev_smooth_f = max(float(SPLINE_SMOOTHING_MIN), min(float(SPLINE_SMOOTHING_MAX), prev_smooth_f))
        smooth = ui.slider(
            "Spline smoothing",
            min_value=float(SPLINE_SMOOTHING_MIN),
            max_value=float(SPLINE_SMOOTHING_MAX),
            value=prev_smooth_f,
            step=float(SPLINE_SMOOTHING_STEP),
            key="spline_smoothing",
        )

    return {
        "seq_label": seq_label,
        "seq": seq,
        "f_base": float(f_base),
        "base_freq_key": str(base_freq_key),
        "plot_height": int(plot_height),
        "use_auto_width": bool(use_auto_width),
        "figure_width_px": int(figure_width_px),
        "enable_spline": bool(enable_spline),
        "smooth": float(smooth),
        "selection_reset_token": int(selection_reset_token),
    }


def _infer_default_base_frequency(data: Dict[str, SweepSheet]) -> Optional[int]:
    max_freq = 0.0
    for sheet in data.values():
        if not isinstance(sheet, SweepSheet):
            continue
        freq = np.asarray(sheet.frequency_hz, dtype=float)
        freq = freq[np.isfinite(freq)]
        if freq.size:
            max_freq = max(max_freq, float(np.max(freq)))
    if max_freq <= 0.0:
        return None
    if max_freq <= 330.0:
        return 50
    if max_freq <= 390.0:
        return 60
    return None


def _apply_base_frequency_autodetect(data: Dict[str, SweepSheet], data_id: str, base_freq_key: str) -> None:
    marker_key = "base_frequency_autodetect_data_id"
    did = str(data_id or "")
    if not did or st.session_state.get(marker_key) == did:
        return
    inferred = _infer_default_base_frequency(data)
    if inferred in (50, 60):
        st.session_state[base_freq_key] = int(inferred)
    st.session_state[marker_key] = did


def _render_show_plots_controls(container: Optional[object] = None) -> Tuple[bool, bool, bool, bool, bool, bool]:
    ui = container if container is not None else st.sidebar
    ui.header("Show plots")
    show_plot_rx = ui.checkbox("R vs X scatter", value=True, key="show_plot_rx")
    cols = ui.columns(4, gap="small")
    with cols[0]:
        show_plot_x = st.checkbox("X", value=True, key="show_plot_x")
    with cols[1]:
        show_plot_r = st.checkbox("R", value=False, key="show_plot_r")
    with cols[2]:
        show_plot_xr = st.checkbox("X/R", value=False, key="show_plot_xr")
    with cols[3]:
        show_plot_z = st.checkbox("Z", value=False, key="show_plot_z")
    selection_mode_layout = ui.checkbox(
        "Selection mode",
        value=False,
        key="selection_mode_layout",
        help="Layout only: put R vs X and X side by side, with enabled R, X/R, and Z below.",
    )
    return show_plot_rx, show_plot_x, show_plot_r, show_plot_xr, show_plot_z, selection_mode_layout


def _prepare_render_context(default_path: str) -> AppRenderContext:
    st.sidebar.header("Data Source")
    try:
        data, data_id = _load_data_source(default_path)
    except Exception as e:
        st.error(f"Failed to load Excel: {e}")
        st.stop()

    _prune_data_scoped_session_state(data_id)

    upload_nonce = int(st.session_state.get("upload_nonce", 0))
    seq_key = "seq_label_control"
    base_freq_key = "base_frequency_hz_control"
    _apply_base_frequency_autodetect(data, str(data_id), base_freq_key)
    if st.session_state.get(seq_key) not in ("Positive", "Zero"):
        st.session_state[seq_key] = "Positive"
    try:
        base_freq_val = int(st.session_state.get(base_freq_key, 50))
    except Exception:
        base_freq_val = 50
    if base_freq_val not in (50, 60):
        st.session_state[base_freq_key] = 50

    analysis_context_area = st.sidebar.container()
    case_filters_area = st.sidebar.container()
    show_plots_area = st.sidebar.container()
    display_settings_area = st.sidebar.expander("Display settings", expanded=False)

    with analysis_context_area:
        st.header("Analysis context")
        st.caption("Changing these rebuilds plots.")
        st.radio("Sequence", ["Positive", "Zero"], key=seq_key)
        st.radio("Base frequency", [50, 60], key=base_freq_key, format_func=lambda v: f"{int(v)} Hz")

    controls = _render_global_controls(seq_key, display_settings_area)
    seq_label = str(controls["seq_label"])
    seq = controls["seq"]
    f_base = float(controls["f_base"])
    base_freq_key = str(controls["base_freq_key"])
    plot_height = int(controls["plot_height"])
    use_auto_width = bool(controls["use_auto_width"])
    figure_width_px = int(controls["figure_width_px"])
    enable_spline = bool(controls["enable_spline"])
    smooth = float(controls["smooth"])
    selection_reset_token = int(controls["selection_reset_token"])

    df_r = data.get(seq[0])
    df_x = data.get(seq[1])
    if df_r is None and df_x is None:
        st.error(f"Missing sheets for sequence '{seq_label}' ({seq[0]}/{seq[1]}).")
        st.stop()

    all_cases = sorted(list({*list_case_columns(df_r), *list_case_columns(df_x)}))
    if not all_cases:
        st.warning("No case columns found in the selected sequence sheets.")
        st.stop()

    location_values = list_location_values(all_cases)
    location_labels = [("<empty>" if str(v) == "" else str(v)) for v in location_values]
    location_label_to_value = {lbl: val for lbl, val in zip(location_labels, location_values)}
    location_key = f"location_select:{data_id}:{seq_label}"
    if location_key not in st.session_state or st.session_state.get(location_key) not in location_labels:
        st.session_state[location_key] = location_labels[0]

    with analysis_context_area:
        selected_location_label = st.radio("Location", options=location_labels, key=location_key)
    selected_location = str(location_label_to_value.get(str(selected_location_label), ""))

    with case_filters_area:
        st.header("Case Filters & Selection")
        interactive_controls_area = st.container()

    show_plot_rx, show_plot_x, show_plot_r, show_plot_xr, show_plot_z, selection_mode_layout = _render_show_plots_controls(show_plots_area)
    render_auto_width = bool(use_auto_width or selection_mode_layout)
    if not (show_plot_x or show_plot_r or show_plot_xr or show_plot_z or show_plot_rx):
        st.warning("Select at least one plot to display.")
        st.stop()
    f_base = float(int(st.session_state.get(base_freq_key, int(round(f_base)))))
    chart_id = f"{seq_label}:{selected_location}:f{int(round(f_base))}"
    _prune_chart_scoped_session_state(
        data_id=str(data_id),
        seq_label=str(seq_label),
        selected_location=str(selected_location),
        chart_id=str(chart_id),
    )
    _maybe_evict_caches_on_chart_switch(
        data_id=str(data_id),
        seq_label=str(seq_label),
        selected_location=str(selected_location),
        chart_id=str(chart_id),
    )

    if (show_plot_r or show_plot_xr or show_plot_z or show_plot_rx) and df_r is None:
        st.error(f"Sheet '{seq[0]}' is missing, but R, X/R, Z and/or R vs X scatter is enabled.")
        st.stop()
    if (show_plot_x or show_plot_xr or show_plot_z or show_plot_rx) and df_x is None:
        st.error(f"Sheet '{seq[1]}' is missing, but X, X/R, Z and/or R vs X scatter is enabled.")
        st.stop()

    location_cases = filter_cases_by_location(all_cases, selected_location)
    if not location_cases:
        st.warning("No cases found for the selected location.")
        st.stop()

    preselection_cache_key = _preselection_cache_key(str(data_id), str(seq_label), str(selected_location))
    requested_base_key = str(int(round(float(f_base))))
    raw_preselection_payload = st.session_state.get(preselection_cache_key)
    payload_by_f1 = raw_preselection_payload.get("by_f1") if isinstance(raw_preselection_payload, dict) else {}
    cache_has_requested_base = isinstance(payload_by_f1, dict) and requested_base_key in payload_by_f1
    cache_format_ok = isinstance(raw_preselection_payload, dict) and str(raw_preselection_payload.get("format", "")) == "compact_v4"
    if not isinstance(raw_preselection_payload, dict) or not cache_has_requested_base or not cache_format_ok:
        build_location_caption = selected_location if selected_location else "<empty>"
        with st.spinner(f"Building plots for {build_location_caption} / {int(round(f_base))} Hz..."):
            built_payload = build_preselection_payload_safe(
                data=data,
                cases=list(location_cases),
                fundamentals_hz=(float(f_base),),
                sequence_sheets=(str(seq[0]), str(seq[1])),
            )
        raw_preselection_payload = _compact_preselection_payload(built_payload)
        st.session_state[preselection_cache_key] = dict(raw_preselection_payload)
    preselection_payload = dict(raw_preselection_payload)

    cases_tuple = tuple(location_cases)
    cases_meta, part_labels = build_js_case_metadata(cases_tuple)
    color_by_options, color_maps, auto_color_part_label = build_js_color_maps(cases_tuple, len(part_labels))
    default_color_map = _case_color_map_from_array(location_cases, list(color_maps.get("Auto", [])))
    case_colors_line = {c: str(default_color_map.get(c, "#1f77b4")) for c in location_cases}
    case_colors_scatter = {c: str(default_color_map.get(c, "#1f77b4")) for c in location_cases}
    cases_sig = _stable_string_list_sig(list(location_cases))
    line_colors_sig = _stable_case_color_sig(list(location_cases), case_colors_line)
    scatter_colors_sig = _stable_case_color_sig(list(location_cases), case_colors_scatter)

    return AppRenderContext(
        data_id=str(data_id),
        upload_nonce=int(upload_nonce),
        seq_label=str(seq_label),
        f_base=float(f_base),
        plot_height=int(plot_height),
        figure_width_px=int(figure_width_px),
        enable_spline=bool(enable_spline),
        smooth=float(smooth),
        selection_reset_token=int(selection_reset_token),
        df_r=df_r,
        df_x=df_x,
        location_cases=list(location_cases),
        selected_location=str(selected_location),
        chart_id=str(chart_id),
        show_plot_rx=bool(show_plot_rx),
        show_plot_x=bool(show_plot_x),
        show_plot_r=bool(show_plot_r),
        show_plot_xr=bool(show_plot_xr),
        show_plot_z=bool(show_plot_z),
        selection_mode_layout=bool(selection_mode_layout),
        render_auto_width=bool(render_auto_width),
        preselection_payload=dict(preselection_payload),
        cases_meta=list(cases_meta),
        part_labels=list(part_labels),
        color_by_options=list(color_by_options),
        color_maps=dict(color_maps),
        auto_color_part_label=str(auto_color_part_label),
        case_colors_line=dict(case_colors_line),
        case_colors_scatter=dict(case_colors_scatter),
        cases_sig=str(cases_sig),
        line_colors_sig=str(line_colors_sig),
        scatter_colors_sig=str(scatter_colors_sig),
        interactive_controls_area=interactive_controls_area,
    )


def _line_fig_cache_keys(data_id: str, seq_label: str, kind: str) -> Tuple[str, str, str]:
    base = f"{data_id}:{seq_label}:{kind}"
    return (
        f"line_fig_sig:{base}",
        f"line_fig_cache:{base}",
        f"line_fig_meta:{base}",
    )


def _get_or_build_cached_line_figure(
    data_id: str,
    seq_label: str,
    kind: str,
    sig_payload: Dict[str, object],
    builder: Callable[[], Tuple[go.Figure, Dict[str, object]]],
) -> Tuple[go.Figure, Dict[str, object]]:
    sig_key, fig_key, meta_key = _line_fig_cache_keys(data_id, seq_label, kind)
    sig = hashlib.sha1(
        json.dumps(sig_payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]

    if st.session_state.get(sig_key) != sig or (fig_key not in st.session_state):
        fig_built, meta_built = builder()
        st.session_state[sig_key] = sig
        st.session_state[fig_key] = fig_built
        st.session_state[meta_key] = dict(meta_built or {})

    cached_fig = st.session_state.get(fig_key)
    if isinstance(cached_fig, go.Figure):
        fig = cached_fig
    else:
        fig = go.Figure(cached_fig if isinstance(cached_fig, dict) else {})
        st.session_state[fig_key] = fig
    raw_meta = st.session_state.get(meta_key, {})
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    _touch_figure_cache_key(fig_key, [sig_key, meta_key])
    return fig, meta


def _line_sig_payload(
    *,
    kind: str,
    cases_sig: str,
    f_base: float,
    plot_height: int,
    smooth: float,
    enable_spline: bool,
    legend_entrywidth: int,
    strip_location_suffix: bool,
    render_auto_width: bool,
    figure_width_px: int,
    colors_sig: str,
    title: str,
    n_lo: float,
    n_hi: float,
    selection_mode_layout: bool,
) -> Dict[str, object]:
    return {
        "kind": str(kind),
        "cases_sig": str(cases_sig),
        "f_base": float(f_base),
        "plot_h": int(plot_height),
        "smooth": float(smooth),
        "spline": bool(enable_spline),
        "legend_w": int(legend_entrywidth),
        "strip_loc": bool(strip_location_suffix),
        "auto_w": bool(render_auto_width),
        "fig_w": int(figure_width_px),
        "colors_sig": str(colors_sig),
        "title": str(title),
        "n_lo": float(n_lo),
        "n_hi": float(n_hi),
        "sel_layout": bool(selection_mode_layout),
    }


def _build_cached_xy_plot_item(
    *,
    kind: str,
    df: Optional[SheetLike],
    cases: List[str],
    data_id: str,
    seq_label: str,
    f_base: float,
    plot_height: int,
    y_title: str,
    smooth: float,
    enable_spline: bool,
    legend_entrywidth: int,
    strip_location_suffix: bool,
    render_auto_width: bool,
    figure_width_px: int,
    case_colors: Dict[str, str],
    cases_sig: str,
    colors_sig: str,
    filename: str,
    chart_key: str,
    n_lo: float,
    n_hi: float,
    selection_mode_layout: bool,
) -> Dict[str, object]:
    sig_payload = _line_sig_payload(
        kind=str(kind),
        cases_sig=str(cases_sig),
        f_base=float(f_base),
        plot_height=int(plot_height),
        smooth=float(smooth),
        enable_spline=bool(enable_spline),
        legend_entrywidth=int(legend_entrywidth),
        strip_location_suffix=bool(strip_location_suffix),
        render_auto_width=bool(render_auto_width),
        figure_width_px=int(figure_width_px),
        colors_sig=str(colors_sig),
        title=str(y_title),
        n_lo=float(n_lo),
        n_hi=float(n_hi),
        selection_mode_layout=bool(selection_mode_layout),
    )

    def builder() -> Tuple[go.Figure, Dict[str, object]]:
        fig_built, _ = build_plot_spline(
            df,
            cases,
            f_base,
            plot_height,
            y_title,
            smooth,
            enable_spline,
            legend_entrywidth,
            strip_location_suffix,
            render_auto_width,
            figure_width_px,
            case_colors,
        )
        _apply_line_harmonic_xaxis(fig_built, f_base=float(f_base), n_lo=float(n_lo), n_hi=float(n_hi))
        if selection_mode_layout:
            apply_selection_mode_line_layout(
                fig=fig_built,
                y_title=str(y_title),
                target_height=max(420, int(round(float(plot_height) * float(RX_SCATTER_HEIGHT_FACTOR)))),
            )
        return fig_built, {}

    fig, _ = _get_or_build_cached_line_figure(
        data_id=data_id,
        seq_label=seq_label,
        kind=str(kind),
        sig_payload=sig_payload,
        builder=builder,
    )
    return _make_plot_item(str(kind), fig, sheet_frequency_values(df), str(filename), str(chart_key))


def _build_cached_xr_plot_item(
    *,
    df_r: Optional[SheetLike],
    df_x: Optional[SheetLike],
    cases: List[str],
    data_id: str,
    seq_label: str,
    f_base: float,
    plot_height: int,
    smooth: float,
    enable_spline: bool,
    legend_entrywidth: int,
    strip_location_suffix: bool,
    render_auto_width: bool,
    figure_width_px: int,
    case_colors: Dict[str, str],
    cases_sig: str,
    colors_sig: str,
    n_lo: float,
    n_hi: float,
    selection_mode_layout: bool,
) -> Tuple[Dict[str, object], int, int]:
    sig_payload = _line_sig_payload(
        kind="xr",
        cases_sig=str(cases_sig),
        f_base=float(f_base),
        plot_height=int(plot_height),
        smooth=float(smooth),
        enable_spline=bool(enable_spline),
        legend_entrywidth=int(legend_entrywidth),
        strip_location_suffix=bool(strip_location_suffix),
        render_auto_width=bool(render_auto_width),
        figure_width_px=int(figure_width_px),
        colors_sig=str(colors_sig),
        title=str(seq_label),
        n_lo=float(n_lo),
        n_hi=float(n_hi),
        selection_mode_layout=bool(selection_mode_layout),
    )

    def builder() -> Tuple[go.Figure, Dict[str, object]]:
        fig_built, _, xr_dropped_built, xr_total_built = build_x_over_r_spline(
            df_r,
            df_x,
            cases,
            f_base,
            plot_height,
            seq_label,
            smooth,
            legend_entrywidth,
            enable_spline,
            strip_location_suffix,
            render_auto_width,
            figure_width_px,
            case_colors,
        )
        _apply_line_harmonic_xaxis(fig_built, f_base=float(f_base), n_lo=float(n_lo), n_hi=float(n_hi))
        if selection_mode_layout:
            apply_selection_mode_line_layout(
                fig=fig_built,
                y_title=_sequence_y_titles(str(seq_label))["xr"],
                target_height=max(420, int(round(float(plot_height) * float(RX_SCATTER_HEIGHT_FACTOR)))),
            )
        return fig_built, {
            "xr_dropped": int(xr_dropped_built),
            "xr_total": int(xr_total_built),
        }

    fig, meta = _get_or_build_cached_line_figure(
        data_id=data_id,
        seq_label=seq_label,
        kind="xr",
        sig_payload=sig_payload,
        builder=builder,
    )
    item = _make_plot_item("xr", fig, sheet_frequency_values(df_r), "X_over_R_full_legend.png", "plot_xr")
    return item, int(meta.get("xr_dropped", 0)), int(meta.get("xr_total", 0))


def _build_cached_z_plot_item(
    *,
    df_r: Optional[SheetLike],
    df_x: Optional[SheetLike],
    cases: List[str],
    data_id: str,
    seq_label: str,
    f_base: float,
    plot_height: int,
    smooth: float,
    enable_spline: bool,
    legend_entrywidth: int,
    strip_location_suffix: bool,
    render_auto_width: bool,
    figure_width_px: int,
    case_colors: Dict[str, str],
    cases_sig: str,
    colors_sig: str,
    n_lo: float,
    n_hi: float,
    selection_mode_layout: bool,
) -> Dict[str, object]:
    y_title = _sequence_y_titles(str(seq_label))["z"]
    sig_payload = _line_sig_payload(
        kind="z",
        cases_sig=str(cases_sig),
        f_base=float(f_base),
        plot_height=int(plot_height),
        smooth=float(smooth),
        enable_spline=bool(enable_spline),
        legend_entrywidth=int(legend_entrywidth),
        strip_location_suffix=bool(strip_location_suffix),
        render_auto_width=bool(render_auto_width),
        figure_width_px=int(figure_width_px),
        colors_sig=str(colors_sig),
        title=str(y_title),
        n_lo=float(n_lo),
        n_hi=float(n_hi),
        selection_mode_layout=bool(selection_mode_layout),
    )

    def builder() -> Tuple[go.Figure, Dict[str, object]]:
        fig_built, _ = build_z_spline(
            df_r,
            df_x,
            cases,
            f_base,
            plot_height,
            seq_label,
            smooth,
            legend_entrywidth,
            enable_spline,
            strip_location_suffix,
            render_auto_width,
            figure_width_px,
            case_colors,
        )
        _apply_line_harmonic_xaxis(fig_built, f_base=float(f_base), n_lo=float(n_lo), n_hi=float(n_hi))
        if selection_mode_layout:
            apply_selection_mode_line_layout(
                fig=fig_built,
                y_title=str(y_title),
                target_height=max(420, int(round(float(plot_height) * float(RX_SCATTER_HEIGHT_FACTOR)))),
            )
        return fig_built, {}

    fig, _ = _get_or_build_cached_line_figure(
        data_id=data_id,
        seq_label=seq_label,
        kind="z",
        sig_payload=sig_payload,
        builder=builder,
    )
    return _make_plot_item("z", fig, sheet_frequency_values(df_r), "Z_full_legend.png", "plot_z")


def _rx_scatter_cache_keys(data_id: str, seq_label: str) -> Tuple[str, str, str, str]:
    prefix = f"{str(data_id)}:{str(seq_label)}"
    return (
        f"rx_filter_sig:{prefix}",
        f"rx_fig_sig:{prefix}",
        f"rx_fig_cache:{prefix}",
        f"rx_fig_steps:{prefix}",
    )


def _get_or_build_cached_rx_scatter_figure(
    *,
    data_id: str,
    seq_label: str,
    df_r: Optional[SheetLike],
    df_x: Optional[SheetLike],
    location_cases: List[str],
    case_colors: Dict[str, str],
    cases_sig: str,
    colors_sig: str,
    plot_height: int,
) -> Tuple[go.Figure, int]:
    rx_filter_sig_key, rx_fig_sig_key, rx_fig_cache_key, rx_fig_steps_key = _rx_scatter_cache_keys(
        data_id=data_id,
        seq_label=seq_label,
    )

    filter_sig = str(cases_sig or _stable_string_list_sig(sorted(location_cases)))[:16]
    prev_filter_sig = str(st.session_state.get(rx_filter_sig_key, ""))
    if prev_filter_sig != filter_sig:
        st.session_state[rx_filter_sig_key] = filter_sig
        st.session_state.pop(rx_fig_sig_key, None)
        st.session_state.pop(rx_fig_cache_key, None)
        st.session_state.pop(rx_fig_steps_key, None)

    location_cases_for_axes = list(location_cases)
    rx_sig_payload = {
        "seq": str(seq_label),
        "layout": "explicit_scatter_margins_v1",
        "plot_h": int(plot_height),
        "cases_sig": str(cases_sig),
        "axis_cases_sig": _stable_string_list_sig(list(location_cases_for_axes)),
        "colors_sig": str(colors_sig),
    }
    rx_sig = hashlib.sha1(
        json.dumps(rx_sig_payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]

    if st.session_state.get(rx_fig_sig_key) != rx_sig or (rx_fig_cache_key not in st.session_state):
        rx_fig_built, rx_steps_built = build_rx_scatter_animated(
            df_r=df_r,
            df_x=df_x,
            cases=list(location_cases),
            seq_label=seq_label,
            case_colors=case_colors,
            plot_height=int(plot_height),
            axis_cases=list(location_cases_for_axes),
        )
        st.session_state[rx_fig_sig_key] = rx_sig
        st.session_state[rx_fig_cache_key] = rx_fig_built
        st.session_state[rx_fig_steps_key] = int(rx_steps_built)

    cached_rx_fig = st.session_state.get(rx_fig_cache_key)
    if isinstance(cached_rx_fig, go.Figure):
        rx_fig = cached_rx_fig
    else:
        rx_fig = go.Figure(cached_rx_fig if isinstance(cached_rx_fig, dict) else {})
        st.session_state[rx_fig_cache_key] = rx_fig
    _touch_figure_cache_key(rx_fig_cache_key, [rx_filter_sig_key, rx_fig_sig_key, rx_fig_steps_key])
    return rx_fig, int(st.session_state.get(rx_fig_steps_key, 0))


def _sequence_y_titles(seq_label: str) -> Dict[str, str]:
    if str(seq_label) == "Positive":
        return {
            "r": "R1 (\u03A9)",
            "x": "X1 (\u03A9)",
            "xr": "X1/R1 (unitless)",
            "z": "Z1 (\u03A9)",
        }
    return {
        "r": "R0 (\u03A9)",
        "x": "X0 (\u03A9)",
        "xr": "X0/R0 (unitless)",
        "z": "Z0 (\u03A9)",
    }


def _compute_legend_entrywidth(cases: List[str], figure_width_px: int) -> int:
    display_names = [display_case_name(c) for c in cases]
    max_len = max((len(n) for n in display_names), default=12)
    legend_font_px = int(STYLE["legend_font_size_px"])
    approx_char_px = max(7, int(round(0.60 * float(legend_font_px))))
    base_px = max(44, int(round(3.5 * float(legend_font_px))))  # symbol + padding inside a legend item

    est_width_px = int(figure_width_px)
    usable_w = max(1, int(est_width_px) - int(LEFT_MARGIN_PX) - int(RIGHT_MARGIN_PX))
    desired = int(max_len) * int(approx_char_px) + int(base_px)
    entrywidth = _clamp_int(desired, 50, min(900, usable_w))
    if entrywidth >= int(usable_w * 0.95):
        entrywidth = usable_w
    return int(entrywidth)


def _plot_order_from_flags(
    show_plot_rx: bool,
    show_plot_x: bool,
    show_plot_r: bool,
    show_plot_xr: bool,
    show_plot_z: bool,
) -> List[str]:
    order: List[str] = []
    if show_plot_rx:
        order.append("rx")
    if show_plot_x:
        order.append("x")
    if show_plot_r:
        order.append("r")
    if show_plot_xr:
        order.append("xr")
    if show_plot_z:
        order.append("z")
    return order


def _line_kind_order_from_flags(show_plot_x: bool, show_plot_r: bool, show_plot_xr: bool, show_plot_z: bool) -> List[str]:
    order: List[str] = []
    if show_plot_x:
        order.append("x")
    if show_plot_r:
        order.append("r")
    if show_plot_xr:
        order.append("xr")
    if show_plot_z:
        order.append("z")
    return order


def _plotly_download_config() -> Dict[str, object]:
    return {
        "toImageButtonOptions": {
            "format": "png",
            "filename": "plot",
            "scale": int(EXPORT_IMAGE_SCALE),
        }
    }


def _plot_kind_label(kind: str) -> str:
    return {
        "rx": "R vs X",
        "x": "X",
        "r": "R",
        "xr": "X/R",
        "z": "Z",
    }.get(str(kind), str(kind).upper())


def _strip_plotly_markup(value: object) -> str:
    txt = str(value or "")
    for marker in ("<b>", "</b>"):
        txt = txt.replace(marker, "")
    return txt.replace(chr(937), "Ohm").replace(chr(206) + chr(169), "Ohm").strip()


def _line_plot_header_title(it: Dict[str, object]) -> str:
    kind = str(it.get("kind", ""))
    fig = it.get("fig")
    y_title = ""
    base_suffix = ""
    if isinstance(fig, go.Figure):
        title_obj = getattr(getattr(fig.layout, "yaxis", None), "title", None)
        y_title = _strip_plotly_markup(getattr(title_obj, "text", "") if title_obj is not None else "")
        meta = fig.layout.meta if isinstance(fig.layout.meta, dict) else {}
        try:
            f_base = float(meta.get("f_base", float("nan")))
        except Exception:
            f_base = float("nan")
        if np.isfinite(f_base):
            base_suffix = f" ({int(round(f_base))} Hz base)"
    return f"{y_title or _plot_kind_label(kind)} vs harmonic number{base_suffix}"


def _html_escape(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _render_context_header(seq_label: str, f_base: float, selected_location: str, sweep_count: int) -> None:
    location_caption = selected_location if selected_location else "<empty>"
    chips = [
        _html_escape(seq_label),
        f"{int(round(float(f_base)))} Hz",
        _html_escape(location_caption),
        f"{int(sweep_count)} sweeps",
    ]
    chips_html = "".join([f"<span class='fs-context-chip'>{chip}</span>" for chip in chips])
    st.markdown(
        f"""
        <style>
          .fs-context-bar {{
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
            margin: 2px 0 12px 0;
          }}
          .fs-context-chip {{
            display: inline-flex;
            align-items: center;
            min-height: 28px;
            padding: 3px 10px;
            border: 1px solid #d8e0ec;
            border-radius: 999px;
            background: #f7f9fc;
            color: #283345;
            font-size: 14px;
            font-weight: 700;
            line-height: 1.2;
          }}
        </style>
        <div class="fs-context-bar">{chips_html}</div>
        """,
        unsafe_allow_html=True,
    )


def _render_plot_header(
    title: str,
    export_item: Optional[Dict[str, object]] = None,
    *,
    export_scale: int = int(EXPORT_IMAGE_SCALE),
    plot_height: int = 400,
    legend_entrywidth: int = 120,
) -> None:
    st.markdown(
        """
        <style>
          .fs-plot-head-title {
            color: #2b3445;
            font-size: 16px;
            font-weight: 700;
            line-height: 1.2;
            margin: 0 0 2px 0;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if export_item is None:
        cols = st.columns([0.72, 0.28], gap="small", vertical_alignment="center")
        with cols[0]:
            st.markdown(f"<div class='fs-plot-head-title'>{_html_escape(title)}</div>", unsafe_allow_html=True)
        with cols[1]:
            st.markdown("<div style='height:30px'></div>", unsafe_allow_html=True)
        return

    cols = st.columns([0.72, 0.28], gap="small", vertical_alignment="center")
    with cols[0]:
        st.markdown(f"<div class='fs-plot-head-title'>{_html_escape(title)}</div>", unsafe_allow_html=True)
    with cols[1]:
        _render_client_png_download(
            filename=str(export_item.get("filename", "plot.png")),
            scale=int(export_scale),
            button_label="Export PNG",
            plot_height=int(plot_height),
            legend_entrywidth=int(legend_entrywidth),
            plot_index=int(export_item.get("plot_index", 0)),
            state_key=str(export_item.get("state_key", "")),
            selected_case_legend=bool(export_item.get("selected_case_legend", False)),
        )


def _render_line_plot_item(
    it: Dict[str, object],
    render_auto_width: bool,
    download_config: Dict[str, object],
    *,
    export_scale: int,
    plot_height: int,
    legend_entrywidth: int,
) -> None:
    fig = it.get("fig")
    chart_key = str(it.get("chart_key", ""))
    _render_plot_header(
        _line_plot_header_title(it),
        export_item=it,
        export_scale=int(export_scale),
        plot_height=int(plot_height),
        legend_entrywidth=int(legend_entrywidth),
    )
    if isinstance(fig, go.Figure):
        st.plotly_chart(fig, use_container_width=bool(render_auto_width), config=download_config, key=chart_key)


def _render_line_plot_sequence(
    items: List[Dict[str, object]],
    render_auto_width: bool,
    download_config: Dict[str, object],
    *,
    export_scale: int,
    plot_height: int,
    legend_entrywidth: int,
) -> None:
    for idx, it in enumerate(items):
        _render_line_plot_item(
            it,
            render_auto_width=render_auto_width,
            download_config=download_config,
            export_scale=int(export_scale),
            plot_height=int(plot_height),
            legend_entrywidth=int(legend_entrywidth),
        )
        if idx < len(items) - 1:
            st.markdown("<div style='height:36px'></div>", unsafe_allow_html=True)


def _render_rx_scatter_plot(
    *,
    ctx: AppRenderContext,
    plot_order: List[str],
    download_config: Dict[str, object],
) -> Tuple[str, int]:
    if not ctx.show_plot_rx:
        return "", 0

    sequence_suffix = "1" if str(ctx.seq_label) == "Positive" else "0"
    rx_plot_index = int(plot_order.index("rx")) if "rx" in plot_order else 0
    rx_height = max(420, int(round(float(ctx.plot_height) * float(RX_SCATTER_HEIGHT_FACTOR))))
    _render_plot_header(
        f"R{sequence_suffix} vs X{sequence_suffix} scatter",
        export_item={
            "filename": f"R{sequence_suffix}_vs_X{sequence_suffix}_scatter_selected_legend.png",
            "plot_index": int(rx_plot_index),
            "state_key": f"{str(ctx.data_id)}|{str(ctx.chart_id)}",
            "selected_case_legend": True,
        },
        plot_height=int(rx_height),
    )

    rx_fig, rx_freq_steps = _get_or_build_cached_rx_scatter_figure(
        data_id=str(ctx.data_id),
        seq_label=str(ctx.seq_label),
        df_r=ctx.df_r,
        df_x=ctx.df_x,
        location_cases=list(ctx.location_cases),
        case_colors=ctx.case_colors_scatter,
        cases_sig=str(ctx.cases_sig),
        colors_sig=str(ctx.scatter_colors_sig),
        plot_height=int(ctx.plot_height),
    )
    st.plotly_chart(
        rx_fig,
        use_container_width=bool(ctx.render_auto_width),
        config=download_config,
        key="plot_rx",
    )
    _render_rx_client_step_buttons(rx_plot_index, data_id=ctx.data_id, chart_id=ctx.chart_id)
    return "", int(rx_freq_steps)


def _render_selection_mode_row(
    *,
    row_kinds: List[str],
    ctx: AppRenderContext,
    plot_items_by_kind: Dict[str, Dict[str, object]],
    plot_order: List[str],
    download_config: Dict[str, object],
    export_scale: int,
    legend_entrywidth: int,
) -> Tuple[str, int]:
    if not row_kinds:
        return "", 0

    rx_status_dom_id = ""
    rx_freq_steps = 0

    def render_kind(kind: str) -> None:
        nonlocal rx_status_dom_id, rx_freq_steps
        if kind == "rx":
            rx_status_dom_id, rx_freq_steps = _render_rx_scatter_plot(
                ctx=ctx,
                plot_order=plot_order,
                download_config=download_config,
            )
        elif kind in plot_items_by_kind:
            _render_line_plot_item(
                plot_items_by_kind[kind],
                render_auto_width=ctx.render_auto_width,
                download_config=download_config,
                export_scale=int(export_scale),
                plot_height=int(ctx.plot_height),
                legend_entrywidth=int(legend_entrywidth),
            )

    if len(row_kinds) == 1:
        render_kind(str(row_kinds[0]))
        return str(rx_status_dom_id), int(rx_freq_steps)

    row_columns = st.columns(len(row_kinds), gap="medium")
    for column, kind in zip(row_columns, row_kinds):
        with column:
            render_kind(str(kind))
    return str(rx_status_dom_id), int(rx_freq_steps)


def _render_enabled_plots(
    *,
    ctx: AppRenderContext,
    plot_items: List[Dict[str, object]],
    plot_items_by_kind: Dict[str, Dict[str, object]],
    plot_order: List[str],
    download_config: Dict[str, object],
    export_scale: int,
    legend_entrywidth: int,
) -> Tuple[str, int]:
    if ctx.selection_mode_layout:
        first_row_kinds: List[str] = []
        if ctx.show_plot_rx:
            first_row_kinds.append("rx")
        if ctx.show_plot_x and "x" in plot_items_by_kind:
            first_row_kinds.append("x")

        second_row_kinds: List[str] = []
        if ctx.show_plot_r and "r" in plot_items_by_kind:
            second_row_kinds.append("r")
        if ctx.show_plot_xr and "xr" in plot_items_by_kind:
            second_row_kinds.append("xr")
        if ctx.show_plot_z and "z" in plot_items_by_kind:
            second_row_kinds.append("z")

        rx_status_dom_id, rx_freq_steps = _render_selection_mode_row(
            row_kinds=first_row_kinds,
            ctx=ctx,
            plot_items_by_kind=plot_items_by_kind,
            plot_order=plot_order,
            download_config=download_config,
            export_scale=int(export_scale),
            legend_entrywidth=int(legend_entrywidth),
        )
        if first_row_kinds and second_row_kinds:
            st.markdown("<div style='height:36px'></div>", unsafe_allow_html=True)
        second_rx_status_dom_id, second_rx_freq_steps = _render_selection_mode_row(
            row_kinds=second_row_kinds,
            ctx=ctx,
            plot_items_by_kind=plot_items_by_kind,
            plot_order=plot_order,
            download_config=download_config,
            export_scale=int(export_scale),
            legend_entrywidth=int(legend_entrywidth),
        )
        return (
            str(rx_status_dom_id or second_rx_status_dom_id),
            int(rx_freq_steps or second_rx_freq_steps),
        )

    scatter_slot = st.container()
    line_slot = st.container()

    with line_slot:
        _render_line_plot_sequence(
            plot_items,
            render_auto_width=ctx.render_auto_width,
            download_config=download_config,
            export_scale=int(export_scale),
            plot_height=int(ctx.plot_height),
            legend_entrywidth=int(legend_entrywidth),
        )

    with scatter_slot:
        return _render_rx_scatter_plot(
            ctx=ctx,
            plot_order=plot_order,
            download_config=download_config,
        )


def main():
    st.title("FS Sweep Visualizer")

    ctx = _prepare_render_context(default_path="FS_sweep.xlsx")
    data_id = ctx.data_id
    upload_nonce = ctx.upload_nonce
    seq_label = ctx.seq_label
    f_base = ctx.f_base
    plot_height = ctx.plot_height
    figure_width_px = ctx.figure_width_px
    enable_spline = ctx.enable_spline
    smooth = ctx.smooth
    selection_reset_token = ctx.selection_reset_token
    df_r = ctx.df_r
    df_x = ctx.df_x
    location_cases = ctx.location_cases
    selected_location = ctx.selected_location
    chart_id = ctx.chart_id
    show_plot_rx = ctx.show_plot_rx
    show_plot_x = ctx.show_plot_x
    show_plot_r = ctx.show_plot_r
    show_plot_xr = ctx.show_plot_xr
    show_plot_z = ctx.show_plot_z
    selection_mode_layout = ctx.selection_mode_layout
    render_auto_width = ctx.render_auto_width
    preselection_payload = ctx.preselection_payload
    cases_meta = ctx.cases_meta
    part_labels = ctx.part_labels
    color_by_options = ctx.color_by_options
    color_maps = ctx.color_maps
    auto_color_part_label = ctx.auto_color_part_label
    case_colors_line = ctx.case_colors_line
    cases_sig = ctx.cases_sig
    line_colors_sig = ctx.line_colors_sig
    interactive_controls_area = ctx.interactive_controls_area

    download_config = _plotly_download_config()

    # Build all cases for selected location on server-side.
    # Case-part filtering and selection styling are applied client-side in JS.
    cases_for_line = list(location_cases)
    strip_location_suffix = True

    legend_cases = list(cases_for_line)
    legend_entrywidth = _compute_legend_entrywidth(legend_cases, figure_width_px)

    # Render order for currently enabled plots.
    plot_order = _plot_order_from_flags(show_plot_rx, show_plot_x, show_plot_r, show_plot_xr, show_plot_z)

    # Build plots
    build_location_caption = selected_location if selected_location else "<empty>"
    with st.spinner(f"Building plots for {build_location_caption} / {int(round(f_base))} Hz..."):
        line_y_titles = _sequence_y_titles(seq_label)
        r_title = str(line_y_titles["r"])
        x_title = str(line_y_titles["x"])
        plot_items: List[Dict[str, object]] = []
        xr_dropped = 0
        xr_total = 0
        line_range_refs: List[Optional[np.ndarray]] = []
        if show_plot_x:
            line_range_refs.append(sheet_frequency_values(df_x))
        if show_plot_r:
            line_range_refs.append(sheet_frequency_values(df_r))
        if show_plot_xr:
            line_range_refs.append(sheet_frequency_values(df_r))
        if show_plot_z:
            line_range_refs.append(sheet_frequency_values(df_r))
        n_lo, n_hi = compute_common_n_range(line_range_refs, f_base)

        if show_plot_x:
            plot_items.append(_build_cached_xy_plot_item(
                kind="x",
                df=df_x,
                cases=cases_for_line,
                data_id=data_id,
                seq_label=seq_label,
                f_base=f_base,
                plot_height=plot_height,
                y_title=x_title,
                smooth=smooth,
                enable_spline=enable_spline,
                legend_entrywidth=legend_entrywidth,
                strip_location_suffix=strip_location_suffix,
                render_auto_width=render_auto_width,
                figure_width_px=figure_width_px,
                case_colors=case_colors_line,
                cases_sig=cases_sig,
                colors_sig=line_colors_sig,
                filename="X_full_legend.png",
                chart_key="plot_x",
                n_lo=float(n_lo),
                n_hi=float(n_hi),
                selection_mode_layout=bool(selection_mode_layout),
            ))

        if show_plot_r:
            plot_items.append(_build_cached_xy_plot_item(
                kind="r",
                df=df_r,
                cases=cases_for_line,
                data_id=data_id,
                seq_label=seq_label,
                f_base=f_base,
                plot_height=plot_height,
                y_title=r_title,
                smooth=smooth,
                enable_spline=enable_spline,
                legend_entrywidth=legend_entrywidth,
                strip_location_suffix=strip_location_suffix,
                render_auto_width=render_auto_width,
                figure_width_px=figure_width_px,
                case_colors=case_colors_line,
                cases_sig=cases_sig,
                colors_sig=line_colors_sig,
                filename="R_full_legend.png",
                chart_key="plot_r",
                n_lo=float(n_lo),
                n_hi=float(n_hi),
                selection_mode_layout=bool(selection_mode_layout),
            ))

        if show_plot_xr:
            item_xr, xr_dropped, xr_total = _build_cached_xr_plot_item(
                df_r=df_r,
                df_x=df_x,
                cases=cases_for_line,
                data_id=data_id,
                seq_label=seq_label,
                f_base=f_base,
                plot_height=plot_height,
                smooth=smooth,
                enable_spline=enable_spline,
                legend_entrywidth=legend_entrywidth,
                strip_location_suffix=strip_location_suffix,
                render_auto_width=render_auto_width,
                figure_width_px=figure_width_px,
                case_colors=case_colors_line,
                cases_sig=cases_sig,
                colors_sig=line_colors_sig,
                n_lo=float(n_lo),
                n_hi=float(n_hi),
                selection_mode_layout=bool(selection_mode_layout),
            )
            plot_items.append(item_xr)

        if show_plot_z:
            plot_items.append(_build_cached_z_plot_item(
                df_r=df_r,
                df_x=df_x,
                cases=cases_for_line,
                data_id=data_id,
                seq_label=seq_label,
                f_base=f_base,
                plot_height=plot_height,
                smooth=smooth,
                enable_spline=enable_spline,
                legend_entrywidth=legend_entrywidth,
                strip_location_suffix=strip_location_suffix,
                render_auto_width=render_auto_width,
                figure_width_px=figure_width_px,
                case_colors=case_colors_line,
                cases_sig=cases_sig,
                colors_sig=line_colors_sig,
                n_lo=float(n_lo),
                n_hi=float(n_hi),
                selection_mode_layout=bool(selection_mode_layout),
            ))

    # Render
    _render_context_header(
        seq_label=str(seq_label),
        f_base=float(f_base),
        selected_location=str(selected_location),
        sweep_count=len(location_cases),
    )
    if show_plot_xr and xr_total > 0 and xr_dropped > 0:
        st.caption(f"X/R: dropped {xr_dropped} of {xr_total} points where |R| < {XR_EPS_DISPLAY} or data missing.")

    export_scale = int(EXPORT_IMAGE_SCALE)
    plot_items_by_kind = {str(it["kind"]): it for it in plot_items}
    line_plot_base_index = 1 if show_plot_rx else 0
    line_kind_order = _line_kind_order_from_flags(show_plot_x, show_plot_r, show_plot_xr, show_plot_z)
    line_plot_index_map = {kind: int(line_plot_base_index + idx) for idx, kind in enumerate(line_kind_order)}
    for kind, item in plot_items_by_kind.items():
        item["plot_index"] = int(line_plot_index_map.get(str(kind), line_plot_base_index))

    rx_status_dom_id, rx_freq_steps_for_bridge = _render_enabled_plots(
        ctx=ctx,
        plot_items=plot_items,
        plot_items_by_kind=plot_items_by_kind,
        plot_order=plot_order,
        download_config=download_config,
        export_scale=int(export_scale),
        legend_entrywidth=int(legend_entrywidth),
    )

    sel_bind_nonce_key = _selection_bind_nonce_key(str(data_id), str(chart_id))
    st.session_state[sel_bind_nonce_key] = int(st.session_state.get(sel_bind_nonce_key, 0)) + 1

    with interactive_controls_area:
        energinet_defaults = default_energinet_thresholds_for_f1(float(f_base))
        plotly_selection_bridge(
            data_id=data_id,
            chart_id=chart_id,
            plot_ids=list(plot_order),
            cases_meta=list(cases_meta),
            part_labels=list(part_labels),
            color_by_options=list(color_by_options),
            color_maps=dict(color_maps),
            auto_color_part_label=str(auto_color_part_label),
            color_by_default="Auto",
            show_only_default=False,
            selected_marker_size=float(SELECTED_MARKER_SIZE),
            dim_marker_opacity=float(DIM_MARKER_OPACITY),
            selected_line_width=float(SELECTED_LINE_WIDTH),
            dim_line_width=float(DIM_LINE_WIDTH),
            dim_line_opacity=float(DIM_LINE_OPACITY),
            dim_line_color=str(DIM_LINE_COLOR),
            f_base=float(f_base),
            n_min=float(n_lo),
            n_max=float(n_hi),
            show_harmonics_default=True,
            bin_width_hz_default=0.0,
            rx_status_dom_id=str(rx_status_dom_id),
            rx_freq_steps=int(rx_freq_steps_for_bridge),
            preselection_payload=dict(preselection_payload),
            energinet_t2_default=float(energinet_defaults[2]),
            energinet_t3_default=float(energinet_defaults[3]),
            energinet_t4_default=float(energinet_defaults[4]),
            reset_token=int(upload_nonce),
            selection_reset_token=int(selection_reset_token),
            render_nonce=int(st.session_state.get(sel_bind_nonce_key, 0)),
            enable_selection=bool(show_plot_rx),
            spline_enabled=bool(enable_spline),
        )


if __name__ == "__main__":
    main()

const CASE_UI_API_GLOBAL = "__fsCaseUiApi";

function sendToStreamlit(type, payload) {
  try {
    window.parent.postMessage(
      {
        isStreamlitMessage: true,
        type,
        ...(payload || {}),
      },
      "*",
    );
  } catch (e) {
    debugWarn("sendToStreamlit", e);
  }
}

let latestArgs = {};

function debugEnabled() {
  try {
    return Boolean(latestArgs && latestArgs.debug_log);
  } catch (e) {
    return false;
  }
}

function debugWarn(scope, err) {
  if (!debugEnabled()) return;
  try {
    // eslint-disable-next-line no-console
    console.warn(`[fs-export-button] ${scope}`, err);
  } catch (e) {
    // Debug logging must never affect export behavior.
  }
}

function argValue(name) {
  const contract = latestArgs && latestArgs.export_contract && typeof latestArgs.export_contract === "object"
    ? latestArgs.export_contract
    : {};
  if (Object.prototype.hasOwnProperty.call(contract, name)) return contract[name];
  return latestArgs ? latestArgs[name] : null;
}

function asNumber(name, fallback) {
  const v = Number(argValue(name));
  return Number.isFinite(v) ? v : Number(fallback);
}

function asString(name, fallback) {
  const v = argValue(name);
  if (v == null) return String(fallback);
  return String(v);
}

function asBool(name, fallback) {
  const v = argValue(name);
  if (v == null) return Boolean(fallback);
  if (typeof v === "boolean") return v;
  const txt = String(v).trim().toLowerCase();
  if (["true", "1", "yes", "y"].includes(txt)) return true;
  if (["false", "0", "no", "n"].includes(txt)) return false;
  return Boolean(fallback);
}

function escapeHtml(txt) {
  return String(txt == null ? "" : txt)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function exportArgs() {
  const fallbackLegendFontSize = Math.max(8, Math.round(asNumber("fallback_legend_font_size", 14)));
  return {
    scale: Math.max(1, Math.round(asNumber("scale", 1))),
    plotHeight: Math.max(1, Math.round(asNumber("plot_height", 400))),
    topMargin: Math.round(asNumber("top_margin_px", 40)),
    bottomAxis: Math.round(asNumber("bottom_axis_px", 60)),
    legendPad: Math.round(asNumber("legend_padding_px", 18)),
    legendEntryWidth: Math.max(1, Math.round(asNumber("legend_entrywidth", 120))),
    plotIndex: Math.max(0, Math.round(asNumber("plot_index", 0))),
    stateKey: asString("state_key", ""),
    selectedCaseLegend: asBool("selected_case_legend", false),
    filename: asString("filename", "plot.png"),
    fallbackLegendFontSize,
    legendFontFamily: asString("legend_font_family", "Open Sans, verdana, arial, sans-serif"),
    legendFontColor: asString("legend_font_color", "#000000"),
    leftMarginBase: Math.max(1, Math.round(asNumber("left_margin_px", 60))),
    rightMargin: Math.max(0, Math.round(asNumber("right_margin_px", 20))),
    tickFontSize: Math.max(1, Math.round(asNumber("tick_font_size_px", 14))),
    axisTitleFontSize: Math.max(1, Math.round(asNumber("axis_title_font_size_px", 16))),
    leftMarginTickMult: asNumber("left_margin_tick_mult", 4.4),
    leftMarginTitleMult: asNumber("left_margin_title_mult", 1.6),
    rowHeightFactor: asNumber("export_legend_row_height_factor", 1.25),
    sampleLineMinPx: Math.max(1, Math.round(asNumber("export_sample_line_min_px", 18))),
    sampleLineMult: asNumber("export_sample_line_mult", 1.8),
    sampleGapMinPx: Math.max(1, Math.round(asNumber("export_sample_gap_min_px", 6))),
    sampleGapMult: asNumber("export_sample_gap_mult", 0.6),
    textPadMinPx: Math.max(1, Math.round(asNumber("export_text_pad_min_px", 8))),
    textPadMult: asNumber("export_text_pad_mult", 0.8),
    tailFontMult: asNumber("export_legend_tail_font_mult", 0.35),
    rowYOffset: asNumber("export_legend_row_y_offset", 0.6),
    colPaddingMaxPx: Math.max(0, Math.round(asNumber("export_col_padding_max_px", 12))),
    colPaddingFrac: asNumber("export_col_padding_frac", 0.06),
    fallbackColor: asString("export_fallback_color", "#444"),
  };
}

function parentPlotContext(plotIndex) {
  const Plotly = window.parent && window.parent.Plotly ? window.parent.Plotly : null;
  if (!Plotly) return null;
  const plots = window.parent && window.parent.document ? window.parent.document.querySelectorAll("div.js-plotly-plot") : null;
  if (!plots || plots.length <= plotIndex) return null;
  const gd = plots[plotIndex];
  return gd ? { Plotly, gd } : null;
}

function getSelectionApi(stateKey) {
  try {
    const rootWin = window.parent;
    const apiStore = rootWin && rootWin[CASE_UI_API_GLOBAL] && typeof rootWin[CASE_UI_API_GLOBAL] === "object"
      ? rootWin[CASE_UI_API_GLOBAL]
      : null;
    if (!apiStore) return null;
    const api = apiStore[String(stateKey || "")];
    return api && typeof api === "object" ? api : null;
  } catch (e) {
    debugWarn("getSelectionApi", e);
  }
  return null;
}

function exportableData(gd) {
  const data = Array.isArray(gd.data) ? gd.data : [];
  return data.map((tr) => {
    const t = Object.assign({}, tr);
    if (t.type === "scattergl") t.type = "scatter";
    return t;
  });
}

function markerColorAt(markerColor, idx, fallbackColor) {
  if (Array.isArray(markerColor)) {
    const v = markerColor[idx];
    return v == null || String(v) === "" ? fallbackColor : v;
  }
  if (markerColor != null && String(markerColor) !== "") return markerColor;
  return fallbackColor;
}

function selectedCaseLegendItemsForData(data, cfg) {
  if (!cfg.selectedCaseLegend || !cfg.stateKey) return [];
  const api = getSelectionApi(cfg.stateKey);
  if (!api || typeof api.getState !== "function") return [];
  const st = api.getState();
  const selectedRows = st && Array.isArray(st.selectedRows) ? st.selectedRows : [];
  if (selectedRows.length === 0) return [];

  const colorByCase = new Map();
  for (const tr of data) {
    if (!tr || !Array.isArray(tr.ids)) continue;
    const marker = tr.marker && typeof tr.marker === "object" ? tr.marker : {};
    const markerColor = marker.color;
    for (let i = 0; i < tr.ids.length; i++) {
      const cid = String(tr.ids[i] || "");
      if (!cid || colorByCase.has(cid)) continue;
      colorByCase.set(cid, markerColorAt(markerColor, i, cfg.fallbackColor));
    }
  }

  const seen = new Set();
  const items = [];
  for (const row of selectedRows) {
    const cid = String(row && row.caseId != null ? row.caseId : "");
    if (!cid || seen.has(cid) || (row && row.hidden === true)) continue;
    seen.add(cid);
    const display = String(row && row.displayCase ? row.displayCase : cid);
    items.push({ name: display, color: colorByCase.get(cid) || cfg.fallbackColor });
  }
  return items;
}

function legendItemsForData(data, fallbackColor) {
  const items = [];
  for (const tr of data) {
    if (tr && tr.showlegend === false) continue;
    const name = tr && tr.name ? String(tr.name) : "";
    if (!name) continue;
    const color =
      (tr.line && tr.line.color) ? tr.line.color :
      (tr.marker && tr.marker.color) ? tr.marker.color :
      (tr.meta && tr.meta.legend_color) ? tr.meta.legend_color :
      fallbackColor;
    items.push({ name, color });
  }
  return items;
}

function measureMaxLegendTextWidth(items, fontSize, fontFamily) {
  let maxTextW = 0;
  try {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.font = `${fontSize}px ${fontFamily}`;
      for (const it of items) {
        const w = ctx.measureText(it.name).width || 0;
        if (w > maxTextW) maxTextW = w;
      }
    }
  } catch (e) {
    debugWarn("measureMaxLegendTextWidth", e);
  }
  return maxTextW;
}

function resetExportContainer() {
  try {
    const container = document.getElementById("exp-plot");
    if (container) {
      container.innerHTML = "";
      container.style.width = "1px";
      container.style.height = "1px";
    }
  } catch (e) {
    debugWarn("resetExportContainer", e);
  }
}

function render() {
  const root = document.getElementById("app");
  if (!root) return;
  const buttonLabel = asString("button_label", "Export");
  const safeButtonLabel = escapeHtml(buttonLabel);
  root.innerHTML = `
    <style>
      html, body {
        margin: 0;
        padding: 0;
        overflow: hidden;
        background: transparent;
      }
      #exp-root {
        width: 100%;
        height: 28px;
        display: flex;
        align-items: center;
        justify-content: flex-end;
      }
      #exp-btn {
        width: auto;
        min-width: 86px;
        min-height: 24px;
        padding: 2px 9px;
        font-size: 11px;
        font-family: "Open Sans", verdana, arial, sans-serif;
        font-weight: 600;
        color: #243047;
        background: #fff;
        border: 1px solid #b8c7dd;
        border-radius: 8px;
        cursor: pointer;
        white-space: nowrap;
        line-height: 1.15;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      #exp-btn:hover:not(:disabled) {
        background: #f4f8ff;
        border-color: #91a9ca;
      }
      #exp-btn:focus-visible {
        outline: 2px solid #2f6fda;
        outline-offset: 2px;
      }
      #exp-btn:disabled {
        color: #8a95a8;
        background: #eef2f7;
        border-color: #d5deeb;
        cursor: wait;
      }
      #exp-plot {
        width: 1px;
        height: 1px;
        position: absolute;
        left: -99999px;
        top: -99999px;
      }
    </style>
    <div id="exp-root">
      <button id="exp-btn" type="button" aria-label="${safeButtonLabel}">${safeButtonLabel}</button>
      <div id="exp-plot"></div>
    </div>
  `;
  const btn = document.getElementById("exp-btn");
  if (btn) {
    btn.addEventListener("click", async () => {
      if (btn.disabled) return;
      btn.disabled = true;
      btn.textContent = "Exporting PNG...";
      try {
        await doExport();
      } finally {
        btn.disabled = false;
        btn.textContent = buttonLabel;
      }
    });
  }
  sendToStreamlit("streamlit:setFrameHeight", { height: 28 });
}

async function doExport() {
  const cfg = exportArgs();

  try {
    const plotCtx = parentPlotContext(cfg.plotIndex);
    if (!plotCtx) return;
    const Plotly = plotCtx.Plotly;
    const gd = plotCtx.gd;

    const r = gd.getBoundingClientRect();
    const widthPx = Math.floor(r.width || 0);
    if (!widthPx) return;

    const legendFontSize = (
      (gd && gd._fullLayout && gd._fullLayout.legend && gd._fullLayout.legend.font && gd._fullLayout.legend.font.size) ||
      (gd && gd._fullLayout && gd._fullLayout.font && gd._fullLayout.font.size) ||
      cfg.fallbackLegendFontSize
    );
    const legendRowH = Math.ceil(Number(legendFontSize) * cfg.rowHeightFactor);
    const leftMarginPx = Math.max(
      cfg.leftMarginBase,
      Math.round(cfg.tickFontSize * cfg.leftMarginTickMult + cfg.axisTitleFontSize * cfg.leftMarginTitleMult),
    );

    const data2 = exportableData(gd);
    const selectedLegendItems = selectedCaseLegendItemsForData(data2, cfg);
    const legendItems = selectedLegendItems.length > 0 ? selectedLegendItems : legendItemsForData(data2, cfg.fallbackColor);

    const usableW = Math.max(1, widthPx - leftMarginPx - cfg.rightMargin);
    const maxTextW = measureMaxLegendTextWidth(legendItems, legendFontSize, cfg.legendFontFamily);

    const sampleLinePx = Math.max(cfg.sampleLineMinPx, Math.round(cfg.sampleLineMult * legendFontSize));
    const sampleGapPx = Math.max(cfg.sampleGapMinPx, Math.round(cfg.sampleGapMult * legendFontSize));
    const textPadPx = Math.max(cfg.textPadMinPx, Math.round(cfg.textPadMult * legendFontSize));
    const neededEntryPx = Math.ceil(sampleLinePx + sampleGapPx + maxTextW + textPadPx);
    const entryPx = Math.max(1, Math.max(cfg.legendEntryWidth, neededEntryPx));

    const cols = Math.max(1, Math.floor(usableW / entryPx));
    const rows = Math.ceil(legendItems.length / cols);
    const legendH = (rows * legendRowH) + cfg.legendPad + Math.ceil(cfg.tailFontMult * legendFontSize);
    const newHeight = cfg.plotHeight + cfg.topMargin + cfg.bottomAxis + legendH;
    const newMarginB = cfg.bottomAxis + legendH;

    const container = document.getElementById("exp-plot");
    if (!container) return;
    container.style.width = `${widthPx}px`;
    container.style.height = `${newHeight}px`;

    const baseLayout = Object.assign({}, gd.layout || {});
    baseLayout.width = widthPx;
    baseLayout.height = newHeight;
    baseLayout.autosize = false;
    baseLayout.margin = Object.assign({}, baseLayout.margin || {});
    baseLayout.margin.t = cfg.topMargin;
    baseLayout.margin.l = leftMarginPx;
    baseLayout.margin.r = cfg.rightMargin;
    baseLayout.margin.b = newMarginB;
    baseLayout.showlegend = false;
    for (const tr of data2) {
      tr.showlegend = false;
    }

    const ann = Array.isArray(baseLayout.annotations) ? baseLayout.annotations.slice() : [];
    const shp = Array.isArray(baseLayout.shapes) ? baseLayout.shapes.slice() : [];
    const colW = usableW / cols;
    const xPadPx = Math.max(0, Math.min(cfg.colPaddingMaxPx, Math.floor(colW * cfg.colPaddingFrac)));

    for (let i = 0; i < legendItems.length; i++) {
      const row = Math.floor(i / cols);
      const col = i % cols;
      const x0 = (col * colW + xPadPx) / usableW;
      const x1 = x0 + (sampleLinePx / usableW);
      const y = -(cfg.bottomAxis + cfg.legendPad + (row + cfg.rowYOffset) * legendRowH) / Math.max(1, cfg.plotHeight);
      shp.push({
        type: "line",
        xref: "paper",
        yref: "paper",
        x0, x1,
        y0: y, y1: y,
        line: { color: legendItems[i].color, width: 2 },
      });
      ann.push({
        xref: "paper",
        yref: "paper",
        x: x1 + (sampleGapPx / usableW),
        y,
        xanchor: "left",
        yanchor: "middle",
        showarrow: false,
        align: "left",
        text: legendItems[i].name,
        font: { size: legendFontSize, family: cfg.legendFontFamily, color: cfg.legendFontColor },
      });
    }

    baseLayout.annotations = ann;
    baseLayout.shapes = shp;

    await Plotly.newPlot(container, data2, baseLayout, { displayModeBar: false, staticPlot: true });
    const url = await Plotly.toImage(container, {
      format: "png",
      width: widthPx,
      height: newHeight,
      scale: cfg.scale,
    });
    const a = document.createElement("a");
    a.href = url;
    a.download = cfg.filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } catch (e) {
    debugWarn("doExport", e);
  } finally {
    resetExportContainer();
  }
}

window.addEventListener("message", (event) => {
  const data = event && event.data ? event.data : null;
  if (!data || data.type !== "streamlit:render") return;
  latestArgs = data.args || {};
  render();
});

sendToStreamlit("streamlit:componentReady", { apiVersion: 1 });
sendToStreamlit("streamlit:setFrameHeight", { height: 28 });

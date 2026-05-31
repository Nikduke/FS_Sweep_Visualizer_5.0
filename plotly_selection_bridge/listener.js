const CASE_UI_STORE_GLOBAL = "__fsCaseUiStore";
const CASE_UI_STATE_EVENT = "fsCaseUiStateChanged";

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

let latestArgs = null;
let applyPassNonce = 0;
let applyQueued = false;
let lastRenderNonceSeen = -1;
let lastSentFrameHeight = 0;
let plotDivCacheKey = "";
let plotDivCache = [];

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
    console.warn(`[fs-selection-bridge] ${scope}`, err);
  } catch (e) {
    // Debug logging must never affect the Streamlit component.
  }
}

function rootWindow() {
  return window.parent || window;
}

function getStateStore() {
  const root = rootWindow();
  if (!root[CASE_UI_STORE_GLOBAL] || typeof root[CASE_UI_STORE_GLOBAL] !== "object") {
    root[CASE_UI_STORE_GLOBAL] = {};
  }
  return root[CASE_UI_STORE_GLOBAL];
}

function pruneStoreByStateKey(store, stateKey) {
  if (!store || typeof store !== "object") return;
  const keep = String(stateKey || "");
  if (!keep) return;
  for (const k of Object.keys(store)) {
    if (k !== keep) {
      delete store[k];
    }
  }
}

function pruneStoreByDataId(store, dataId) {
  if (!store || typeof store !== "object") return;
  const did = String(dataId || "");
  if (!did) return;
  for (const k of Object.keys(store)) {
    if (!k.startsWith(`${did}|`)) {
      delete store[k];
    }
  }
}

function asArray(v) {
  return Array.isArray(v) ? v : [];
}

function escapeHtml(txt) {
  return String(txt == null ? "" : txt)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function displayValue(v) {
  return String(v) === "" ? "<empty>" : String(v);
}

function normalizeCaseMeta(rawItems) {
  const out = [];
  for (const item of asArray(rawItems)) {
    if (!item || typeof item !== "object") continue;
    const caseId = String(item.case_id || "");
    if (!caseId) continue;
    const displayCase = String(item.display_case || caseId);
    const parts = asArray(item.parts).map((v) => String(v || ""));
    out.push({
      case_id: caseId,
      display_case: displayCase,
      parts,
    });
  }
  return out;
}

function buildPartOptions(casesMeta, partCount) {
  const out = [];
  for (let i = 0; i < partCount; i++) {
    const vals = new Set();
    for (const item of casesMeta) {
      vals.add(String((item.parts && item.parts[i]) || ""));
    }
    out.push(Array.from(vals).sort((a, b) => a.localeCompare(b)));
  }
  return out;
}

function bumpStateVersion(state) {
  const cur = Number(state && state.__applyVersion != null ? state.__applyVersion : 0);
  const next = Number.isFinite(cur) ? cur + 1 : 1;
  if (state && typeof state === "object") {
    state.__applyVersion = next;
  }
  return next;
}

function toStrictBool(rawVal, fallbackVal) {
  if (rawVal === true || rawVal === false) return rawVal;
  if (rawVal === 1 || rawVal === "1" || rawVal === "true" || rawVal === "TRUE") return true;
  if (rawVal === 0 || rawVal === "0" || rawVal === "false" || rawVal === "FALSE") return false;
  return Boolean(fallbackVal);
}

function normalizeTopN(rawVal) {
  const n = Number(rawVal);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.max(0, Math.floor(n));
}

function notifySelectionStateChanged(ctx, detailExtra) {
  if (!ctx) return;
  try {
    const root = rootWindow();
    if (!root || !root.dispatchEvent) return;
    const stateKey = `${String(ctx.dataId || "")}|${String(ctx.chartId || "")}`;
    const version = Number(ctx && ctx.state && ctx.state.__applyVersion != null ? ctx.state.__applyVersion : 0);
    const detail = { stateKey, version };
    if (detailExtra && typeof detailExtra === "object") Object.assign(detail, detailExtra);
    const EventCtor = root.CustomEvent || CustomEvent;
    root.dispatchEvent(
      new EventCtor(CASE_UI_STATE_EVENT, {
        detail,
      }),
    );
  } catch (e) {
    debugWarn("notifySelectionStateChanged", e);
  }
}

function preselectionThresholdDefaults() {
  const fallback = { t2: 400, t3: 600, t4: 2400 };
  const t2 = Number(latestArgs && latestArgs.energinet_t2_default != null ? latestArgs.energinet_t2_default : fallback.t2);
  const t3 = Number(latestArgs && latestArgs.energinet_t3_default != null ? latestArgs.energinet_t3_default : fallback.t3);
  const t4 = Number(latestArgs && latestArgs.energinet_t4_default != null ? latestArgs.energinet_t4_default : fallback.t4);
  return {
    t2: Number.isFinite(t2) && t2 > 0 ? t2 : fallback.t2,
    t3: Number.isFinite(t3) && t3 > 0 ? t3 : fallback.t3,
    t4: Number.isFinite(t4) && t4 > 0 ? t4 : fallback.t4,
  };
}

function toKnownCaseSet(rawVal, knownCaseIds) {
  const out = new Set();
  const src = rawVal instanceof Set ? Array.from(rawVal) : (Array.isArray(rawVal) ? rawVal : []);
  for (const v of src) {
    const cid = String(v || "");
    if (cid && knownCaseIds.has(cid)) out.add(cid);
  }
  return out;
}

function createDefaultState(partOptions, colorByOptions, colorByDefault, showOnlyDefault, baseFreqOptions, baseFreqDefault) {
  const selectedByPart = partOptions.map((opts) => new Set(opts));
  const validDefaultColor = colorByOptions.includes(String(colorByDefault || ""))
    ? String(colorByDefault)
    : String(colorByOptions[0] || "Auto");
  const baseOptions = Array.isArray(baseFreqOptions) && baseFreqOptions.length ? baseFreqOptions : [50, 60];
  const baseDefault = Number(baseFreqDefault || 50);
  const validBase = baseOptions.includes(baseDefault) ? baseDefault : Number(baseOptions[0] || 50);
  const th = preselectionThresholdDefaults();
  return {
    selectedByPart,
    manualSelectedCases: new Set(),
    methodExcludedCases: new Set(),
    methodEnerginetEnabled: false,
    methodIecEnabled: false,
    methodIecCapacitiveOnly: false,
    methodPeakZEnabled: false,
    methodPeakZCapacitiveOnly: false,
    methodPeakZExactEnabled: true,
    methodPeakZBandEnabled: false,
    methodPeakXEnabled: false,
    methodPeakXCapacitiveOnly: false,
    methodPeakXExactEnabled: true,
    methodPeakXBandEnabled: false,
    methodRiskEnabled: false,
    methodRiskCapacitiveOnly: false,
    methodOutlierEnabled: false,
    methodOutlierCapacitiveOnly: false,
    energinetT2: Number(th.t2),
    energinetT3: Number(th.t3),
    energinetT4: Number(th.t4),
    methodEnerginetTopN: 0,
    methodIecTopN: 0,
    methodPeakZTopN: 10,
    methodPeakXTopN: 10,
    methodRiskTopN: 10,
    methodOutlierTopN: 10,
    methodEnerginetCasesRaw: new Set(),
    methodIecCasesRaw: new Set(),
    methodIecCasesRawAll: new Set(),
    methodIecCasesRawCapacitive: new Set(),
    methodPeakZCasesRaw: new Set(),
    methodPeakZCasesRawAll: new Set(),
    methodPeakZCasesRawCapacitive: new Set(),
    methodPeakZExactCasesRawAll: new Set(),
    methodPeakZExactCasesRawCapacitive: new Set(),
    methodPeakZBandCasesRawAll: new Set(),
    methodPeakZBandCasesRawCapacitive: new Set(),
    methodPeakXCasesRaw: new Set(),
    methodPeakXCasesRawAll: new Set(),
    methodPeakXCasesRawCapacitive: new Set(),
    methodPeakXExactCasesRawAll: new Set(),
    methodPeakXExactCasesRawCapacitive: new Set(),
    methodPeakXBandCasesRawAll: new Set(),
    methodPeakXBandCasesRawCapacitive: new Set(),
    methodRiskCasesRaw: new Set(),
    methodRiskCasesRawAll: new Set(),
    methodRiskCasesRawCapacitive: new Set(),
    methodOutlierCasesRaw: new Set(),
    methodOutlierCasesRawAll: new Set(),
    methodOutlierCasesRawCapacitive: new Set(),
    selectedCases: new Set(),
    colorBy: validDefaultColor,
    baseFrequencyHz: validBase,
    showOnlySelected: toStrictBool(showOnlyDefault, false),
    showHarmonics: Boolean(latestArgs && latestArgs.show_harmonics_default),
    binWidthHz: Number(latestArgs && latestArgs.bin_width_hz_default ? latestArgs.bin_width_hz_default : 0),
    importStatus: "",
    __applyVersion: 1,
    __version: 1,
    __resetToken: 0,
    __methodRawCacheKey: "",
  };
}

function sanitizeState(state, casesMeta, partOptions, colorByOptions, colorByDefault, baseFreqOptions, baseFreqDefault) {
  const knownCaseIds = new Set(casesMeta.map((x) => String(x.case_id)));
  const next = state && typeof state === "object" ? state : {};

  next.manualSelectedCases = toKnownCaseSet(
    next.manualSelectedCases != null ? next.manualSelectedCases : next.selectedCases,
    knownCaseIds,
  );
  next.methodExcludedCases = toKnownCaseSet(next.methodExcludedCases, knownCaseIds);
  next.selectedCases = toKnownCaseSet(next.selectedCases, knownCaseIds);
  next.methodEnerginetCasesRaw = toKnownCaseSet(next.methodEnerginetCasesRaw, knownCaseIds);
  next.methodIecCasesRaw = toKnownCaseSet(next.methodIecCasesRaw, knownCaseIds);
  next.methodIecCasesRawAll = toKnownCaseSet(next.methodIecCasesRawAll, knownCaseIds);
  next.methodIecCasesRawCapacitive = toKnownCaseSet(next.methodIecCasesRawCapacitive, knownCaseIds);
  next.methodPeakZCasesRaw = toKnownCaseSet(next.methodPeakZCasesRaw, knownCaseIds);
  next.methodPeakZCasesRawAll = toKnownCaseSet(next.methodPeakZCasesRawAll, knownCaseIds);
  next.methodPeakZCasesRawCapacitive = toKnownCaseSet(next.methodPeakZCasesRawCapacitive, knownCaseIds);
  next.methodPeakZExactCasesRawAll = toKnownCaseSet(next.methodPeakZExactCasesRawAll, knownCaseIds);
  next.methodPeakZExactCasesRawCapacitive = toKnownCaseSet(next.methodPeakZExactCasesRawCapacitive, knownCaseIds);
  next.methodPeakZBandCasesRawAll = toKnownCaseSet(next.methodPeakZBandCasesRawAll, knownCaseIds);
  next.methodPeakZBandCasesRawCapacitive = toKnownCaseSet(next.methodPeakZBandCasesRawCapacitive, knownCaseIds);
  next.methodPeakXCasesRaw = toKnownCaseSet(next.methodPeakXCasesRaw, knownCaseIds);
  next.methodPeakXCasesRawAll = toKnownCaseSet(next.methodPeakXCasesRawAll, knownCaseIds);
  next.methodPeakXCasesRawCapacitive = toKnownCaseSet(next.methodPeakXCasesRawCapacitive, knownCaseIds);
  next.methodPeakXExactCasesRawAll = toKnownCaseSet(next.methodPeakXExactCasesRawAll, knownCaseIds);
  next.methodPeakXExactCasesRawCapacitive = toKnownCaseSet(next.methodPeakXExactCasesRawCapacitive, knownCaseIds);
  next.methodPeakXBandCasesRawAll = toKnownCaseSet(next.methodPeakXBandCasesRawAll, knownCaseIds);
  next.methodPeakXBandCasesRawCapacitive = toKnownCaseSet(next.methodPeakXBandCasesRawCapacitive, knownCaseIds);
  next.methodRiskCasesRaw = toKnownCaseSet(next.methodRiskCasesRaw, knownCaseIds);
  next.methodRiskCasesRawAll = toKnownCaseSet(next.methodRiskCasesRawAll, knownCaseIds);
  next.methodRiskCasesRawCapacitive = toKnownCaseSet(next.methodRiskCasesRawCapacitive, knownCaseIds);
  next.methodOutlierCasesRaw = toKnownCaseSet(next.methodOutlierCasesRaw, knownCaseIds);
  next.methodOutlierCasesRawAll = toKnownCaseSet(next.methodOutlierCasesRawAll, knownCaseIds);
  next.methodOutlierCasesRawCapacitive = toKnownCaseSet(next.methodOutlierCasesRawCapacitive, knownCaseIds);

  const selectedByPart = [];
  const rawByPart = Array.isArray(next.selectedByPart) ? next.selectedByPart : [];
  for (let i = 0; i < partOptions.length; i++) {
    const opts = partOptions[i];
    const allowed = new Set(opts);
    const rawPart = rawByPart[i];
    const rawVals =
      rawPart instanceof Set ? Array.from(rawPart) : Array.isArray(rawPart) ? rawPart.map((v) => String(v || "")) : opts;
    const setPart = new Set();
    for (const v of rawVals) {
      const s = String(v || "");
      if (allowed.has(s)) setPart.add(s);
    }
    selectedByPart.push(setPart);
  }
  next.selectedByPart = selectedByPart;

  const fallbackColor = colorByOptions.includes(String(colorByDefault || ""))
    ? String(colorByDefault)
    : String(colorByOptions[0] || "Auto");
  next.colorBy = colorByOptions.includes(String(next.colorBy || "")) ? String(next.colorBy) : fallbackColor;
  const baseOptions = Array.isArray(baseFreqOptions) && baseFreqOptions.length ? baseFreqOptions : [50, 60];
  const baseDefault = Number(baseFreqDefault || 50);
  const rawBase = Number(next.baseFrequencyHz != null ? next.baseFrequencyHz : baseDefault);
  next.baseFrequencyHz = baseOptions.includes(rawBase) ? rawBase : (baseOptions.includes(baseDefault) ? baseDefault : Number(baseOptions[0] || 50));
  next.methodEnerginetEnabled = Boolean(next.methodEnerginetEnabled);
  next.methodIecEnabled = Boolean(next.methodIecEnabled);
  next.methodIecCapacitiveOnly = Boolean(next.methodIecCapacitiveOnly);
  next.methodPeakZEnabled = Boolean(next.methodPeakZEnabled);
  next.methodPeakZCapacitiveOnly = Boolean(next.methodPeakZCapacitiveOnly);
  next.methodPeakZExactEnabled = next.methodPeakZExactEnabled == null ? true : Boolean(next.methodPeakZExactEnabled);
  next.methodPeakZBandEnabled = Boolean(next.methodPeakZBandEnabled);
  next.methodPeakXEnabled = Boolean(next.methodPeakXEnabled);
  next.methodPeakXCapacitiveOnly = Boolean(next.methodPeakXCapacitiveOnly);
  next.methodPeakXExactEnabled = next.methodPeakXExactEnabled == null ? true : Boolean(next.methodPeakXExactEnabled);
  next.methodPeakXBandEnabled = Boolean(next.methodPeakXBandEnabled);
  next.methodRiskEnabled = Boolean(next.methodRiskEnabled);
  next.methodRiskCapacitiveOnly = Boolean(next.methodRiskCapacitiveOnly);
  next.methodOutlierEnabled = Boolean(next.methodOutlierEnabled);
  next.methodOutlierCapacitiveOnly = Boolean(next.methodOutlierCapacitiveOnly);
  if (!next.methodIecEnabled) {
    next.methodIecCapacitiveOnly = false;
  }
  if (!next.methodPeakZEnabled) next.methodPeakZCapacitiveOnly = false;
  if (!next.methodPeakXEnabled) next.methodPeakXCapacitiveOnly = false;
  if (!next.methodRiskEnabled) next.methodRiskCapacitiveOnly = false;
  if (!next.methodOutlierEnabled) next.methodOutlierCapacitiveOnly = false;
  const th = preselectionThresholdDefaults();
  const t2 = Number(next.energinetT2 != null ? next.energinetT2 : th.t2);
  const t3 = Number(next.energinetT3 != null ? next.energinetT3 : th.t3);
  const t4 = Number(next.energinetT4 != null ? next.energinetT4 : th.t4);
  next.energinetT2 = Number.isFinite(t2) && t2 > 0 ? t2 : Number(th.t2);
  next.energinetT3 = Number.isFinite(t3) && t3 > 0 ? t3 : Number(th.t3);
  next.energinetT4 = Number.isFinite(t4) && t4 > 0 ? t4 : Number(th.t4);
  next.methodEnerginetTopN = normalizeTopN(next.methodEnerginetTopN);
  next.methodIecTopN = normalizeTopN(next.methodIecTopN);
  next.methodPeakZTopN = next.methodPeakZTopN == null ? 10 : normalizeTopN(next.methodPeakZTopN);
  next.methodPeakXTopN = next.methodPeakXTopN == null ? 10 : normalizeTopN(next.methodPeakXTopN);
  next.methodRiskTopN = next.methodRiskTopN == null ? 10 : normalizeTopN(next.methodRiskTopN);
  next.methodOutlierTopN = next.methodOutlierTopN == null ? 10 : normalizeTopN(next.methodOutlierTopN);
  next.showOnlySelected = toStrictBool(next.showOnlySelected, false);
  next.showHarmonics = Boolean(next.showHarmonics);
  const bw = Number(next.binWidthHz || 0);
  next.binWidthHz = Number.isFinite(bw) && bw >= 0 ? bw : 0;
  const ver = Number(next.__applyVersion != null ? next.__applyVersion : 1);
  next.__applyVersion = Number.isFinite(ver) && ver >= 1 ? Math.floor(ver) : 1;
  next.importStatus = String(next.importStatus || "");
  next.__methodRawCacheKey = String(next.__methodRawCacheKey || "");
  next.__version = 1;
  return next;
}

function ensureContext() {
  if (!latestArgs) return null;
  const dataId = String(latestArgs.data_id || "");
  const chartId = String(latestArgs.chart_id || "");
  const resetToken = Number(latestArgs.reset_token || 0);
  const casesMeta = normalizeCaseMeta(latestArgs.cases_meta);
  const partLabels = asArray(latestArgs.part_labels).map((v) => String(v || ""));
  const partCount = partLabels.length;
  const partOptions = buildPartOptions(casesMeta, partCount);
  if (!dataId || !chartId || casesMeta.length === 0 || partCount <= 0) {
    return null;
  }
  const colorByOptions = asArray(latestArgs.color_by_options).map((v) => String(v || "")).filter((v) => v !== "");
  const colorOptions = colorByOptions.length ? colorByOptions : ["Auto"];
  const colorByDefault = String(latestArgs.color_by_default || "Auto");
  const showOnlyDefault = Boolean(latestArgs.show_only_default);
  const serverBaseRaw = Number(latestArgs && latestArgs.f_base != null ? latestArgs.f_base : 50);
  const serverBase = Number.isFinite(serverBaseRaw) && serverBaseRaw > 0 ? serverBaseRaw : 50.0;
  const baseFreqOptions = [Number(serverBase)];
  const baseFreqDefault = Number(serverBase);
  const selectionResetToken = Number(latestArgs.selection_reset_token || 0);
  const stateKey = `${dataId}|${chartId}`;
  const store = getStateStore();
  pruneStoreByStateKey(store, stateKey);
  const prev = store[stateKey];
  let state;
  if (!prev || Number(prev.__resetToken || 0) !== resetToken || Number(prev.__version || 0) !== 1) {
    state = createDefaultState(partOptions, colorOptions, colorByDefault, showOnlyDefault, baseFreqOptions, baseFreqDefault);
  } else {
    state = sanitizeState(prev, casesMeta, partOptions, colorOptions, colorByDefault, baseFreqOptions, baseFreqDefault);
  }

  const prevSelReset = Number(state && state.__selectionResetToken != null ? state.__selectionResetToken : 0);
  if (prevSelReset !== selectionResetToken) {
    state.manualSelectedCases = new Set();
    state.methodExcludedCases = new Set();
    state.methodEnerginetEnabled = false;
    state.methodIecEnabled = false;
    state.methodIecCapacitiveOnly = false;
    state.methodPeakZEnabled = false;
    state.methodPeakZCapacitiveOnly = false;
    state.methodPeakZExactEnabled = true;
    state.methodPeakZBandEnabled = false;
    state.methodPeakXEnabled = false;
    state.methodPeakXCapacitiveOnly = false;
    state.methodPeakXExactEnabled = true;
    state.methodPeakXBandEnabled = false;
    state.methodRiskEnabled = false;
    state.methodRiskCapacitiveOnly = false;
    state.methodOutlierEnabled = false;
    state.methodOutlierCapacitiveOnly = false;
    state.methodEnerginetCasesRaw = new Set();
    state.methodIecCasesRaw = new Set();
    state.methodIecCasesRawAll = new Set();
    state.methodIecCasesRawCapacitive = new Set();
    state.methodPeakZCasesRaw = new Set();
    state.methodPeakZCasesRawAll = new Set();
    state.methodPeakZCasesRawCapacitive = new Set();
    state.methodPeakZExactCasesRawAll = new Set();
    state.methodPeakZExactCasesRawCapacitive = new Set();
    state.methodPeakZBandCasesRawAll = new Set();
    state.methodPeakZBandCasesRawCapacitive = new Set();
    state.methodPeakXCasesRaw = new Set();
    state.methodPeakXCasesRawAll = new Set();
    state.methodPeakXCasesRawCapacitive = new Set();
    state.methodPeakXExactCasesRawAll = new Set();
    state.methodPeakXExactCasesRawCapacitive = new Set();
    state.methodPeakXBandCasesRawAll = new Set();
    state.methodPeakXBandCasesRawCapacitive = new Set();
    state.methodRiskCasesRaw = new Set();
    state.methodRiskCasesRawAll = new Set();
    state.methodRiskCasesRawCapacitive = new Set();
    state.methodOutlierCasesRaw = new Set();
    state.methodOutlierCasesRawAll = new Set();
    state.methodOutlierCasesRawCapacitive = new Set();
    state.selectedCases = new Set();
    // Force method candidates recomputation after reset-trigger reruns
    // (e.g. spline toggle), otherwise stale cache key can keep raw sets empty.
    state.__methodRawCacheKey = "";
    state.importStatus = "";
    bumpStateVersion(state);
  }
  if (Math.abs(Number(state.baseFrequencyHz || 0) - Number(serverBase)) > 1e-9) {
    state.baseFrequencyHz = Number(serverBase);
    bumpStateVersion(state);
  }
  state.__selectionResetToken = selectionResetToken;
  state.__resetToken = resetToken;
  store[stateKey] = state;

  const caseById = new Map();
  const exactLookup = new Map();
  const displayLookup = new Map();
  for (const item of casesMeta) {
    const cid = String(item.case_id);
    const disp = String(item.display_case || cid);
    caseById.set(cid, item);
    exactLookup.set(cid.toLowerCase(), cid);
    if (!displayLookup.has(disp.toLowerCase())) displayLookup.set(disp.toLowerCase(), []);
    displayLookup.get(disp.toLowerCase()).push(cid);
  }

  const ctx = {
    dataId,
    chartId,
    state,
    casesMeta,
    partLabels,
    partOptions,
    colorOptions,
    caseById,
    exactLookup,
    displayLookup,
  };
  recomputeSelectedCases(ctx);
  return ctx;
}

function getColorMap(ctx) {
  const all = latestArgs && latestArgs.color_maps && typeof latestArgs.color_maps === "object" ? latestArgs.color_maps : {};
  const key = String(ctx.state.colorBy || "Auto");
  const m = all[key];
  if (Array.isArray(m)) {
    const cacheKey = `${key}|${m.length}|${ctx.casesMeta ? ctx.casesMeta.length : 0}`;
    if (!ctx.__colorMapCache || ctx.__colorMapCacheKey !== cacheKey) {
      const built = {};
      const rows = Array.isArray(ctx.casesMeta) ? ctx.casesMeta : [];
      for (let i = 0; i < rows.length; i++) {
        const cid = String(rows[i] && rows[i].case_id != null ? rows[i].case_id : "");
        if (cid) built[cid] = String(m[i] || "#1f77b4");
      }
      ctx.__colorMapCache = built;
      ctx.__colorMapCacheKey = cacheKey;
    }
    return ctx.__colorMapCache && typeof ctx.__colorMapCache === "object" ? ctx.__colorMapCache : {};
  }
  return m && typeof m === "object" ? m : {};
}

function colorForCase(ctx, caseId) {
  const cmap = getColorMap(ctx);
  const c = cmap ? cmap[String(caseId)] : null;
  return c ? String(c) : "#1f77b4";
}

function parseHexColor(raw) {
  const s = String(raw || "").trim();
  const m6 = s.match(/^#([0-9a-fA-F]{6})$/);
  if (m6) {
    const v = m6[1];
    return {
      r: parseInt(v.slice(0, 2), 16),
      g: parseInt(v.slice(2, 4), 16),
      b: parseInt(v.slice(4, 6), 16),
    };
  }
  const m3 = s.match(/^#([0-9a-fA-F]{3})$/);
  if (m3) {
    const v = m3[1];
    return {
      r: parseInt(v[0] + v[0], 16),
      g: parseInt(v[1] + v[1], 16),
      b: parseInt(v[2] + v[2], 16),
    };
  }
  return null;
}

function rgbToHexColor(r, g, b) {
  const clamp = (x) => Math.max(0, Math.min(255, Math.round(Number(x || 0))));
  const toHex = (x) => clamp(x).toString(16).padStart(2, "0");
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

function buildActivePartValueColorMap(ctx) {
  let activeLabel = String(ctx && ctx.state ? ctx.state.colorBy || "" : "");
  if (activeLabel === "Auto") {
    activeLabel = String(latestArgs && latestArgs.auto_color_part_label ? latestArgs.auto_color_part_label : "");
  }
  const partIdx =
    ctx && Array.isArray(ctx.partLabels) ? ctx.partLabels.findIndex((lbl) => String(lbl || "") === activeLabel) : -1;
  if (partIdx < 0) return { partIdx: -1, valueColorMap: new Map() };

  const cmap = getColorMap(ctx);
  const sums = new Map();
  for (const item of asArray(ctx && ctx.casesMeta)) {
    const caseId = String(item && item.case_id ? item.case_id : "");
    if (!caseId) continue;
    const partVal = String((item && item.parts && item.parts[partIdx]) || "");
    const rgb = parseHexColor(cmap && cmap[caseId] ? cmap[caseId] : null);
    if (!rgb) continue;
    const prev = sums.get(partVal) || { r: 0, g: 0, b: 0, n: 0 };
    prev.r += Number(rgb.r || 0);
    prev.g += Number(rgb.g || 0);
    prev.b += Number(rgb.b || 0);
    prev.n += 1;
    sums.set(partVal, prev);
  }

  const valueColorMap = new Map();
  for (const [partVal, agg] of sums.entries()) {
    const n = Number(agg && agg.n ? agg.n : 0);
    if (!(n > 0)) continue;
    valueColorMap.set(
      String(partVal || ""),
      rgbToHexColor(Number(agg.r || 0) / n, Number(agg.g || 0) / n, Number(agg.b || 0) / n),
    );
  }
  return { partIdx, valueColorMap };
}

function computeAllowedSet(ctx) {
  const allowed = new Set();
  for (const item of ctx.casesMeta) {
    let ok = true;
    for (let i = 0; i < ctx.partOptions.length; i++) {
      const sel = ctx.state.selectedByPart[i];
      if (!(sel instanceof Set) || sel.size === 0) {
        ok = false;
        break;
      }
      const partVal = String((item.parts && item.parts[i]) || "");
      if (!sel.has(partVal)) {
        ok = false;
        break;
      }
    }
    if (ok) allowed.add(String(item.case_id));
  }
  return allowed;
}

function getPreselectionPayload() {
  const p = latestArgs && latestArgs.preselection_payload && typeof latestArgs.preselection_payload === "object"
    ? latestArgs.preselection_payload
    : {};
  return p && typeof p === "object" ? p : {};
}

function getPreselectionForBase(ctx) {
  if (!ctx || !ctx.state) return null;
  const payload = getPreselectionPayload();
  if (!payload || !Boolean(payload.available)) return null;
  const byF1 = payload.by_f1 && typeof payload.by_f1 === "object" ? payload.by_f1 : {};
  const baseFromArgs = Number(latestArgs && latestArgs.f_base != null ? latestArgs.f_base : ctx.state.baseFrequencyHz);
  const baseKey = String(Math.round(Number.isFinite(baseFromArgs) ? baseFromArgs : 50));
  const candidate = byF1[baseKey] || null;
  return candidate && typeof candidate === "object" ? candidate : null;
}

function preselectionBaseSignature(baseData) {
  if (!baseData || typeof baseData !== "object") return "";
  const modeLen = (modesName, modeName) => {
    try {
      const modes = baseData[modesName] && typeof baseData[modesName] === "object" ? baseData[modesName] : {};
      const node = modes[modeName] && typeof modes[modeName] === "object" ? modes[modeName] : {};
      return Array.isArray(node.case_idx) ? node.case_idx.length : 0;
    } catch (e) {
      return 0;
    }
  };
  const ids = Array.isArray(baseData.case_ids) ? baseData.case_ids : [];
  return [
    ids.length,
    modeLen("iec_modes", "all"),
    modeLen("iec_modes", "capacitive"),
    modeLen("peak_z_modes", "all"),
    modeLen("peak_z_modes", "capacitive"),
    modeLen("peak_z_band_modes", "all"),
    modeLen("peak_z_band_modes", "capacitive"),
    modeLen("peak_x_modes", "all"),
    modeLen("peak_x_modes", "capacitive"),
    modeLen("peak_x_band_modes", "all"),
    modeLen("peak_x_band_modes", "capacitive"),
    modeLen("risk_modes", "all"),
    modeLen("risk_modes", "capacitive"),
    modeLen("outlier_modes", "all"),
    modeLen("outlier_modes", "capacitive"),
  ].join(":");
}

function getCompactCaseIndexMap(baseData) {
  if (!baseData || typeof baseData !== "object") return new Map();
  if (baseData.__caseIndexById instanceof Map) return baseData.__caseIndexById;
  const ids = Array.isArray(baseData.case_ids) ? baseData.case_ids : [];
  const out = new Map();
  for (let i = 0; i < ids.length; i++) {
    const cid = String(ids[i] || "");
    if (!cid || out.has(cid)) continue;
    out.set(cid, i);
  }
  try {
    baseData.__caseIndexById = out;
  } catch (e) {
    debugWarn("getCompactCaseIndexMap.cache", e);
  }
  return out;
}

function compactEnerginetRow(baseData, caseId) {
  const eng = baseData && baseData.energinet && typeof baseData.energinet === "object" ? baseData.energinet : null;
  if (!eng) return null;
  const idxMap = getCompactCaseIndexMap(baseData);
  const idxRaw = idxMap.get(String(caseId || ""));
  const idx = Number(idxRaw);
  if (!Number.isFinite(idx) || idx < 0) return null;
  const z2Arr = Array.isArray(eng.z2) ? eng.z2 : [];
  const z3Arr = Array.isArray(eng.z3) ? eng.z3 : [];
  const z4Arr = Array.isArray(eng.z4) ? eng.z4 : [];
  return {
    z2: idx < z2Arr.length ? Number(z2Arr[idx]) : Number.NaN,
    z3: idx < z3Arr.length ? Number(z3Arr[idx]) : Number.NaN,
    z4: idx < z4Arr.length ? Number(z4Arr[idx]) : Number.NaN,
  };
}

function isPreselectionAvailable(ctx) {
  return Boolean(getPreselectionForBase(ctx));
}

function computeEnerginetCandidates(ctx) {
  const out = new Set();
  const baseData = getPreselectionForBase(ctx);
  if (!baseData) return out;
  const hasCompactEnerginet = baseData.energinet && typeof baseData.energinet === "object";
  const defaults = preselectionThresholdDefaults();
  const t2 = Number(ctx.state.energinetT2 || defaults.t2);
  const t3 = Number(ctx.state.energinetT3 || defaults.t3);
  const t4 = Number(ctx.state.energinetT4 || defaults.t4);
  const ranked = [];
  for (const item of ctx.casesMeta) {
    const cid = String(item.case_id || "");
    if (!cid) continue;
    let z2 = Number.NaN;
    let z3 = Number.NaN;
    let z4 = Number.NaN;
    if (!hasCompactEnerginet) continue;
    const cRow = compactEnerginetRow(baseData, cid);
    if (!cRow) continue;
    z2 = Number(cRow.z2);
    z3 = Number(cRow.z3);
    z4 = Number(cRow.z4);
    const r2 = Number.isFinite(z2) && Number.isFinite(t2) && t2 > 0 ? z2 / t2 : Number.NaN;
    const r3 = Number.isFinite(z3) && Number.isFinite(t3) && t3 > 0 ? z3 / t3 : Number.NaN;
    const r4 = Number.isFinite(z4) && Number.isFinite(t4) && t4 > 0 ? z4 / t4 : Number.NaN;
    const score = Math.max(
      Number.isFinite(r2) ? r2 : Number.NEGATIVE_INFINITY,
      Number.isFinite(r3) ? r3 : Number.NEGATIVE_INFINITY,
      Number.isFinite(r4) ? r4 : Number.NEGATIVE_INFINITY,
    );
    if (!(score > 1.0)) continue;
    ranked.push({
      caseId: cid,
      score: Number(score),
      z2: Number.isFinite(z2) ? Number(z2) : Number.NEGATIVE_INFINITY,
      z3: Number.isFinite(z3) ? Number(z3) : Number.NEGATIVE_INFINITY,
      z4: Number.isFinite(z4) ? Number(z4) : Number.NEGATIVE_INFINITY,
    });
  }
  ranked.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.z2 !== a.z2) return b.z2 - a.z2;
    if (b.z3 !== a.z3) return b.z3 - a.z3;
    if (b.z4 !== a.z4) return b.z4 - a.z4;
    return String(a.caseId).localeCompare(String(b.caseId));
  });
  const topN = normalizeTopN(ctx && ctx.state ? ctx.state.methodEnerginetTopN : 0);
  const limited = topN > 0 ? ranked.slice(0, topN) : ranked;
  for (const row of limited) out.add(String(row.caseId));
  return out;
}

function getIecModeData(baseData, modeKey) {
  const iecModes = baseData && baseData.iec_modes && typeof baseData.iec_modes === "object" ? baseData.iec_modes : {};
  const key = String(modeKey || "all");
  return iecModes && iecModes[key] && typeof iecModes[key] === "object" ? iecModes[key] : null;
}

function computeIecCandidatesForMode(ctx, modeKey) {
  const out = new Set();
  const baseData = getPreselectionForBase(ctx);
  if (!baseData) return out;
  const modeData = getIecModeData(baseData, String(modeKey || "all"));
  if (!modeData) return out;
  const compactIdx = Array.isArray(modeData.case_idx) ? modeData.case_idx : [];
  const compactOrders = Array.isArray(modeData.vertex_orders) ? modeData.vertex_orders : [];
  const compactZmax = Array.isArray(modeData.vertex_zmax) ? modeData.vertex_zmax : [];
  const baseCaseIds = Array.isArray(baseData.case_ids) ? baseData.case_ids : [];
  if (compactIdx.length <= 0 || baseCaseIds.length <= 0) return out;
  const seen = new Set();
  const totalVertexCountByCase = new Map();
  const rowsByHarmonic = new Map();
  for (let i = 0; i < compactIdx.length; i++) {
    const idxRaw = Number(compactIdx[i]);
    if (!Number.isFinite(idxRaw)) continue;
    const idx = Math.floor(idxRaw);
    if (idx < 0 || idx >= baseCaseIds.length) continue;
    const cid = String(baseCaseIds[idx] || "");
    if (!cid || seen.has(cid) || !ctx.caseById.has(cid)) continue;
    seen.add(cid);
    const ordersRaw = Array.isArray(compactOrders[i]) ? compactOrders[i] : [];
    const finiteOrders = ordersRaw
      .map((v) => Number(v))
      .filter((v) => Number.isFinite(v) && v >= 1)
      .map((v) => Math.floor(v));
    const zmaxRaw = Array.isArray(compactZmax[i]) ? compactZmax[i] : [];
    totalVertexCountByCase.set(cid, finiteOrders.length);
    for (let j = 0; j < finiteOrders.length; j++) {
      const harmonic = finiteOrders[j];
      const zmax = Number.isFinite(Number(zmaxRaw[j])) ? Number(zmaxRaw[j]) : 0;
      if (!rowsByHarmonic.has(harmonic)) rowsByHarmonic.set(harmonic, []);
      rowsByHarmonic.get(harmonic).push({ caseId: cid, harmonic, zmax });
    }
  }
  const sortRows = (a, b) => {
    if (b.zmax !== a.zmax) return b.zmax - a.zmax;
    const av = Number(totalVertexCountByCase.get(a.caseId) || 0);
    const bv = Number(totalVertexCountByCase.get(b.caseId) || 0);
    if (bv !== av) return bv - av;
    return String(a.caseId).localeCompare(String(b.caseId));
  };
  const topN = normalizeTopN(ctx && ctx.state ? ctx.state.methodIecTopN : 0);
  const harmonics = Array.from(rowsByHarmonic.keys()).sort((a, b) => a - b);
  for (const harmonic of harmonics) {
    const rows = rowsByHarmonic.get(harmonic) || [];
    rows.sort(sortRows);
    const limited = topN > 0 ? rows.slice(0, topN) : rows;
    for (const row of limited) out.add(String(row.caseId));
  }
  return out;
}

function getRankedModeData(baseData, modesName, modeKey) {
  const modes = baseData && baseData[modesName] && typeof baseData[modesName] === "object" ? baseData[modesName] : {};
  const key = String(modeKey || "all");
  return modes && modes[key] && typeof modes[key] === "object" ? modes[key] : null;
}

function computeRankedModeCandidates(ctx, modesName, modeKey, topNRaw) {
  const out = new Set();
  const baseData = getPreselectionForBase(ctx);
  if (!baseData) return out;
  const modeData = getRankedModeData(baseData, modesName, modeKey);
  if (!modeData) return out;
  const compactIdx = Array.isArray(modeData.case_idx) ? modeData.case_idx : [];
  const compactScores = Array.isArray(modeData.scores) ? modeData.scores : [];
  const compactZmax = Array.isArray(modeData.zmax) ? modeData.zmax : [];
  const compactHarmonics = Array.isArray(modeData.harmonic) ? modeData.harmonic : [];
  const baseCaseIds = Array.isArray(baseData.case_ids) ? baseData.case_ids : [];
  const topNScope = String(modeData.top_n_scope || "global");
  if (compactIdx.length <= 0 || baseCaseIds.length <= 0) return out;

  const rows = [];
  const seen = new Set();
  const seenCases = new Set();
  for (let i = 0; i < compactIdx.length; i++) {
    const idx = Math.floor(Number(compactIdx[i]));
    if (!Number.isFinite(idx) || idx < 0 || idx >= baseCaseIds.length) continue;
    const cid = String(baseCaseIds[idx] || "");
    if (!cid || !ctx.caseById.has(cid)) continue;
    const score = Number(compactScores[i]);
    if (!Number.isFinite(score)) continue;
    const harmonic = Number.isFinite(Number(compactHarmonics[i])) ? Math.floor(Number(compactHarmonics[i])) : 999;
    const seenKey = `${cid}|${harmonic}`;
    if (seen.has(seenKey)) continue;
    if (topNScope !== "per_harmonic" && seenCases.has(cid)) continue;
    seen.add(seenKey);
    seenCases.add(cid);
    rows.push({
      caseId: cid,
      score,
      zmax: Number.isFinite(Number(compactZmax[i])) ? Number(compactZmax[i]) : 0,
      harmonic,
    });
  }
  const sortRows = (a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.zmax !== a.zmax) return b.zmax - a.zmax;
    if (a.harmonic !== b.harmonic) return a.harmonic - b.harmonic;
    return String(a.caseId).localeCompare(String(b.caseId));
  };
  const topN = normalizeTopN(topNRaw);
  if (topNScope === "per_harmonic" && topN > 0) {
    const byHarmonic = new Map();
    for (const row of rows) {
      const key = String(row.harmonic);
      if (!byHarmonic.has(key)) byHarmonic.set(key, []);
      byHarmonic.get(key).push(row);
    }
    for (const group of byHarmonic.values()) {
      group.sort(sortRows);
      for (const row of group.slice(0, topN)) out.add(String(row.caseId));
    }
    return out;
  }
  rows.sort(sortRows);
  const limited = topN > 0 ? rows.slice(0, topN) : rows;
  for (const row of limited) out.add(String(row.caseId));
  return out;
}

function isCaseSelectedByActiveMethod(state, caseId) {
  if (!state || !caseId) return false;
  const excluded = state.methodExcludedCases instanceof Set ? state.methodExcludedCases : new Set();
  if (excluded.has(caseId)) return false;
  const energinetSet = state.methodEnerginetCasesRaw instanceof Set ? state.methodEnerginetCasesRaw : new Set();
  const iecSet = state.methodIecCasesRaw instanceof Set ? state.methodIecCasesRaw : new Set();
  const peakZSet = state.methodPeakZCasesRaw instanceof Set ? state.methodPeakZCasesRaw : new Set();
  const peakXSet = state.methodPeakXCasesRaw instanceof Set ? state.methodPeakXCasesRaw : new Set();
  const riskSet = state.methodRiskCasesRaw instanceof Set ? state.methodRiskCasesRaw : new Set();
  const outlierSet = state.methodOutlierCasesRaw instanceof Set ? state.methodOutlierCasesRaw : new Set();
  if (Boolean(state.methodEnerginetEnabled) && energinetSet.has(caseId)) return true;
  if (Boolean(state.methodIecEnabled) && iecSet.has(caseId)) return true;
  if (Boolean(state.methodPeakZEnabled) && peakZSet.has(caseId)) return true;
  if (Boolean(state.methodPeakXEnabled) && peakXSet.has(caseId)) return true;
  if (Boolean(state.methodRiskEnabled) && riskSet.has(caseId)) return true;
  if (Boolean(state.methodOutlierEnabled) && outlierSet.has(caseId)) return true;
  return false;
}

function unionEnabledSources(exactSet, bandSet, exactEnabled, bandEnabled) {
  const out = new Set();
  if (exactEnabled === true && exactSet instanceof Set) {
    for (const cid of exactSet) out.add(String(cid));
  }
  if (bandEnabled === true && bandSet instanceof Set) {
    for (const cid of bandSet) out.add(String(cid));
  }
  return out;
}

function recomputeSelectedCases(ctx) {
  if (!ctx || !ctx.state) return;
  const st = ctx.state;
  const excluded = st.methodExcludedCases instanceof Set ? st.methodExcludedCases : new Set();
  const baseFromArgs = Number(latestArgs && latestArgs.f_base != null ? latestArgs.f_base : st.baseFrequencyHz);
  const baseData = getPreselectionForBase(ctx);
  const iecModeKey = Boolean(st.methodIecCapacitiveOnly) ? "capacitive" : "all";
  const peakZModeKey = Boolean(st.methodPeakZCapacitiveOnly) ? "capacitive" : "all";
  const peakXModeKey = Boolean(st.methodPeakXCapacitiveOnly) ? "capacitive" : "all";
  const riskModeKey = Boolean(st.methodRiskCapacitiveOnly) ? "capacitive" : "all";
  const outlierModeKey = Boolean(st.methodOutlierCapacitiveOnly) ? "capacitive" : "all";
  const cacheKey = [
    Number.isFinite(baseFromArgs) ? Number(baseFromArgs) : 0,
    preselectionBaseSignature(baseData),
    Number(st.energinetT2 || 0),
    Number(st.energinetT3 || 0),
    Number(st.energinetT4 || 0),
    Number(st.methodEnerginetTopN || 0),
    Number(st.methodIecTopN || 0),
    Number(st.methodPeakZTopN || 0),
    Number(st.methodPeakXTopN || 0),
    Number(st.methodRiskTopN || 0),
    Number(st.methodOutlierTopN || 0),
  ].join("|");

  let rawEnerginet = st.methodEnerginetCasesRaw instanceof Set ? st.methodEnerginetCasesRaw : new Set();
  let rawIecAll = st.methodIecCasesRawAll instanceof Set ? st.methodIecCasesRawAll : new Set();
  let rawIecCapacitive = st.methodIecCasesRawCapacitive instanceof Set ? st.methodIecCasesRawCapacitive : new Set();
  let rawPeakZAll = st.methodPeakZCasesRawAll instanceof Set ? st.methodPeakZCasesRawAll : new Set();
  let rawPeakZCapacitive = st.methodPeakZCasesRawCapacitive instanceof Set ? st.methodPeakZCasesRawCapacitive : new Set();
  let rawPeakZExactAll = st.methodPeakZExactCasesRawAll instanceof Set ? st.methodPeakZExactCasesRawAll : new Set();
  let rawPeakZExactCapacitive = st.methodPeakZExactCasesRawCapacitive instanceof Set ? st.methodPeakZExactCasesRawCapacitive : new Set();
  let rawPeakZBandAll = st.methodPeakZBandCasesRawAll instanceof Set ? st.methodPeakZBandCasesRawAll : new Set();
  let rawPeakZBandCapacitive = st.methodPeakZBandCasesRawCapacitive instanceof Set ? st.methodPeakZBandCasesRawCapacitive : new Set();
  let rawPeakXAll = st.methodPeakXCasesRawAll instanceof Set ? st.methodPeakXCasesRawAll : new Set();
  let rawPeakXCapacitive = st.methodPeakXCasesRawCapacitive instanceof Set ? st.methodPeakXCasesRawCapacitive : new Set();
  let rawPeakXExactAll = st.methodPeakXExactCasesRawAll instanceof Set ? st.methodPeakXExactCasesRawAll : new Set();
  let rawPeakXExactCapacitive = st.methodPeakXExactCasesRawCapacitive instanceof Set ? st.methodPeakXExactCasesRawCapacitive : new Set();
  let rawPeakXBandAll = st.methodPeakXBandCasesRawAll instanceof Set ? st.methodPeakXBandCasesRawAll : new Set();
  let rawPeakXBandCapacitive = st.methodPeakXBandCasesRawCapacitive instanceof Set ? st.methodPeakXBandCasesRawCapacitive : new Set();
  let rawRiskAll = st.methodRiskCasesRawAll instanceof Set ? st.methodRiskCasesRawAll : new Set();
  let rawRiskCapacitive = st.methodRiskCasesRawCapacitive instanceof Set ? st.methodRiskCasesRawCapacitive : new Set();
  let rawOutlierAll = st.methodOutlierCasesRawAll instanceof Set ? st.methodOutlierCasesRawAll : new Set();
  let rawOutlierCapacitive = st.methodOutlierCasesRawCapacitive instanceof Set ? st.methodOutlierCasesRawCapacitive : new Set();
  const needRecompute =
    String(st.__methodRawCacheKey || "") !== cacheKey
    || !(st.methodEnerginetCasesRaw instanceof Set)
    || !(st.methodIecCasesRawAll instanceof Set)
    || !(st.methodIecCasesRawCapacitive instanceof Set)
    || !(st.methodPeakZCasesRawAll instanceof Set)
    || !(st.methodPeakZCasesRawCapacitive instanceof Set)
    || !(st.methodPeakZExactCasesRawAll instanceof Set)
    || !(st.methodPeakZExactCasesRawCapacitive instanceof Set)
    || !(st.methodPeakZBandCasesRawAll instanceof Set)
    || !(st.methodPeakZBandCasesRawCapacitive instanceof Set)
    || !(st.methodPeakXCasesRawAll instanceof Set)
    || !(st.methodPeakXCasesRawCapacitive instanceof Set)
    || !(st.methodPeakXExactCasesRawAll instanceof Set)
    || !(st.methodPeakXExactCasesRawCapacitive instanceof Set)
    || !(st.methodPeakXBandCasesRawAll instanceof Set)
    || !(st.methodPeakXBandCasesRawCapacitive instanceof Set)
    || !(st.methodRiskCasesRawAll instanceof Set)
    || !(st.methodRiskCasesRawCapacitive instanceof Set)
    || !(st.methodOutlierCasesRawAll instanceof Set)
    || !(st.methodOutlierCasesRawCapacitive instanceof Set);
  if (needRecompute) {
    rawEnerginet = computeEnerginetCandidates(ctx);
    rawIecAll = computeIecCandidatesForMode(ctx, "all");
    rawIecCapacitive = computeIecCandidatesForMode(ctx, "capacitive");
    rawPeakZExactAll = computeRankedModeCandidates(ctx, "peak_z_modes", "all", st.methodPeakZTopN);
    rawPeakZExactCapacitive = computeRankedModeCandidates(ctx, "peak_z_modes", "capacitive", st.methodPeakZTopN);
    rawPeakZBandAll = computeRankedModeCandidates(ctx, "peak_z_band_modes", "all", st.methodPeakZTopN);
    rawPeakZBandCapacitive = computeRankedModeCandidates(ctx, "peak_z_band_modes", "capacitive", st.methodPeakZTopN);
    rawPeakXExactAll = computeRankedModeCandidates(ctx, "peak_x_modes", "all", st.methodPeakXTopN);
    rawPeakXExactCapacitive = computeRankedModeCandidates(ctx, "peak_x_modes", "capacitive", st.methodPeakXTopN);
    rawPeakXBandAll = computeRankedModeCandidates(ctx, "peak_x_band_modes", "all", st.methodPeakXTopN);
    rawPeakXBandCapacitive = computeRankedModeCandidates(ctx, "peak_x_band_modes", "capacitive", st.methodPeakXTopN);
    rawRiskAll = computeRankedModeCandidates(ctx, "risk_modes", "all", st.methodRiskTopN);
    rawRiskCapacitive = computeRankedModeCandidates(ctx, "risk_modes", "capacitive", st.methodRiskTopN);
    rawOutlierAll = computeRankedModeCandidates(ctx, "outlier_modes", "all", st.methodOutlierTopN);
    rawOutlierCapacitive = computeRankedModeCandidates(ctx, "outlier_modes", "capacitive", st.methodOutlierTopN);
    st.methodEnerginetCasesRaw = rawEnerginet;
    st.methodIecCasesRawAll = rawIecAll;
    st.methodIecCasesRawCapacitive = rawIecCapacitive;
    st.methodPeakZExactCasesRawAll = rawPeakZExactAll;
    st.methodPeakZExactCasesRawCapacitive = rawPeakZExactCapacitive;
    st.methodPeakZBandCasesRawAll = rawPeakZBandAll;
    st.methodPeakZBandCasesRawCapacitive = rawPeakZBandCapacitive;
    st.methodPeakXExactCasesRawAll = rawPeakXExactAll;
    st.methodPeakXExactCasesRawCapacitive = rawPeakXExactCapacitive;
    st.methodPeakXBandCasesRawAll = rawPeakXBandAll;
    st.methodPeakXBandCasesRawCapacitive = rawPeakXBandCapacitive;
    st.methodRiskCasesRawAll = rawRiskAll;
    st.methodRiskCasesRawCapacitive = rawRiskCapacitive;
    st.methodOutlierCasesRawAll = rawOutlierAll;
    st.methodOutlierCasesRawCapacitive = rawOutlierCapacitive;
    st.__methodRawCacheKey = cacheKey;
  }
  rawPeakZAll = unionEnabledSources(rawPeakZExactAll, rawPeakZBandAll, Boolean(st.methodPeakZExactEnabled), Boolean(st.methodPeakZBandEnabled));
  rawPeakZCapacitive = unionEnabledSources(rawPeakZExactCapacitive, rawPeakZBandCapacitive, Boolean(st.methodPeakZExactEnabled), Boolean(st.methodPeakZBandEnabled));
  rawPeakXAll = unionEnabledSources(rawPeakXExactAll, rawPeakXBandAll, Boolean(st.methodPeakXExactEnabled), Boolean(st.methodPeakXBandEnabled));
  rawPeakXCapacitive = unionEnabledSources(rawPeakXExactCapacitive, rawPeakXBandCapacitive, Boolean(st.methodPeakXExactEnabled), Boolean(st.methodPeakXBandEnabled));
  st.methodPeakZCasesRawAll = rawPeakZAll;
  st.methodPeakZCasesRawCapacitive = rawPeakZCapacitive;
  st.methodPeakXCasesRawAll = rawPeakXAll;
  st.methodPeakXCasesRawCapacitive = rawPeakXCapacitive;

  const rawIec = iecModeKey === "capacitive" ? rawIecCapacitive : rawIecAll;
  const rawPeakZ = peakZModeKey === "capacitive" ? rawPeakZCapacitive : rawPeakZAll;
  const rawPeakX = peakXModeKey === "capacitive" ? rawPeakXCapacitive : rawPeakXAll;
  const rawRisk = riskModeKey === "capacitive" ? rawRiskCapacitive : rawRiskAll;
  const rawOutlier = outlierModeKey === "capacitive" ? rawOutlierCapacitive : rawOutlierAll;
  st.methodIecCasesRaw = rawIec;
  st.methodPeakZCasesRaw = rawPeakZ;
  st.methodPeakXCasesRaw = rawPeakX;
  st.methodRiskCasesRaw = rawRisk;
  st.methodOutlierCasesRaw = rawOutlier;

  const derived = new Set();
  if (Boolean(st.methodEnerginetEnabled)) {
    for (const cid of rawEnerginet) {
      if (!excluded.has(cid)) derived.add(cid);
    }
  }
  if (Boolean(st.methodIecEnabled)) {
    for (const cid of rawIec) {
      if (!excluded.has(cid)) derived.add(cid);
    }
  }
  if (Boolean(st.methodPeakZEnabled)) {
    for (const cid of rawPeakZ) {
      if (!excluded.has(cid)) derived.add(cid);
    }
  }
  if (Boolean(st.methodPeakXEnabled)) {
    for (const cid of rawPeakX) {
      if (!excluded.has(cid)) derived.add(cid);
    }
  }
  if (Boolean(st.methodRiskEnabled)) {
    for (const cid of rawRisk) {
      if (!excluded.has(cid)) derived.add(cid);
    }
  }
  if (Boolean(st.methodOutlierEnabled)) {
    for (const cid of rawOutlier) {
      if (!excluded.has(cid)) derived.add(cid);
    }
  }
  const manual = st.manualSelectedCases instanceof Set ? st.manualSelectedCases : new Set();
  const selected = new Set(manual);
  for (const cid of derived) selected.add(cid);
  st.selectedCases = selected;
}

function toggleCaseSelectionByCaseId(ctx, caseId) {
  if (!ctx || !ctx.state) return false;
  const cid = String(caseId || "");
  if (!cid || !ctx.caseById || !ctx.caseById.has(cid)) return false;
  const st = ctx.state || {};
  const manual = st.manualSelectedCases instanceof Set ? new Set(st.manualSelectedCases) : new Set();
  const excluded = st.methodExcludedCases instanceof Set ? new Set(st.methodExcludedCases) : new Set();
  const selectedNow = st.selectedCases instanceof Set ? st.selectedCases.has(cid) : false;
  const selectedByMethodNow = isCaseSelectedByActiveMethod(st, cid);

  if (selectedNow) {
    if (manual.has(cid)) manual.delete(cid);
    if (selectedByMethodNow) excluded.add(cid);
  } else {
    manual.add(cid);
    excluded.delete(cid);
  }

  st.manualSelectedCases = manual;
  st.methodExcludedCases = excluded;
  recomputeSelectedCases(ctx);
  bumpStateVersion(ctx.state);
  ctx.state.importStatus = "";
  notifySelectionStateChanged(ctx);
  return true;
}

function caseIdFromCustomData(cd) {
  if (Array.isArray(cd)) {
    if (cd.length >= 1 && cd[0] != null && String(cd[0]) !== "") return String(cd[0]);
    if (cd.length >= 2 && cd[1] != null && String(cd[1]) !== "") return String(cd[1]);
    return "";
  }
  if (cd == null) return "";
  return String(cd);
}

function knownCaseId(ctx, rawValue) {
  const cid = String(rawValue == null ? "" : rawValue);
  if (!cid) return "";
  const known = ctx && ctx.caseById instanceof Map ? ctx.caseById : null;
  if (!known) return cid;
  return known.has(cid) ? cid : "";
}

function knownCaseIdByTraceName(ctx, rawName) {
  const traceName = String(rawName || "");
  if (!traceName) return "";
  const exactNameId = knownCaseId(ctx, traceName);
  if (exactNameId) return exactNameId;
  const dispMap = ctx && ctx.displayLookup instanceof Map ? ctx.displayLookup : null;
  const matches = dispMap ? dispMap.get(traceName.toLowerCase()) : null;
  if (Array.isArray(matches) && matches.length === 1) {
    const only = knownCaseId(ctx, matches[0]);
    if (only) return only;
  }
  return "";
}

function resolveCaseIdFromTrace(ctx, tr) {
  if (!tr || typeof tr !== "object") return "";
  try {
    const meta = tr.meta && typeof tr.meta === "object" ? tr.meta : null;
    const fromMeta = knownCaseId(ctx, meta && meta.case_id != null ? meta.case_id : "");
    if (fromMeta) return fromMeta;
  } catch (e) {
    debugWarn("resolveCaseIdFromTrace.meta", e);
  }
  try {
    const fromName = knownCaseIdByTraceName(ctx, tr.name);
    if (fromName) return fromName;
  } catch (e) {
    debugWarn("resolveCaseIdFromTrace.name", e);
  }
  return "";
}

function caseIdFromEventPoint(ctx, pt, gd) {
  if (!pt || typeof pt !== "object") return "";
  const fromCustom = knownCaseId(ctx, caseIdFromCustomData(pt.customdata));
  if (fromCustom) return fromCustom;
  if (Array.isArray(pt.customdata)) {
    for (let i = 0; i < pt.customdata.length; i++) {
      const c = knownCaseId(ctx, pt.customdata[i]);
      if (c) return c;
    }
  }
  const fromPointId = knownCaseId(ctx, pt.id);
  if (fromPointId) return fromPointId;
  try {
    const dMeta = pt.data && pt.data.meta && typeof pt.data.meta === "object" ? pt.data.meta : null;
    const dId = knownCaseId(ctx, dMeta && dMeta.case_id != null ? dMeta.case_id : "");
    if (dId) return dId;
  } catch (e) {
    debugWarn("caseIdFromEventPoint.dataMeta", e);
  }
  try {
    const fMeta = pt.fullData && pt.fullData.meta && typeof pt.fullData.meta === "object" ? pt.fullData.meta : null;
    const fId = knownCaseId(ctx, fMeta && fMeta.case_id != null ? fMeta.case_id : "");
    if (fId) return fId;
  } catch (e) {
    debugWarn("caseIdFromEventPoint.fullDataMeta", e);
  }
  try {
    const ci = Number(pt.curveNumber);
    if (Number.isFinite(ci) && ci >= 0 && gd && Array.isArray(gd.data) && ci < gd.data.length) {
      const tr = gd.data[ci];
      const meta = tr && tr.meta && typeof tr.meta === "object" ? tr.meta : null;
      const cid = knownCaseId(ctx, meta && meta.case_id != null ? meta.case_id : "");
      if (cid) return cid;
    }
  } catch (e) {
    debugWarn("caseIdFromEventPoint.curveTrace", e);
  }
  try {
    const traceNameRaw = pt.data && pt.data.name != null ? pt.data.name : "";
    const byName = knownCaseIdByTraceName(ctx, traceNameRaw);
    if (byName) return byName;
  } catch (e) {
    debugWarn("caseIdFromEventPoint.traceName", e);
  }
  return "";
}

function getPlotDivs() {
  const renderNonce = Number(latestArgs && latestArgs.render_nonce ? latestArgs.render_nonce : 0);
  const expectedCount = asArray(latestArgs && latestArgs.plot_ids).length;
  const cacheKey = `${String(latestArgs && latestArgs.data_id ? latestArgs.data_id : "")}|${String(latestArgs && latestArgs.chart_id ? latestArgs.chart_id : "")}|${renderNonce}|${expectedCount}`;
  try {
    if (plotDivCacheKey === cacheKey && Array.isArray(plotDivCache) && plotDivCache.length >= expectedCount) {
      const alive = plotDivCache.every((gd) => gd && gd.isConnected !== false);
      if (alive) return plotDivCache;
    }
  } catch (e) {
    debugWarn("getPlotDivs.cache-read", e);
  }
  const out = [];
  try {
    const doc = rootWindow().document;
    const blocks = doc.querySelectorAll('div[data-testid="stPlotlyChart"], div.stPlotlyChart');
    for (const block of blocks) {
      const fr = block.querySelector("iframe");
      if (fr && fr.contentWindow && fr.contentWindow.document) {
        const gd = fr.contentWindow.document.querySelector("div.js-plotly-plot");
        if (gd) {
          out.push(gd);
          continue;
        }
      }
      const gd2 = block.querySelector("div.js-plotly-plot");
      if (gd2) out.push(gd2);
    }
  } catch (e) {
    debugWarn("getPlotDivs", e);
  }
  plotDivCacheKey = cacheKey;
  plotDivCache = out;
  return out;
}

function buildHarmonicShapes(ctx, nMin, nMax, fBase, xUnit) {
  if (!ctx) return [];
  const showMarkers = Boolean(ctx.state.showHarmonics);
  const binWidthHz = Number(ctx.state.binWidthHz || 0);
  if (!showMarkers && !(Number.isFinite(binWidthHz) && binWidthHz > 0)) return [];
  if (!Number.isFinite(nMin) || !Number.isFinite(nMax) || nMin >= nMax) return [];
  if (!Number.isFinite(fBase) || fBase <= 0) return [];
  const out = [];
  const useHzAxis = String(xUnit || "").toLowerCase() === "hz";
  const axisX = (nValue) => (useHzAxis ? Number(nValue) * Number(fBase) : Number(nValue));
  const kStart = Math.max(1, Math.floor(nMin));
  const kEnd = Math.ceil(nMax);
  for (let k = kStart; k <= kEnd; k++) {
    if (showMarkers) {
      const x = axisX(k);
      out.push({
        type: "line",
        xref: "x",
        yref: "paper",
        x0: x,
        x1: x,
        y0: 0,
        y1: 1,
        line: { color: "rgba(0,0,0,0.3)", width: 1.5 },
      });
    }
    if (Number.isFinite(binWidthHz) && binWidthHz > 0) {
      const dn = Number(binWidthHz) / (2.0 * Number(fBase));
      const edges = [k - dn, k + dn].map(axisX);
      for (const edge of edges) {
        out.push({
          type: "line",
          xref: "x",
          yref: "paper",
          x0: edge,
          x1: edge,
          y0: 0,
          y1: 1,
          line: { color: "rgba(0,0,0,0.2)", width: 1, dash: "dot" },
        });
      }
    }
  }
  return out;
}

function isVisibleForCase(caseId, allowedSet, selectedSet, showOnlySelected) {
  if (!allowedSet.has(caseId)) return false;
  if (!showOnlySelected) return true;
  // Preserve toggle state; empty selection means "no selection filter applied".
  if (selectedSet.size === 0) return true;
  return selectedSet.has(caseId);
}

function getLineTraceEntries(ctx, gd) {
  if (!gd || !Array.isArray(gd.data) || !ctx || !ctx.caseById) return [];
  const ctxKey = `${String(ctx.dataId || "")}|${String(ctx.chartId || "")}|${Number(ctx.casesMeta ? ctx.casesMeta.length : 0)}`;
  try {
    const sameRef = gd.__fsLineEntriesDataRef === gd.data;
    const sameCount = Number(gd.__fsLineEntriesCount || 0) === gd.data.length;
    const sameCtx = String(gd.__fsLineEntriesCtxKey || "") === ctxKey;
    if (sameRef && sameCount && sameCtx && Array.isArray(gd.__fsLineEntries)) {
      let allKnown = true;
      for (const row of gd.__fsLineEntries) {
        const cid = String(row && row.caseId != null ? row.caseId : "");
        if (!cid || !ctx.caseById.has(cid)) {
          allKnown = false;
          break;
        }
      }
      if (allKnown) return gd.__fsLineEntries;
    }
  } catch (e) {
    debugWarn("getLineTraceEntries.cache-read", e);
  }

  const entries = [];
  for (let ti = 0; ti < gd.data.length; ti++) {
    const tr = gd.data[ti];
    const caseId = resolveCaseIdFromTrace(ctx, tr);
    if (!caseId) continue;
    entries.push({ traceIndex: ti, caseId });
  }
  try {
    gd.__fsLineEntries = entries;
    gd.__fsLineEntriesDataRef = gd.data;
    gd.__fsLineEntriesCount = gd.data.length;
    gd.__fsLineEntriesCtxKey = ctxKey;
    gd.__fsLineStyleSig = {};
  } catch (e) {
    debugWarn("getLineTraceEntries.cache-write", e);
  }
  return entries;
}

function applyLineStyles(ctx, gd, allowedSet) {
  if (!gd || !Array.isArray(gd.data)) return;
  const win = gd.ownerDocument && gd.ownerDocument.defaultView ? gd.ownerDocument.defaultView : null;
  const Plotly = win && win.Plotly ? win.Plotly : null;
  if (!Plotly || !Plotly.restyle) return;
  const applyToken = Number(ctx.state && ctx.state.__applyVersion != null ? ctx.state.__applyVersion : 0);
  const applyCtxKey = `${String(ctx.dataId || "")}|${String(ctx.chartId || "")}`;
  try {
    const sameToken = Number(gd.__fsLineApplyToken || 0) === applyToken;
    const sameCount = Number(gd.__fsLineTraceCount || 0) === gd.data.length;
    const sameDataRef = gd.__fsLineDataRef === gd.data;
    const sameCtx = String(gd.__fsLineApplyCtxKey || "") === applyCtxKey;
    if (sameToken && sameCount && sameDataRef && sameCtx) return;
  } catch (e) {
    debugWarn("applyLineStyles.noop-check", e);
  }

  try {
    if (String(gd.__fsLineBaseCtxKey || "") !== applyCtxKey) {
      gd.__fsCaseUiBase = {};
      gd.__fsLineStyleSig = {};
      gd.__fsLineBaseCtxKey = applyCtxKey;
    }
  } catch (e) {
    debugWarn("applyLineStyles.base-cache", e);
  }

  const hasSelection = ctx.state.selectedCases.size > 0;
  const showOnlyState = ctx.state && Object.prototype.hasOwnProperty.call(ctx.state, "showOnlySelected")
    ? ctx.state.showOnlySelected
    : false;
  const showOnly = showOnlyState === true && hasSelection;
  const dimLineWidth = Number(latestArgs.dim_line_width || 1.0);
  const dimLineOpacity = Number(latestArgs.dim_line_opacity || 0.35);
  const dimLineColor = String(latestArgs.dim_line_color || "#B8B8B8");
  const selectedLineWidth = Number(latestArgs.selected_line_width || 2.5);

  if (!gd.__fsCaseUiBase) gd.__fsCaseUiBase = {};
  const baseMap = gd.__fsCaseUiBase;
  const entries = getLineTraceEntries(ctx, gd);
  if (!entries.length) return;
  const prevSig = gd.__fsLineStyleSig && typeof gd.__fsLineStyleSig === "object" ? gd.__fsLineStyleSig : {};
  const nextSig = {};

  const changedTraceIndices = [];
  const changedVisibleVals = [];
  const changedLegendVals = [];
  const changedLineColors = [];
  const changedLineWidths = [];
  const changedOpacities = [];

  for (let i = 0; i < entries.length; i++) {
    const ti = Number(entries[i].traceIndex);
    const caseId = String(entries[i].caseId || "");
    const tr = gd.data[ti];
    if (!tr || !caseId) continue;

    if (!baseMap[ti]) {
      const baseLineWidth = tr && tr.line && tr.line.width != null ? Number(tr.line.width) : 2.0;
      const baseOpacity = tr && tr.opacity != null ? Number(tr.opacity) : 1.0;
      baseMap[ti] = {
        lineWidth: baseLineWidth,
        opacity: baseOpacity,
      };
    }
    const base = baseMap[ti];
    const isSelected = ctx.state.selectedCases.has(caseId);
    const visible = isVisibleForCase(caseId, allowedSet, ctx.state.selectedCases, showOnly);
    const legendVisible = visible && (!hasSelection || isSelected);
    const shouldDim = visible && hasSelection && !showOnly && !isSelected;
    const shouldHighlight = visible && hasSelection && isSelected;

    let finalColor = colorForCase(ctx, caseId);
    let finalWidth = Number(base.lineWidth || 2.0);
    let finalOpacity = 1.0;
    if (shouldDim) {
      finalColor = dimLineColor;
      finalWidth = dimLineWidth;
      finalOpacity = dimLineOpacity;
    } else if (shouldHighlight) {
      finalWidth = selectedLineWidth;
      finalOpacity = 1.0;
    } else if (!hasSelection) {
      finalOpacity = Number(base.opacity || 1.0);
    }

    const sig = [
      visible ? 1 : 0,
      legendVisible ? 1 : 0,
      String(finalColor),
      Number(finalWidth).toFixed(4),
      Number(finalOpacity).toFixed(4),
    ].join("|");
    nextSig[String(ti)] = sig;
    if (prevSig[String(ti)] === sig) continue;

    changedTraceIndices.push(ti);
    changedVisibleVals.push(Boolean(visible));
    changedLegendVals.push(Boolean(legendVisible));
    changedLineColors.push(String(finalColor));
    changedLineWidths.push(Number(finalWidth));
    changedOpacities.push(Number(finalOpacity));
  }

  gd.__fsLineStyleSig = nextSig;
  if (!changedTraceIndices.length) {
    gd.__fsLineApplyToken = applyToken;
    gd.__fsLineTraceCount = gd.data.length;
    gd.__fsLineDataRef = gd.data;
    gd.__fsLineApplyCtxKey = applyCtxKey;
    return;
  }
  try {
    Plotly.restyle(
      gd,
      {
        visible: changedVisibleVals,
        showlegend: changedLegendVals,
        "line.color": changedLineColors,
        "line.width": changedLineWidths,
        opacity: changedOpacities,
      },
      changedTraceIndices,
    );
    gd.__fsLineApplyToken = applyToken;
    gd.__fsLineTraceCount = gd.data.length;
    gd.__fsLineDataRef = gd.data;
    gd.__fsLineApplyCtxKey = applyCtxKey;
  } catch (e) {
    debugWarn("applyLineStyles", e);
  }
}

function applyHarmonicsToLinePlot(ctx, gd) {
  if (!gd) return;
  const win = gd.ownerDocument && gd.ownerDocument.defaultView ? gd.ownerDocument.defaultView : null;
  const Plotly = win && win.Plotly ? win.Plotly : null;
  if (!Plotly || !Plotly.relayout) return;
  const fBase = Number(latestArgs && latestArgs.f_base != null ? latestArgs.f_base : (ctx && ctx.state && ctx.state.baseFrequencyHz != null ? ctx.state.baseFrequencyHz : 50));
  // Use stable full-range bounds from server args, not current zoom range.
  // This avoids losing harmonic/bin lines after reset/autoscale when shapes
  // were last regenerated while zoomed into a narrow window.
  const n0 = Number(latestArgs && latestArgs.n_min != null ? latestArgs.n_min : 0);
  const n1 = Number(latestArgs && latestArgs.n_max != null ? latestArgs.n_max : 1);
  const layoutMeta = gd && gd.layout && gd.layout.meta && typeof gd.layout.meta === "object" ? gd.layout.meta : {};
  const xUnit = String(layoutMeta.line_x_unit || "");

  const harmonicShapes = buildHarmonicShapes(ctx, n0, n1, fBase, xUnit);
  const hKey = JSON.stringify({
    show: Boolean(ctx.state.showHarmonics),
    bw: Number(ctx.state.binWidthHz || 0),
    n0: Number(n0),
    n1: Number(n1),
    fb: Number(fBase),
    xu: String(xUnit),
  });
  try {
    if (gd.__fsHarmKey === hKey) return;
    gd.__fsHarmKey = hKey;
  } catch (e) {
    debugWarn("applyHarmonicsToLinePlot:set-key", e);
  }
  try {
    Plotly.relayout(gd, { shapes: harmonicShapes });
  } catch (e) {
    debugWarn("applyHarmonicsToLinePlot:relayout", e);
  }
}

function getScatterPointTraceIndex(gd) {
  if (!gd || !Array.isArray(gd.data)) return -1;
  for (let i = 0; i < gd.data.length; i++) {
    const tr = gd.data[i];
    const kind = tr && tr.meta && typeof tr.meta === "object" ? String(tr.meta.kind || "") : "";
    if (kind === "points") return i;
  }
  return gd.data.length > 0 ? 0 : -1;
}

function readScatterSliderActiveIndex(gd) {
  let active = 0;
  try {
    const sliders = gd && gd.layout && Array.isArray(gd.layout.sliders) ? gd.layout.sliders : [];
    if (sliders.length && sliders[0] && sliders[0].active != null) {
      active = Number(sliders[0].active);
    }
  } catch (e) {
    debugWarn("readScatterSliderActiveIndex", e);
  }
  if (!Number.isFinite(active)) active = 0;
  return Math.max(0, Math.floor(active));
}

function getRxSingleTracePayload(gd) {
  try {
    const layoutMeta = gd && gd.layout && gd.layout.meta && typeof gd.layout.meta === "object" ? gd.layout.meta : null;
    const raw = layoutMeta && layoutMeta.rx_single_trace && typeof layoutMeta.rx_single_trace === "object"
      ? layoutMeta.rx_single_trace
      : null;
    if (!raw) return null;
    const freqValues = Array.isArray(raw.freq_hz) ? raw.freq_hz.map((v) => Number(v)) : [];
    if (!freqValues.length) return null;
    const pointCount = Math.max(0, Math.floor(Number(raw.point_count || 0)));
    const xFlat = Array.isArray(raw.x_flat) ? raw.x_flat : [];
    const yFlat = Array.isArray(raw.y_flat) ? raw.y_flat : [];
    if (pointCount > 0 && xFlat.length === freqValues.length * pointCount && yFlat.length === xFlat.length) {
      const stepValues = (arr, idx) => {
        const start = Math.max(0, Math.floor(Number(idx || 0))) * pointCount;
        return arr.slice(start, start + pointCount);
      };
      return {
        freqValues,
        xAtStep: (idx) => stepValues(xFlat, idx),
        yAtStep: (idx) => stepValues(yFlat, idx),
        seqLabel: String(raw.seq_label || ""),
      };
    }

    return null;
  } catch (e) {
    debugWarn("getRxSingleTracePayload", e);
  }
  return null;
}

function scatterSliderEventIndex(evt, gd) {
  let idx = Number.NaN;
  try {
    const step = evt && evt.step && typeof evt.step === "object" ? evt.step : null;
    if (step && Array.isArray(step.args) && step.args.length > 0) {
      idx = Number(step.args[0]);
    }
  } catch (e) {
    debugWarn("scatterSliderEventIndex", e);
  }
  if (!Number.isFinite(idx)) {
    idx = Number(readScatterSliderActiveIndex(gd));
  }
  return idx;
}

function applyScatterFrequencyIndex(ctx, gd, nextIndex, options) {
  if (!gd) return false;
  const payload = getRxSingleTracePayload(gd);
  if (!payload) return false;
  const pointTraceIndex = getScatterPointTraceIndex(gd);
  if (pointTraceIndex < 0) return false;
  const win = gd.ownerDocument && gd.ownerDocument.defaultView ? gd.ownerDocument.defaultView : null;
  const Plotly = win && win.Plotly ? win.Plotly : null;
  const syncSlider = !(options && options.syncSlider === false);
  if (!Plotly || !Plotly.restyle || (syncSlider && !Plotly.update && !Plotly.relayout)) return false;

  const n = payload.freqValues.length;
  if (n <= 0) return false;
  let idx = Number(nextIndex);
  if (!Number.isFinite(idx)) idx = 0;
  idx = Math.max(0, Math.min(n - 1, Math.floor(idx)));

  const currentRaw = Number(gd.__fsRxSingleActiveIndex);
  // Plotly updates slider.active before firing plotly_sliderchange for method="skip".
  // Only our own stored index can prove the scatter trace is already restyled.
  if (Number.isFinite(currentRaw) && Math.floor(currentRaw) === idx) return true;

  const relayoutPayload = { "sliders[0].active": idx };
  const dataPayload = {
    x: [payload.xAtStep(idx)],
    y: [payload.yAtStep(idx)],
  };

  try {
    gd.__fsRxSingleApplying = true;
    if (syncSlider && Plotly.update) {
      Plotly.update(gd, dataPayload, relayoutPayload, [pointTraceIndex]);
    } else {
      Plotly.restyle(gd, dataPayload, [pointTraceIndex]);
      if (syncSlider) Plotly.relayout(gd, relayoutPayload);
    }
    gd.__fsRxSingleActiveIndex = idx;
    if (ctx) notifySelectionStateChanged(ctx, {
      frequencyOnly: true,
      rxCurrentFrequencyHz: Number(payload.freqValues[idx]),
    });
    return true;
  } catch (e) {
    debugWarn("applyScatterFrequencyIndex", e);
    return false;
  } finally {
    setTimeout(() => {
      try {
        gd.__fsRxSingleApplying = false;
      } catch (e) {
        debugWarn("applyScatterFrequencyIndex.clearApplying", e);
      }
    }, 0);
  }
}

function stepScatterFrequencyByDelta(ctx, delta) {
  const plots = getPlotDivs();
  const step = Number(delta || 0);
  if (!Number.isFinite(step) || step === 0) return false;
  for (let i = 0; i < plots.length; i++) {
    const gd = plots[i];
    if (!gd || !Array.isArray(gd.data)) continue;
    const pointTraceIndex = getScatterPointTraceIndex(gd);
    if (pointTraceIndex < 0) continue;
    const payload = getRxSingleTracePayload(gd);
    if (!payload) continue;
    const n = payload.freqValues.length;
    if (n <= 0) continue;
    const curRaw = Number(gd.__fsRxSingleActiveIndex);
    const cur = Number.isFinite(curRaw) ? curRaw : Number(readScatterSliderActiveIndex(gd));
    const next = Math.max(0, Math.min(n - 1, Math.floor(cur + step)));
    return applyScatterFrequencyIndex(ctx, gd, next);
  }
  return false;
}

function getScatterFrequencyInfo() {
  const plots = getPlotDivs();
  for (let i = 0; i < plots.length; i++) {
    const gd = plots[i];
    if (!gd || !Array.isArray(gd.data)) continue;
    const pointTraceIndex = getScatterPointTraceIndex(gd);
    if (pointTraceIndex < 0) continue;
    const payload = getRxSingleTracePayload(gd);
    if (!payload) continue;
    const n = payload.freqValues.length;
    if (n <= 0) continue;
    const curRaw = Number(gd.__fsRxSingleActiveIndex);
    const cur = Number.isFinite(curRaw) ? curRaw : Number(readScatterSliderActiveIndex(gd));
    const idx = Math.max(0, Math.min(n - 1, Math.floor(cur)));
    return {
      gd,
      payload,
      index: idx,
      freqHz: Number(payload.freqValues[idx]),
      minHz: Number(payload.freqValues[0]),
      maxHz: Number(payload.freqValues[n - 1]),
      stepCount: n,
    };
  }
  return null;
}

function nearestScatterFrequencyIndex(freqValues, targetHz) {
  const target = Number(targetHz);
  if (!Array.isArray(freqValues) || !freqValues.length || !Number.isFinite(target)) return -1;
  let bestIdx = -1;
  let bestDist = Number.POSITIVE_INFINITY;
  for (let i = 0; i < freqValues.length; i++) {
    const freq = Number(freqValues[i]);
    if (!Number.isFinite(freq)) continue;
    const dist = Math.abs(freq - target);
    if (dist < bestDist) {
      bestDist = dist;
      bestIdx = i;
    }
  }
  return bestIdx;
}

function setScatterFrequencyHz(ctx, rawHz) {
  const targetHz = Number(rawHz);
  if (!Number.isFinite(targetHz)) return false;
  const info = getScatterFrequencyInfo();
  if (!info || !info.payload || !Array.isArray(info.payload.freqValues)) return false;
  const idx = nearestScatterFrequencyIndex(info.payload.freqValues, targetHz);
  if (idx < 0) return false;
  return applyScatterFrequencyIndex(ctx, info.gd, idx);
}

function resolveScatterCaseIds(tr) {
  try {
    const idsRef = tr && tr.ids ? tr.ids : null;
    const cdsRef = tr && tr.customdata ? tr.customdata : null;
    const xLen = Array.isArray(tr && tr.x) ? tr.x.length : 0;
    if (tr.__fsScatterCaseIds && tr.__fsScatterIdsRef === idsRef && tr.__fsScatterCdsRef === cdsRef && tr.__fsScatterXLen === xLen) {
      return tr.__fsScatterCaseIds;
    }
  } catch (e) {
    debugWarn("resolveScatterCaseIds.cache-read", e);
  }
  const out = [];
  const ids = Array.isArray(tr && tr.ids) ? tr.ids : [];
  const cds = Array.isArray(tr && tr.customdata) ? tr.customdata : [];
  const xs = Array.isArray(tr && tr.x) ? tr.x : [];
  const count = Math.max(ids.length, cds.length, xs.length);
  for (let i = 0; i < count; i++) {
    let caseId = "";
    if (i < ids.length && ids[i] != null && String(ids[i]) !== "") {
      caseId = String(ids[i]);
    }
    if (!caseId && i < cds.length) {
      caseId = caseIdFromCustomData(cds[i]);
    }
    out.push(caseId);
  }
  try {
    tr.__fsScatterCaseIds = out;
    tr.__fsScatterIdsRef = tr && tr.ids ? tr.ids : null;
    tr.__fsScatterCdsRef = tr && tr.customdata ? tr.customdata : null;
    tr.__fsScatterXLen = xs.length;
  } catch (e) {
    debugWarn("resolveScatterCaseIds.cache-write", e);
  }
  return out;
}

function buildScatterMarkerArrays(caseIds, ctx, allowedSet, selectedMarkerSize, dimMarkerOpacity, dimMarkerSize) {
  const hasSelection = ctx.state.selectedCases.size > 0;
  const colors = [];
  const opacities = [];
  const sizes = [];
  const symbols = [];
  let filteredCount = 0;

  for (let i = 0; i < caseIds.length; i++) {
    const caseId = String(caseIds[i] || "");
    const passesFilter = allowedSet.has(caseId);
    if (passesFilter) filteredCount += 1;
    const selected = ctx.state.selectedCases.has(caseId);
    // Scatter should always keep allowed points visible for interactive picking.
    // "Hide unselected" is applied to line plots only.
    const visible = Boolean(passesFilter);
    const shouldDim = visible && hasSelection && !selected;
    const c = colorForCase(ctx, caseId);

    if (!visible) {
      colors.push(c);
      opacities.push(0.0);
      sizes.push(0.0);
      symbols.push("circle");
      continue;
    }

    colors.push(c);
    if (shouldDim) {
      opacities.push(dimMarkerOpacity);
      sizes.push(dimMarkerSize);
      symbols.push("circle");
    } else {
      opacities.push(1.0);
      sizes.push(selectedMarkerSize);
      symbols.push(selected ? "diamond" : "circle");
    }
  }
  return { colors, opacities, sizes, symbols, filteredCount };
}

function applyScatterStyles(ctx, gd, allowedSet, forceApply) {
  if (!gd || !Array.isArray(gd.data)) return;
  const win = gd.ownerDocument && gd.ownerDocument.defaultView ? gd.ownerDocument.defaultView : null;
  const Plotly = win && win.Plotly ? win.Plotly : null;
  if (!Plotly || !Plotly.restyle) return;

  const pointTraceIndex = getScatterPointTraceIndex(gd);
  if (pointTraceIndex < 0) return;

  const tr = gd.data[pointTraceIndex];
  const caseIds = resolveScatterCaseIds(tr);
  const selectedMarkerSize = Number(latestArgs.selected_marker_size || 10.0);
  const dimMarkerOpacity = Number(latestArgs.dim_marker_opacity || 0.28);
  const dimMarkerSize = Math.max(2.0, Number(selectedMarkerSize * 0.8));
  const applyToken = Number(ctx.state && ctx.state.__applyVersion != null ? ctx.state.__applyVersion : 0);
  const dataKey = `${caseIds.length}|${String(caseIds[0] || "")}|${String(caseIds[caseIds.length - 1] || "")}`;
  const scatterKey = `${applyToken}|${ctx.state.colorBy}|${dataKey}`;
  const doForce = Boolean(forceApply);
  try {
    if (!doForce && gd.__fsScatterApplyKey === scatterKey) return;
  } catch (e) {
    debugWarn("applyScatterStyles.noop-check", e);
  }

  const currentArr = buildScatterMarkerArrays(caseIds, ctx, allowedSet, selectedMarkerSize, dimMarkerOpacity, dimMarkerSize);
  const colors = currentArr.colors;
  const opacities = currentArr.opacities;
  const sizes = currentArr.sizes;
  const symbols = currentArr.symbols;
  try {
    Plotly.restyle(
      gd,
      {
        "marker.color": [colors],
        "marker.opacity": [opacities],
        "marker.size": [sizes],
        "marker.symbol": [symbols],
      },
      [pointTraceIndex],
    );
    gd.__fsScatterApplyKey = scatterKey;
  } catch (e) {
    debugWarn("applyScatterStyles", e);
  }
}

function bindScatterHandlers(ctx, gd, plotIndex) {
  if (!gd || !gd.on) return;
  const renderNonce = Number(latestArgs && latestArgs.render_nonce ? latestArgs.render_nonce : 0);
  const bindKey = `${ctx.dataId}|${ctx.chartId}|${plotIndex}|${renderNonce}`;
  try {
    if (gd.__fsCaseUiScatterKey === bindKey) return;
  } catch (e) {
    debugWarn("bindScatterHandlers.key-check", e);
  }

  try {
    if (gd.__fsCaseUiClick && gd.removeListener) gd.removeListener("plotly_click", gd.__fsCaseUiClick);
    if (gd.__fsCaseUiSlider && gd.removeListener) gd.removeListener("plotly_sliderchange", gd.__fsCaseUiSlider);
  } catch (e) {
    debugWarn("bindScatterHandlers.remove", e);
  }

  const clickHandler = (evt) => {
    const nextCtx = ensureContext();
    if (!nextCtx || !Boolean(latestArgs.enable_selection)) return;
    try {
      if (!evt || !Array.isArray(evt.points) || evt.points.length === 0) return;
      const caseId = caseIdFromEventPoint(nextCtx, evt.points[0], gd);
      if (!toggleCaseSelectionByCaseId(nextCtx, caseId)) return;
      renderPanel();
      applyAllPlots();
    } catch (e) {
      debugWarn("bindScatterHandlers.click", e);
    }
  };
  const sliderHandler = (evt) => {
    const nextCtx = ensureContext();
    if (!nextCtx) return;
    try {
      if (gd.__fsRxSingleApplying === true) return;
    } catch (e) {
      debugWarn("bindScatterHandlers.slider-guard", e);
    }
    const idx = scatterSliderEventIndex(evt, gd);
    if (Number.isFinite(idx)) {
      gd.__fsRxPendingSliderIndex = idx;
      if (gd.__fsRxSliderRaf) return;
      const win = gd.ownerDocument && gd.ownerDocument.defaultView ? gd.ownerDocument.defaultView : window;
      const schedule = win && typeof win.requestAnimationFrame === "function"
        ? win.requestAnimationFrame.bind(win)
        : (fn) => setTimeout(fn, 16);
      gd.__fsRxSliderRaf = schedule(() => {
        gd.__fsRxSliderRaf = 0;
        const latestCtx = ensureContext();
        if (!latestCtx) return;
        const latestIdx = Number(gd.__fsRxPendingSliderIndex);
        if (Number.isFinite(latestIdx) && applyScatterFrequencyIndex(latestCtx, gd, latestIdx, { syncSlider: false })) return;
        const allowed = computeAllowedSet(latestCtx);
        applyScatterStyles(latestCtx, gd, allowed, false);
      });
      return;
    }
    const allowed = computeAllowedSet(nextCtx);
    applyScatterStyles(nextCtx, gd, allowed, false);
  };

  try {
    gd.__fsCaseUiScatterKey = bindKey;
    gd.__fsCaseUiClick = clickHandler;
    gd.__fsCaseUiSlider = sliderHandler;
  } catch (e) {
    debugWarn("bindScatterHandlers.cache", e);
  }

  gd.on("plotly_click", clickHandler);
  gd.on("plotly_sliderchange", sliderHandler);
}

function bindLineHandlers(ctx, gd, plotIndex) {
  if (!gd || !gd.on) return;
  const renderNonce = Number(latestArgs && latestArgs.render_nonce ? latestArgs.render_nonce : 0);
  const bindKey = `${ctx.dataId}|${ctx.chartId}|line|${plotIndex}|${renderNonce}`;
  try {
    if (gd.__fsCaseUiLineKey === bindKey) return;
  } catch (e) {
    debugWarn("bindLineHandlers.key-check", e);
  }

  try {
    if (gd.__fsCaseUiLineClick && gd.removeListener) gd.removeListener("plotly_click", gd.__fsCaseUiLineClick);
  } catch (e) {
    debugWarn("bindLineHandlers.remove", e);
  }

  const clickHandler = (evt) => {
    const nextCtx = ensureContext();
    if (!nextCtx) return;
    try {
      if (!evt || !Array.isArray(evt.points) || evt.points.length === 0) return;
      const caseId = caseIdFromEventPoint(nextCtx, evt.points[0], gd);
      if (!toggleCaseSelectionByCaseId(nextCtx, caseId)) return;
      renderPanel();
      applyAllPlots();
    } catch (e) {
      debugWarn("bindLineHandlers.click", e);
    }
  };

  try {
    gd.__fsCaseUiLineKey = bindKey;
    gd.__fsCaseUiLineClick = clickHandler;
  } catch (e) {
    debugWarn("bindLineHandlers.cache", e);
  }

  gd.on("plotly_click", clickHandler);
}

function applyAllPlots() {
  const ctx = ensureContext();
  if (!ctx) {
    return { touchedCount: 0, matchedCount: 0, expectedCount: 0 };
  }
  const plotIds = asArray(latestArgs.plot_ids).map((v) => String(v || ""));
  const plots = getPlotDivs();
  const allowedSet = computeAllowedSet(ctx);
  let touchedCount = 0;
  let matchedCount = 0;
  const expectedCount = plotIds.length;

  const classifyPlot = (gd) => {
    if (!gd || !Array.isArray(gd.data)) return "";
    const renderNonce = Number(latestArgs && latestArgs.render_nonce ? latestArgs.render_nonce : 0);
    const classifyKey = `${String(ctx.dataId || "")}|${String(ctx.chartId || "")}|${renderNonce}|${gd.data.length}`;
    try {
      if (gd.__fsPlotKindKey === classifyKey && gd.__fsPlotKind) return String(gd.__fsPlotKind);
    } catch (e) {
      debugWarn("classifyPlot.cache-read", e);
    }
    let hasPoints = false;
    let hasLineCases = false;
    let hasIds = false;
    let hasLineByFallback = false;
    for (let i = 0; i < gd.data.length; i++) {
      const tr = gd.data[i];
      const meta = tr && tr.meta && typeof tr.meta === "object" ? tr.meta : null;
      const kind = String(meta && meta.kind != null ? meta.kind : "");
      if (kind === "points") hasPoints = true;
      if (kind === "line" && meta && meta.case_id != null) hasLineCases = true;
      if (Array.isArray(tr && tr.ids) && tr.ids.length > 0) hasIds = true;
      if (!hasLineByFallback && resolveCaseIdFromTrace(ctx, tr)) hasLineByFallback = true;
    }
    let kind = "";
    if (hasPoints) kind = "rx";
    const hasSlider = Boolean(gd && gd.layout && Array.isArray(gd.layout.sliders) && gd.layout.sliders.length > 0);
    if (!kind && hasIds && hasSlider) kind = "rx";
    if (!kind && (hasLineCases || hasLineByFallback)) kind = "line";
    try {
      gd.__fsPlotKindKey = classifyKey;
      gd.__fsPlotKind = kind;
    } catch (e) {
      debugWarn("classifyPlot.cache-write", e);
    }
    return kind;
  };

  for (let i = 0; i < plots.length; i++) {
    const gd = plots[i];
    if (!gd || !Array.isArray(gd.data)) continue;
    const kind = classifyPlot(gd);
    if (!kind) continue;
    matchedCount += 1;
    touchedCount += 1;
    if (kind === "rx") {
      bindScatterHandlers(ctx, gd, i);
      applyScatterStyles(ctx, gd, allowedSet, false);
      continue;
    }
    bindLineHandlers(ctx, gd, i);
    applyLineStyles(ctx, gd, allowedSet);
    applyHarmonicsToLinePlot(ctx, gd);
  }
  return { touchedCount, matchedCount, expectedCount };
}

function scheduleApplyPasses() {
  const myNonce = ++applyPassNonce;
  const splineEnabled = Boolean(latestArgs && latestArgs.spline_enabled);
  // Keep a short stabilization sequence for non-spline, and a longer tail for spline.
  // Stop scheduling once all expected plot DOMs are matched for a minimum number of passes.
  const delays = splineEnabled ? [0, 120, 320, 700, 1400] : [0, 120, 320, 700];
  const minPassBeforeStop = splineEnabled ? 2 : 2;
  let stabilized = false;
  for (let idx = 0; idx < delays.length; idx++) {
    const d = delays[idx];
    setTimeout(() => {
      if (myNonce !== applyPassNonce || stabilized) return;
      const res = applyAllPlots() || {};
      const expected = Number(res.expectedCount || 0);
      const matched = Number(res.matchedCount || 0);
      if (idx >= minPassBeforeStop && expected > 0 && matched >= expected) {
        stabilized = true;
      }
    }, d);
  }
}

function scheduleApplyOnce() {
  if (applyQueued) return;
  applyQueued = true;
  const run = () => {
    applyQueued = false;
    applyAllPlots();
  };
  if (typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(run);
  } else {
    setTimeout(run, 0);
  }
}

function sendFrameHeightIfNeeded() {
  try {
    const panel = document.querySelector(".fs-panel");
    const raw = panel ? Number(panel.scrollHeight || 0) + 8 : 180;
    const nextH = Math.max(180, Math.min(5000, Math.ceil(raw)));
    if (Math.abs(nextH - Number(lastSentFrameHeight || 0)) < 2) return;
    lastSentFrameHeight = nextH;
    sendToStreamlit("streamlit:setFrameHeight", { height: nextH });
  } catch (e) {
    debugWarn("sendFrameHeightIfNeeded", e);
  }
}

function scheduleFrameHeightSync() {
  sendFrameHeightIfNeeded();
  setTimeout(sendFrameHeightIfNeeded, 80);
}

function panelCss() {
  return `
    <style>
      :root {
        color-scheme: light;
        --fs-bg: linear-gradient(180deg, #ffffff 0%, #f7f9fc 100%);
        --fs-border: #cfd7e3;
        --fs-text: #1f2937;
        --fs-muted: #6b7280;
        --fs-soft: #eef2f8;
        --fs-accent: #1f6fd6;
        --fs-accent-soft: #e8f1ff;
      }

      html, body { margin: 0; padding: 0; }
      body {
        font-family: "Open Sans", "Segoe UI", sans-serif;
        color: var(--fs-text);
      }

      .fs-panel {
        border: 1px solid var(--fs-border);
        border-radius: 10px;
        padding: 8px;
        background: var(--fs-bg);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65);
      }

      .fs-section {
        margin: 8px 0 0 0;
        padding-top: 7px;
        border-top: 1px solid #e3e9f2;
      }

      .fs-section-tight {
        margin-top: 0;
        padding-top: 0;
        border-top: none;
      }

      .fs-row {
        display: flex;
        align-items: center;
        gap: 6px;
      }

      .fs-row-space { justify-content: space-between; }
      .fs-row-inline { margin-top: 6px; }

      .fs-title {
        font-weight: 700;
        font-size: 13px;
        letter-spacing: 0.01em;
      }

      .fs-subtitle {
        font-weight: 700;
        font-size: 13px;
        margin: 0 0 5px 0;
        letter-spacing: 0.01em;
      }

      .fs-block { margin: 6px 0 0 0; }
      .fs-block:last-of-type { margin-bottom: 0; }

      .fs-mini-actions {
        display: inline-flex;
        gap: 4px;
      }

      .fs-mini-btn,
      .fs-btn {
        border: 1px solid #b9c5d6;
        background: #ffffff;
        color: #223043;
        border-radius: 8px;
        cursor: pointer;
        transition: background 120ms ease, border-color 120ms ease, box-shadow 120ms ease, color 120ms ease;
      }

      .fs-mini-btn {
        padding: 1px 7px;
        font-size: 12px;
        font-weight: 600;
      }

      .fs-mini-btn-del {
        padding: 1px 6px;
        font-size: 11px;
        min-width: 30px;
      }

      .fs-btn {
        padding: 4px 9px;
        font-size: 12px;
        font-weight: 600;
      }

      .fs-btn-primary {
        background: var(--fs-accent-soft);
        border-color: #91b2e5;
        color: #18488f;
      }

      .fs-mini-btn:hover,
      .fs-btn:hover {
        background: #f6f9ff;
        border-color: #96aeca;
      }

      .fs-mini-btn:focus-visible,
      .fs-btn:focus-visible,
      .fs-select:focus-visible,
      .fs-textarea:focus-visible {
        outline: none;
        border-color: #5f93da;
        box-shadow: 0 0 0 2px rgba(31, 111, 214, 0.18);
      }

      .fs-select,
      .fs-textarea {
        width: 100%;
        box-sizing: border-box;
        border: 1px solid #c4cfdd;
        border-radius: 7px;
        background: #ffffff;
        color: #111827;
        font-size: 13px;
      }

      .fs-select { padding: 4px 7px; }
      .fs-textarea {
        min-height: 48px;
        resize: vertical;
        padding: 6px;
        line-height: 1.22;
      }

      .fs-check-list {
        border: 1px solid #d4ddea;
        border-radius: 8px;
        margin-top: 5px;
        padding: 3px 5px;
        max-height: 150px;
        overflow: auto;
        background: #ffffff;
      }

      .fs-check-item {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        line-height: 1.12;
        margin: 0;
        padding: 2px 4px;
        border-radius: 5px;
        user-select: none;
      }

      .fs-check-item:hover { background: #f5f8ff; }
      .fs-check-item input[type="checkbox"] { accent-color: var(--fs-accent); }

      .fs-check-text {
        display: inline-flex;
        align-items: center;
        gap: 6px;
      }

      .fs-color-dot {
        display: inline-block;
        width: 11px;
        height: 11px;
        border-radius: 50%;
        border: 1px solid rgba(0, 0, 0, 0.28);
        box-sizing: border-box;
        flex: 0 0 auto;
      }

      .fs-note {
        font-size: 12px;
        color: var(--fs-muted);
        margin: 2px 0 0 0;
      }

      .fs-label {
        font-size: 12px;
        color: #2c3748;
      }

      .fs-label-fixed { min-width: 110px; }

      .fs-table-wrap {
        max-height: 170px;
        overflow: auto;
        border: 1px solid #d9e1ed;
        border-radius: 7px;
        margin-top: 4px;
        background: #fff;
      }

      table.fs-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
      }

      .fs-table th,
      .fs-table td {
        border-bottom: 1px solid #edf1f7;
        padding: 4px 5px;
        text-align: left;
        vertical-align: middle;
      }

      .fs-table tbody tr:hover td { background: #f8faff; }

      .fs-table th {
        position: sticky;
        top: 0;
        background: #f5f8fc;
        z-index: 1;
      }

      .fs-empty {
        color: #7c7c7c;
        text-align: center;
      }

      .fs-status {
        font-size: 12px;
        margin-top: 3px;
        color: #3f4d5f;
        min-height: 12px;
      }

      .fs-actions {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
        margin-top: 5px;
      }

      .fs-action-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 6px;
        margin-top: 6px;
      }

      .fs-action-grid .fs-btn {
        width: 100%;
        min-height: 30px;
        justify-content: center;
        text-align: center;
      }

      .fs-selected-note {
        margin-top: 0;
        margin-bottom: 2px;
      }
    </style>
  `;
}

function renderPartFilterBlocks(ctx) {
  const activePartColorInfo = buildActivePartValueColorMap(ctx);
  const partBlocks = [];
  for (let i = 0; i < ctx.partLabels.length; i++) {
    const opts = ctx.partOptions[i] || [];
    const sel = ctx.state.selectedByPart[i] instanceof Set ? ctx.state.selectedByPart[i] : new Set();
    const checksHtml = opts
      .map((v, optIdx) => {
        const checkedAttr = sel.has(v) ? " checked" : "";
        const partValue = String(v || "");
        const showColorDot = activePartColorInfo.partIdx === i;
        const dotColor = showColorDot ? String(activePartColorInfo.valueColorMap.get(partValue) || "#1f77b4") : "";
        const dotHtml = showColorDot
          ? `<span class="fs-color-dot" style="background:${escapeHtml(dotColor)};" title="${escapeHtml(dotColor)}"></span>`
          : "";
        return `
          <label class="fs-check-item">
            <input type="checkbox" data-part-check="${i}" data-part-opt="${optIdx}"${checkedAttr} />
            <span class="fs-check-text"><span>${escapeHtml(displayValue(v))}</span>${dotHtml}</span>
          </label>
        `;
      })
      .join("");
    partBlocks.push(`
      <div class="fs-block">
        <div class="fs-row fs-row-space">
          <div class="fs-title">${escapeHtml(ctx.partLabels[i])}</div>
          <div class="fs-mini-actions">
            <button type="button" class="fs-mini-btn" data-part-all="${i}">All</button>
            <button type="button" class="fs-mini-btn" data-part-none="${i}">None</button>
          </div>
        </div>
        <div class="fs-check-list">
          ${checksHtml}
        </div>
      </div>
    `);
  }
  return partBlocks.join("");
}

function renderColorOptions(ctx) {
  return ctx.colorOptions
    .map((opt) => {
      const selectedAttr = String(opt) === String(ctx.state.colorBy) ? " selected" : "";
      return `<option value="${escapeHtml(opt)}"${selectedAttr}>${escapeHtml(opt)}</option>`;
    })
    .join("");
}

function renderSelectedRows(rows) {
  return rows.length
    ? rows
        .map(
          (r) => `
            <tr>
              <td>${escapeHtml(r.displayCase)}</td>
              <td>${r.hidden ? "Hidden" : "Visible"}</td>
              <td><button type="button" class="fs-mini-btn fs-mini-btn-del" data-remove-case="${escapeHtml(r.caseId)}" title="Remove">Del</button></td>
            </tr>
          `,
        )
        .join("")
    : `<tr><td colspan="3" class="fs-empty">No selected cases</td></tr>`;
}

function renderSelectionToolbar(ctx) {
  if (Boolean(latestArgs.enable_selection)) return "";
  return `
    <label class="fs-row">
      <input id="fs-show-only" type="checkbox" ${ctx.state.showOnlySelected ? "checked" : ""} />
      <span style="font-size:13px;">Hide unselected</span>
    </label>
  `;
}

function renderSelectionDisabledNote() {
  return Boolean(latestArgs.enable_selection) || latestArgs.enable_selection == null
    ? ""
    : `<div class="fs-note">Scatter is hidden. Use line-plot clicks or import list to build a selection.</div>`;
}

function renderPanelHtml(ctx, rows) {
  const hiddenSelectedCount = rows.filter((r) => r.hidden).length;
  const hiddenNote = hiddenSelectedCount > 0 ? ` | Hidden by filters: ${hiddenSelectedCount}` : "";
  return `
    ${panelCss()}
    <div class="fs-panel">
      <section class="fs-section fs-section-tight">
        <div class="fs-row fs-row-space">
          <div class="fs-title">Case part filters</div>
          <button type="button" id="fs-reset-filters" class="fs-btn">Reset filters</button>
        </div>
        ${renderPartFilterBlocks(ctx)}
      </section>

      <section class="fs-section">
        <div class="fs-subtitle">Color</div>
        <select id="fs-color-by" class="fs-select">${renderColorOptions(ctx)}</select>
      </section>

      <section class="fs-section">
        <div class="fs-subtitle">Selection</div>
        ${renderSelectionDisabledNote()}
        ${renderSelectionToolbar(ctx)}
      </section>

      <section class="fs-section">
        <div class="fs-subtitle">Add cases to selection</div>
        <textarea id="fs-import-text" class="fs-textarea" placeholder="Paste case IDs or display names (space/comma/tab/newline separated)"></textarea>
        <div class="fs-actions">
          <button type="button" id="fs-import-add" class="fs-btn">Add list</button>
        </div>
        <div id="fs-import-status" class="fs-status">${escapeHtml(ctx.state.importStatus || "")}</div>
      </section>

      <section class="fs-section">
        <div class="fs-subtitle">Selected cases</div>
        <div class="fs-note fs-selected-note">Selected: ${rows.length} case(s)${hiddenNote}</div>
        <div class="fs-action-grid">
          <button type="button" id="fs-clear-list" class="fs-btn">Clear list</button>
          <button type="button" id="fs-download-csv" class="fs-btn fs-btn-primary" title="Download selected CSV">Download CSV</button>
        </div>
        <div class="fs-table-wrap">
          <table class="fs-table">
            <thead>
              <tr><th>Case</th><th>Status</th><th>Action</th></tr>
            </thead>
            <tbody>${renderSelectedRows(rows)}</tbody>
          </table>
        </div>
      </section>

      <section class="fs-section">
        <div class="fs-subtitle">Harmonics</div>
        <label class="fs-row fs-row-inline">
          <input id="fs-show-harmonics" type="checkbox" ${ctx.state.showHarmonics ? "checked" : ""} />
          <span class="fs-label">Show harmonic lines</span>
        </label>
        <label class="fs-row fs-row-inline">
          <span class="fs-label fs-label-fixed">Bin width (Hz)</span>
          <input id="fs-bin-width" type="number" min="0" step="1" value="${Number(ctx.state.binWidthHz || 0)}" class="fs-select" />
        </label>
      </section>
    </div>
  `;
}

function applyPanelUiChange(ctx) {
  recomputeSelectedCases(ctx);
  bumpStateVersion(ctx.state);
  notifySelectionStateChanged(ctx);
  applyPassNonce += 1;
  renderPanel();
  scheduleApplyOnce();
}

function addImportedCasesToState(ctx, rawText) {
  const tokens = tokenizeImportList(rawText || "");
  let added = 0;
  let missing = 0;
  for (const tok of tokens) {
    const key = tok.toLowerCase();
    const direct = ctx.exactLookup.get(key);
    if (direct) {
      const manual = ctx.state.manualSelectedCases instanceof Set ? ctx.state.manualSelectedCases : new Set();
      if (!manual.has(direct)) {
        manual.add(direct);
        ctx.state.manualSelectedCases = manual;
        if (ctx.state.methodExcludedCases instanceof Set) ctx.state.methodExcludedCases.delete(direct);
        added += 1;
      }
      continue;
    }
    const byDisplay = ctx.displayLookup.get(key) || [];
    if (!byDisplay.length) {
      missing += 1;
      continue;
    }
    for (const cid of byDisplay) {
      const manual = ctx.state.manualSelectedCases instanceof Set ? ctx.state.manualSelectedCases : new Set();
      if (!manual.has(cid)) {
        manual.add(cid);
        ctx.state.manualSelectedCases = manual;
        if (ctx.state.methodExcludedCases instanceof Set) ctx.state.methodExcludedCases.delete(cid);
        added += 1;
      }
    }
  }
  ctx.state.importStatus = `Added ${added} case(s)` + (missing > 0 ? ` | Not found: ${missing}` : "");
}

function bindPanelEvents(ctx, rows) {
  const btnResetFilters = document.getElementById("fs-reset-filters");
  if (btnResetFilters) {
    btnResetFilters.addEventListener("click", () => {
      for (let i = 0; i < ctx.partOptions.length; i++) {
        ctx.state.selectedByPart[i] = new Set(ctx.partOptions[i] || []);
      }
      ctx.state.importStatus = "";
      applyPanelUiChange(ctx);
    });
  }

  for (const btn of Array.from(document.querySelectorAll("button[data-part-all]"))) {
    btn.addEventListener("click", () => {
      const idx = Number(btn.getAttribute("data-part-all"));
      if (!Number.isFinite(idx) || idx < 0 || idx >= ctx.partOptions.length) return;
      ctx.state.selectedByPart[idx] = new Set(ctx.partOptions[idx] || []);
      ctx.state.importStatus = "";
      applyPanelUiChange(ctx);
    });
  }
  for (const btn of Array.from(document.querySelectorAll("button[data-part-none]"))) {
    btn.addEventListener("click", () => {
      const idx = Number(btn.getAttribute("data-part-none"));
      if (!Number.isFinite(idx) || idx < 0 || idx >= ctx.partOptions.length) return;
      ctx.state.selectedByPart[idx] = new Set();
      ctx.state.importStatus = "";
      applyPanelUiChange(ctx);
    });
  }
  for (const inp of Array.from(document.querySelectorAll("input[data-part-check]"))) {
    inp.addEventListener("change", () => {
      const idx = Number(inp.getAttribute("data-part-check"));
      const optIdx = Number(inp.getAttribute("data-part-opt"));
      if (!Number.isFinite(idx) || idx < 0 || idx >= ctx.partOptions.length) return;
      if (!Number.isFinite(optIdx) || optIdx < 0 || optIdx >= (ctx.partOptions[idx] || []).length) return;
      const val = String(ctx.partOptions[idx][optIdx] || "");
      const set = ctx.state.selectedByPart[idx] instanceof Set ? new Set(ctx.state.selectedByPart[idx]) : new Set();
      if (Boolean(inp.checked)) set.add(val);
      else set.delete(val);
      ctx.state.selectedByPart[idx] = set;
      ctx.state.importStatus = "";
      applyPanelUiChange(ctx);
    });
  }

  const colorBy = document.getElementById("fs-color-by");
  if (colorBy) {
    colorBy.addEventListener("change", () => {
      ctx.state.colorBy = String(colorBy.value || "Auto");
      ctx.state.importStatus = "";
      applyPanelUiChange(ctx);
    });
  }

  const showOnly = document.getElementById("fs-show-only");
  if (showOnly) {
    showOnly.addEventListener("change", () => {
      ctx.state.showOnlySelected = showOnly.checked === true;
      ctx.state.importStatus = "";
      applyPanelUiChange(ctx);
    });
  }

  const showHarmonics = document.getElementById("fs-show-harmonics");
  if (showHarmonics) {
    showHarmonics.addEventListener("change", () => {
      ctx.state.showHarmonics = Boolean(showHarmonics.checked);
      scheduleApplyOnce();
    });
  }

  const binWidth = document.getElementById("fs-bin-width");
  if (binWidth) {
    const onBinWidth = () => {
      const v = Number(binWidth.value);
      ctx.state.binWidthHz = Number.isFinite(v) && v >= 0 ? v : 0;
      scheduleApplyOnce();
    };
    binWidth.addEventListener("input", onBinWidth);
    binWidth.addEventListener("change", onBinWidth);
  }

  const clearList = document.getElementById("fs-clear-list");
  if (clearList) {
    clearList.addEventListener("click", () => {
      ctx.state.manualSelectedCases = new Set();
      ctx.state.methodExcludedCases = new Set();
      ctx.state.methodEnerginetEnabled = false;
      ctx.state.methodIecEnabled = false;
      ctx.state.methodIecCapacitiveOnly = false;
      ctx.state.methodPeakZEnabled = false;
      ctx.state.methodPeakZCapacitiveOnly = false;
      ctx.state.methodPeakZExactEnabled = true;
      ctx.state.methodPeakZBandEnabled = false;
      ctx.state.methodPeakXEnabled = false;
      ctx.state.methodPeakXCapacitiveOnly = false;
      ctx.state.methodPeakXExactEnabled = true;
      ctx.state.methodPeakXBandEnabled = false;
      ctx.state.methodRiskEnabled = false;
      ctx.state.methodRiskCapacitiveOnly = false;
      ctx.state.methodOutlierEnabled = false;
      ctx.state.methodOutlierCapacitiveOnly = false;
      ctx.state.importStatus = "";
      applyPanelUiChange(ctx);
    });
  }

  const addList = document.getElementById("fs-import-add");
  const importText = document.getElementById("fs-import-text");
  if (addList && importText) {
    addList.addEventListener("click", () => {
      addImportedCasesToState(ctx, importText.value || "");
      applyPanelUiChange(ctx);
    });
  }

  const downloadCsv = document.getElementById("fs-download-csv");
  if (downloadCsv) {
    downloadCsv.addEventListener("click", () => {
      downloadSelectedCsv(rows);
    });
  }

  for (const btn of Array.from(document.querySelectorAll("button[data-remove-case]"))) {
    btn.addEventListener("click", () => {
      const caseId = String(btn.getAttribute("data-remove-case") || "");
      if (!caseId) return;
      if (ctx.state.manualSelectedCases instanceof Set) ctx.state.manualSelectedCases.delete(caseId);
      if (ctx.state.methodExcludedCases instanceof Set) ctx.state.methodExcludedCases.add(caseId);
      ctx.state.importStatus = "";
      applyPanelUiChange(ctx);
    });
  }
}

function resetPanelScroll() {
  try {
    const sc = document.scrollingElement || document.documentElement || document.body;
    if (sc) sc.scrollTop = 0;
    const panel = document.querySelector(".fs-panel");
    if (panel) panel.scrollTop = 0;
  } catch (e) {
    debugWarn("resetPanelScroll", e);
  }
}

function renderPanel() {
  const ctx = ensureContext();
  if (!ctx) return;
  registerExternalSelectionApi(ctx);
  const renderNonceNow = Number(latestArgs && latestArgs.render_nonce ? latestArgs.render_nonce : 0);
  const isFreshStreamlitRender = renderNonceNow !== lastRenderNonceSeen;
  lastRenderNonceSeen = renderNonceNow;
  const root = document.getElementById("app");
  if (!root) return;

  const allowedSet = computeAllowedSet(ctx);
  const rows = selectedRowsForTable(ctx, allowedSet);
  const html = renderPanelHtml(ctx, rows);
  try {
    if (!isFreshStreamlitRender && root.__fsPanelHtml === html) {
      scheduleFrameHeightSync();
      return;
    }
    root.__fsPanelHtml = html;
  } catch (e) {
    debugWarn("renderPanel.html-cache", e);
  }
  root.innerHTML = html;
  bindPanelEvents(ctx, rows);
  if (isFreshStreamlitRender) resetPanelScroll();
  scheduleFrameHeightSync();
}

window.addEventListener("message", (event) => {
  const data = event && event.data ? event.data : null;
  if (!data || data.type !== "streamlit:render") return;
  latestArgs = data.args || {};
  renderPanel();
  scheduleApplyPasses();
});

sendToStreamlit("streamlit:componentReady", { apiVersion: 1 });
sendToStreamlit("streamlit:setFrameHeight", { height: 180 });

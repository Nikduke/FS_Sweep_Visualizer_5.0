const CASE_UI_API_GLOBAL = "__fsCaseUiApi";
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

let latestArgs = {};
let syncTimer = null;
let thresholdDebounceTimer = null;
let selectionStateListener = null;
let activeStateKey = "";
let lastSyncedStateVersion = Number.NaN;
let lastSentFrameHeight = 0;

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
    console.warn(`[fs-rx-toolbar] ${scope}`, err);
  } catch (e) {
    // Debug logging must never affect toolbar behavior.
  }
}

function asString(name, fallback) {
  const v = latestArgs ? latestArgs[name] : null;
  if (v == null) return String(fallback);
  return String(v);
}

function getPlots() {
  const out = [];
  try {
    const doc = window.parent.document;
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
    debugWarn("getPlots", e);
  }
  return out;
}

function getSelectionApi(stateKey) {
  try {
    const rootWin = window.parent;
    const apiStore = rootWin && rootWin[CASE_UI_API_GLOBAL] && typeof rootWin[CASE_UI_API_GLOBAL] === "object"
      ? rootWin[CASE_UI_API_GLOBAL]
      : null;
    if (!apiStore) return null;
    const api = apiStore[stateKey];
    return api && typeof api === "object" ? api : null;
  } catch (e) {
    debugWarn("getSelectionApi", e);
  }
  return null;
}

function clearSelectionSyncBindings() {
  try {
    if (syncTimer) {
      clearInterval(syncTimer);
      syncTimer = null;
    }
  } catch (e) {
    debugWarn("clearSelectionSyncBindings.timer", e);
  }
  try {
    const rootWin = window.parent || window;
    if (selectionStateListener && rootWin && typeof rootWin.removeEventListener === "function") {
      rootWin.removeEventListener(CASE_UI_STATE_EVENT, selectionStateListener);
    }
  } catch (e) {
    debugWarn("clearSelectionSyncBindings.listener", e);
  }
  selectionStateListener = null;
}

function installSelectionSync(stateKey) {
  clearSelectionSyncBindings();
  activeStateKey = String(stateKey || "");
  lastSyncedStateVersion = Number.NaN;
  try {
    const rootWin = window.parent || window;
    selectionStateListener = (event) => {
      try {
        const detail = event && event.detail && typeof event.detail === "object" ? event.detail : {};
        const evtKey = String(detail.stateKey || "");
        if (evtKey && evtKey !== activeStateKey) return;
        if (detail.frequencyOnly === true) {
          const freqInput = document.getElementById("rx-freq");
          const freqHz = Number(detail.rxCurrentFrequencyHz);
          if (freqInput && Number.isFinite(freqHz)) setInputValueSafe(freqInput, String(freqHz));
          return;
        }
        syncSelectionControls(activeStateKey, true);
      } catch (e) {
        debugWarn("selectionStateListener", e);
      }
    };
    if (rootWin && typeof rootWin.addEventListener === "function") {
      rootWin.addEventListener(CASE_UI_STATE_EVENT, selectionStateListener);
    }
  } catch (e) {
    debugWarn("installSelectionSync.listener", e);
  }
  try {
    syncTimer = setInterval(() => {
      syncSelectionControls(activeStateKey, false);
    }, 5000);
  } catch (e) {
    debugWarn("installSelectionSync.timer", e);
  }
}

function setInputValueSafe(inputEl, value) {
  if (!inputEl) return;
  if (document.activeElement === inputEl) return;
  inputEl.value = String(value);
}

function clearInputAttrSafe(inputEl, name) {
  if (!inputEl) return;
  try {
    inputEl.removeAttribute(name);
  } catch (e) {
    debugWarn("clearInputAttrSafe", e);
  }
}

function sendFrameHeightIfNeeded() {
  try {
    const root = document.getElementById("rx-step-root");
    if (!root) return;
    const rectH = root.getBoundingClientRect ? Number(root.getBoundingClientRect().height || 0) : 0;
    const rawRootH = Math.max(Number(root.scrollHeight || 0), rectH);
    const nextH = Math.max(42, Math.ceil(rawRootH) + 4);
    if (Math.abs(nextH - Number(lastSentFrameHeight || 0)) < 2) return;
    lastSentFrameHeight = nextH;
    sendToStreamlit("streamlit:setFrameHeight", { height: nextH });
  } catch (e) {
    debugWarn("sendFrameHeightIfNeeded", e);
  }
}

function syncSelectionControls(stateKey, force) {
  try {
    const api = getSelectionApi(stateKey);
    if (!api || typeof api.getState !== "function") {
      lastSyncedStateVersion = Number.NaN;
      return;
    }
    const st = api.getState();
    if (!st || typeof st !== "object") return;
    const stVersion = Number(st.stateVersion);
    if (
      force !== true &&
      String(stateKey || "") === String(activeStateKey || "") &&
      Number.isFinite(stVersion) &&
      Number.isFinite(lastSyncedStateVersion) &&
      stVersion === lastSyncedStateVersion
    ) {
      return;
    }
    if (Number.isFinite(stVersion)) {
      lastSyncedStateVersion = stVersion;
    }
    activeStateKey = String(stateKey || "");

    const cbShowOnly = document.getElementById("rx-showonly");
    if (cbShowOnly && Object.prototype.hasOwnProperty.call(st, "showOnlySelected")) {
      cbShowOnly.checked = Boolean(st.showOnlySelected);
    }

    const cbEnerginet = document.getElementById("rx-method-energinet");
    const cbIec = document.getElementById("rx-method-iec");
    const cbIecCapacitive = document.getElementById("rx-iec-capacitive");
    const iecCapacitiveLbl = document.getElementById("rx-iec-capacitive-label");
    const t2 = document.getElementById("rx-t2");
    const t3 = document.getElementById("rx-t3");
    const t4 = document.getElementById("rx-t4");
    const enTopN = document.getElementById("rx-en-topn");
    const iecTopN = document.getElementById("rx-iec-topn");
    const freqInput = document.getElementById("rx-freq");
    const note = document.getElementById("rx-method-note");
    const summary = document.getElementById("rx-selection-summary");
    const clearBtn = document.getElementById("rx-clear-selection");
    const csvBtn = document.getElementById("rx-download-csv");
    const preselectionAvailable = Boolean(st.preselectionAvailable);
    const rxCurrentFrequencyHz = st.rxCurrentFrequencyHz != null ? Number(st.rxCurrentFrequencyHz) : Number.NaN;
    const rxFrequencyMinHz = st.rxFrequencyMinHz != null ? Number(st.rxFrequencyMinHz) : Number.NaN;
    const rxFrequencyMaxHz = st.rxFrequencyMaxHz != null ? Number(st.rxFrequencyMaxHz) : Number.NaN;
    const rxFrequencyStepCount = Number(st.rxFrequencyStepCount || 0);
    const selectedCount = Number(st.selectedCount || 0);
    const visibleSelectedCount = Number(st.visibleSelectedCount != null ? st.visibleSelectedCount : Math.max(0, selectedCount - Number(st.hiddenSelectedCount || 0)));
    const hiddenSelectedCount = Number(st.hiddenSelectedCount || 0);

    if (cbEnerginet) {
      cbEnerginet.disabled = !preselectionAvailable;
      cbEnerginet.checked = preselectionAvailable && Boolean(st.energinetEnabled);
      const cnt = Number(st.energinetCandidateCount || 0);
      const lbl = document.getElementById("rx-method-energinet-label");
      if (lbl) lbl.textContent = `Energinet (${cnt})`;
    }
    if (cbIec) {
      cbIec.disabled = !preselectionAvailable;
      cbIec.checked = preselectionAvailable && Boolean(st.iecEnabled);
      const cnt = Number(st.iecCandidateCount || 0);
      const lbl = document.getElementById("rx-method-iec-label");
      if (lbl) lbl.textContent = `IEC (${cnt})`;
    }
    if (cbIecCapacitive) {
      const iecOn = preselectionAvailable && Boolean(st.iecEnabled);
      cbIecCapacitive.disabled = !iecOn;
      cbIecCapacitive.checked = iecOn && Boolean(st.iecCapacitiveOnly);
    }
    if (iecCapacitiveLbl) {
      const capCount = Number(st.iecCapacitiveCandidateCount || 0);
      iecCapacitiveLbl.textContent = `Capacitive (${capCount})`;
    }
    if (t2) {
      t2.disabled = !preselectionAvailable;
      setInputValueSafe(t2, Number(st.energinetT2 || 0));
    }
    if (t3) {
      t3.disabled = !preselectionAvailable;
      setInputValueSafe(t3, Number(st.energinetT3 || 0));
    }
    if (t4) {
      t4.disabled = !preselectionAvailable;
      setInputValueSafe(t4, Number(st.energinetT4 || 0));
    }
    if (enTopN) {
      enTopN.disabled = !preselectionAvailable;
      setInputValueSafe(enTopN, Number(st.energinetTopN || 0));
    }
    if (iecTopN) {
      iecTopN.disabled = !preselectionAvailable;
      setInputValueSafe(iecTopN, Number(st.iecTopN || 0));
    }
    if (freqInput) {
      const hasFreq = Number.isFinite(rxCurrentFrequencyHz);
      freqInput.disabled = rxFrequencyStepCount <= 0;
      if (hasFreq) {
        setInputValueSafe(freqInput, String(rxCurrentFrequencyHz));
      }
      if (Number.isFinite(rxFrequencyMinHz)) freqInput.setAttribute("min", String(rxFrequencyMinHz));
      else clearInputAttrSafe(freqInput, "min");
      if (Number.isFinite(rxFrequencyMaxHz)) freqInput.setAttribute("max", String(rxFrequencyMaxHz));
      else clearInputAttrSafe(freqInput, "max");
      freqInput.setAttribute("step", "any");
      freqInput.title = rxFrequencyStepCount > 0 ? "Sets the nearest available frequency step." : "Frequency control unavailable.";
    }
    if (note) {
      if (!preselectionAvailable) {
        const err = String(st.preselectionError || "");
        note.textContent = err ? `Preselection unavailable: ${err}` : "Preselection unavailable for this dataset.";
      } else {
        note.textContent = "";
      }
    }
    if (summary) {
      summary.textContent = `Selected ${selectedCount} | Visible ${visibleSelectedCount} | Hidden ${hiddenSelectedCount}`;
    }
    if (clearBtn) clearBtn.disabled = selectedCount <= 0;
    if (csvBtn) csvBtn.disabled = selectedCount <= 0;
    sendFrameHeightIfNeeded();
  } catch (e) {
    debugWarn("syncSelectionControls", e);
  }
}

function stepFrequency(delta, stateKey) {
  try {
    const api = getSelectionApi(stateKey);
    if (api && typeof api.stepRxFrequency === "function") {
      const ok = api.stepRxFrequency(Number(delta || 0));
      if (ok) {
        syncSelectionControls(stateKey, true);
        return;
      }
    }
  } catch (e) {
    debugWarn("stepFrequency", e);
  }
}

function pushExactFrequency(stateKey) {
  const inp = document.getElementById("rx-freq");
  const targetHz = Number(inp ? inp.value : Number.NaN);
  if (!Number.isFinite(targetHz)) return;
  try {
    const api = getSelectionApi(stateKey);
    if (api && typeof api.setRxFrequencyHz === "function") {
      const ok = api.setRxFrequencyHz(targetHz);
      if (ok) {
        syncSelectionControls(stateKey, true);
      }
    }
  } catch (e) {
    debugWarn("pushExactFrequency", e);
  }
}

function pushEnerginetThresholds(stateKey) {
  const t2El = document.getElementById("rx-t2");
  const t3El = document.getElementById("rx-t3");
  const t4El = document.getElementById("rx-t4");
  const t2 = Number(t2El ? t2El.value : NaN);
  const t3 = Number(t3El ? t3El.value : NaN);
  const t4 = Number(t4El ? t4El.value : NaN);
  try {
    const api = getSelectionApi(stateKey);
    if (api && typeof api.setEnerginetThresholds === "function") {
      api.setEnerginetThresholds({ t2, t3, t4 });
    }
  } catch (e) {
    debugWarn("pushEnerginetThresholds", e);
  }
}

function pushEnerginetTopN(stateKey) {
  const inp = document.getElementById("rx-en-topn");
  const n = Number(inp ? inp.value : NaN);
  try {
    const api = getSelectionApi(stateKey);
    if (api && typeof api.setEnerginetTopN === "function") {
      api.setEnerginetTopN(n);
    }
  } catch (e) {
    debugWarn("pushEnerginetTopN", e);
  }
}

function pushIecTopN(stateKey) {
  const inp = document.getElementById("rx-iec-topn");
  const n = Number(inp ? inp.value : NaN);
  try {
    const api = getSelectionApi(stateKey);
    if (api && typeof api.setIecTopN === "function") {
      api.setIecTopN(n);
    }
  } catch (e) {
    debugWarn("pushIecTopN", e);
  }
}

function pushIecCapacitiveMode(stateKey, flag) {
  try {
    const api = getSelectionApi(stateKey);
    if (api && typeof api.setIecCapacitiveOnly === "function") {
      api.setIecCapacitiveOnly(flag === true);
    }
  } catch (e) {
    debugWarn("pushIecCapacitiveMode", e);
  }
}

function render() {
  const root = document.getElementById("app");
  if (!root) return;

  const dataId = asString("data_id", "");
  const chartId = asString("chart_id", "");
  const stateKey = `${String(dataId)}|${String(chartId)}`;

  root.innerHTML = `
    <style>
      html,
      body {
        margin: 0;
        padding: 0;
        overflow: hidden;
      }
      #rx-step-root {
        display: block;
        margin: 0;
        font-family: "Open Sans", verdana, arial, sans-serif;
      }
      .rx-control-table {
        display: grid;
        grid-template-columns: 82px minmax(0, 1fr);
        gap: 0;
        border: 1px solid #d8e1ee;
        border-radius: 10px;
        background: #f8fafc;
        overflow: hidden;
      }
      .rx-label {
        display: flex;
        align-items: center;
        padding: 2px 6px;
        color: #243047;
        font-size: 11px;
        font-weight: 700;
        border-right: 1px solid #e0e7f1;
        border-bottom: 1px solid #e7edf5;
        background: #f3f6fa;
      }
      .rx-label-last {
        border-bottom: none;
      }
      .rx-row {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 5px 7px;
        min-height: 26px;
        padding: 2px 6px;
        border-bottom: 1px solid #e7edf5;
        background: #fbfcfe;
      }
      .rx-row-last {
        border-bottom: none;
      }
      .rx-divider {
        width: 1px;
        height: 22px;
        background: #d5deeb;
        margin: 0 2px;
      }
      .rx-btn {
        min-height: 24px;
        padding: 2px 8px;
        font-size: 11px;
        cursor: pointer;
        font-family: inherit;
        font-weight: 600;
        color: #243047;
        background: #fff;
        border: 1px solid #b8c7dd;
        border-radius: 8px;
        line-height: 1.15;
      }
      .rx-btn:hover:not(:disabled) {
        background: #f4f8ff;
        border-color: #91a9ca;
      }
      .rx-btn:focus-visible,
      .rx-th input:focus-visible {
        outline: 2px solid #2f6fda;
        outline-offset: 2px;
      }
      .rx-btn:disabled,
      .rx-th input:disabled {
        color: #8a95a8;
        background: #eef2f7;
        border-color: #d5deeb;
        cursor: not-allowed;
      }
      .rx-showonly,
      .rx-method-check {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        font-size: 11px;
        color: #222;
      }
      .rx-showonly input,
      .rx-method-check input {
        width: 14px;
        height: 14px;
        margin: 0;
      }
      .rx-th {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 11px;
        color: #222;
      }
      .rx-th input {
        width: 58px;
        font-size: 11px;
        min-height: 22px;
        padding: 1px 5px;
        border: 1px solid #b8c7dd;
        border-radius: 7px;
        background: #fff;
        color: #243047;
      }
      .rx-freq {
        width: 72px;
      }
      #rx-selection-summary {
        color: #546174;
        font-size: 11px;
        white-space: nowrap;
      }
      .rx-input-short input {
        width: 50px;
      }
      .rx-input-wide input {
        width: 70px;
      }
      #rx-method-note {
        font-size: 10px;
        color: #7a2e2e;
        line-height: 1.25;
        margin-top: 3px;
      }
      @media (max-width: 900px) {
        .rx-control-table {
          grid-template-columns: 76px minmax(0, 1fr);
        }
      }
    </style>
    <div id="rx-step-root">
      <div class="rx-control-table">
        <div class="rx-label">Frequency</div>
        <div class="rx-row">
          <button id="rx-prev" type="button" class="rx-btn">&#8592; Prev frequency</button>
          <button id="rx-next" type="button" class="rx-btn">Next frequency &#8594;</button>
          <label class="rx-th rx-input-wide">Set f (Hz) <input id="rx-freq" class="rx-freq" type="number" step="any" /></label>
          <button id="rx-freq-apply" type="button" class="rx-btn">Set</button>
        </div>
        <div class="rx-label">Energinet</div>
        <div class="rx-row">
          <label class="rx-method-check">
            <input id="rx-method-energinet" type="checkbox" />
            <span id="rx-method-energinet-label">Energinet</span>
          </label>
          <label class="rx-th">T2 <input id="rx-t2" type="number" min="1" step="1" /></label>
          <label class="rx-th">T3 <input id="rx-t3" type="number" min="1" step="1" /></label>
          <label class="rx-th">T4 <input id="rx-t4" type="number" min="1" step="1" /></label>
          <label class="rx-th rx-input-short">Top N <input id="rx-en-topn" type="number" min="0" step="1" value="0" /></label>
        </div>
        <div class="rx-label">IEC</div>
        <div class="rx-row">
          <label class="rx-method-check">
            <input id="rx-method-iec" type="checkbox" />
            <span id="rx-method-iec-label">IEC</span>
          </label>
          <label class="rx-th rx-input-short">Top N <input id="rx-iec-topn" type="number" min="0" step="1" value="0" /></label>
          <label class="rx-method-check">
            <input id="rx-iec-capacitive" type="checkbox" />
            <span id="rx-iec-capacitive-label">Capacitive (0)</span>
          </label>
        </div>
        <div class="rx-label rx-label-last">Selection</div>
        <div class="rx-row rx-row-last">
          <label class="rx-showonly">
            <input id="rx-showonly" type="checkbox" />
            <span>Hide unselected</span>
          </label>
          <span id="rx-selection-summary">Selected 0 | Visible 0 | Hidden 0</span>
          <button id="rx-clear-selection" type="button" class="rx-btn">Clear</button>
          <button id="rx-download-csv" type="button" class="rx-btn">Download CSV</button>
        </div>
      </div>
      <div id="rx-method-note"></div>
    </div>
  `;

  const prev = document.getElementById("rx-prev");
  const next = document.getElementById("rx-next");
  const freqInput = document.getElementById("rx-freq");
  const freqApplyBtn = document.getElementById("rx-freq-apply");
  const showOnly = document.getElementById("rx-showonly");
  const energinetCb = document.getElementById("rx-method-energinet");
  const iecCb = document.getElementById("rx-method-iec");
  const iecCapacitiveCb = document.getElementById("rx-iec-capacitive");
  const t2 = document.getElementById("rx-t2");
  const t3 = document.getElementById("rx-t3");
  const t4 = document.getElementById("rx-t4");
  const enTopN = document.getElementById("rx-en-topn");
  const iecTopN = document.getElementById("rx-iec-topn");
  const clearSelectionBtn = document.getElementById("rx-clear-selection");
  const downloadCsvBtn = document.getElementById("rx-download-csv");

  if (prev) prev.addEventListener("click", (ev) => { ev.preventDefault(); stepFrequency(-1, stateKey); });
  if (next) next.addEventListener("click", (ev) => { ev.preventDefault(); stepFrequency(1, stateKey); });
  if (freqApplyBtn) {
    freqApplyBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      pushExactFrequency(stateKey);
    });
  }
  if (freqInput) {
    freqInput.addEventListener("change", () => {
      pushExactFrequency(stateKey);
    });
    freqInput.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      ev.preventDefault();
      pushExactFrequency(stateKey);
    });
  }

  if (showOnly) {
    showOnly.addEventListener("change", () => {
      try {
        const api = getSelectionApi(stateKey);
        if (api && typeof api.setShowOnlySelected === "function") {
          api.setShowOnlySelected(Boolean(showOnly.checked));
        }
      } catch (e) {
        debugWarn("showOnly.change", e);
      }
    });
  }
  if (clearSelectionBtn) {
    clearSelectionBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      try {
        const api = getSelectionApi(stateKey);
        if (api && typeof api.clearSelection === "function") {
          api.clearSelection();
          syncSelectionControls(stateKey, true);
        }
      } catch (e) {
        debugWarn("clearSelection.click", e);
      }
    });
  }
  if (downloadCsvBtn) {
    downloadCsvBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      try {
        const api = getSelectionApi(stateKey);
        if (api && typeof api.downloadSelectedCsv === "function") {
          api.downloadSelectedCsv();
          syncSelectionControls(stateKey, true);
        }
      } catch (e) {
        debugWarn("downloadCsv.click", e);
      }
    });
  }
  if (energinetCb) {
    energinetCb.addEventListener("change", () => {
      try {
        const api = getSelectionApi(stateKey);
        if (api && typeof api.setEnerginetEnabled === "function") {
          api.setEnerginetEnabled(Boolean(energinetCb.checked));
          syncSelectionControls(stateKey, true);
        }
      } catch (e) {
        debugWarn("energinet.change", e);
      }
    });
  }
  if (iecCb) {
    iecCb.addEventListener("change", () => {
      try {
        const api = getSelectionApi(stateKey);
        if (api && typeof api.setIecEnabled === "function") {
          api.setIecEnabled(Boolean(iecCb.checked));
          syncSelectionControls(stateKey, true);
        }
      } catch (e) {
        debugWarn("iec.change", e);
      }
    });
  }
  if (iecCapacitiveCb) {
    iecCapacitiveCb.addEventListener("change", () => {
      pushIecCapacitiveMode(stateKey, Boolean(iecCapacitiveCb.checked));
    });
  }

  const thresholdInputs = [t2, t3, t4].filter(Boolean);
  for (const inp of thresholdInputs) {
    inp.addEventListener("input", () => {
      try {
        if (thresholdDebounceTimer) clearTimeout(thresholdDebounceTimer);
        thresholdDebounceTimer = setTimeout(() => {
          pushEnerginetThresholds(stateKey);
        }, 220);
      } catch (e) {
        debugWarn("threshold.input", e);
      }
    });
    inp.addEventListener("change", () => {
      pushEnerginetThresholds(stateKey);
    });
  }

  const topNInputs = [
    { el: enTopN, push: () => pushEnerginetTopN(stateKey) },
    { el: iecTopN, push: () => pushIecTopN(stateKey) },
  ].filter((row) => Boolean(row.el));
  for (const row of topNInputs) {
    const el = row.el;
    el.addEventListener("input", () => {
      try {
        if (thresholdDebounceTimer) clearTimeout(thresholdDebounceTimer);
        thresholdDebounceTimer = setTimeout(() => {
          row.push();
        }, 220);
      } catch (e) {
        debugWarn("topN.input", e);
      }
    });
    el.addEventListener("change", () => {
      row.push();
    });
  }

  installSelectionSync(stateKey);
  syncSelectionControls(stateKey, true);
  sendFrameHeightIfNeeded();
  setTimeout(sendFrameHeightIfNeeded, 80);
}

window.addEventListener("message", (event) => {
  const data = event && event.data ? event.data : null;
  if (!data || data.type !== "streamlit:render") return;
  latestArgs = data.args || {};
  render();
});

sendToStreamlit("streamlit:componentReady", { apiVersion: 1 });
sendToStreamlit("streamlit:setFrameHeight", { height: 112 });

window.addEventListener("beforeunload", () => {
  clearSelectionSyncBindings();
});

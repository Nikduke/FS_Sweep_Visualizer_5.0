// Selection-table and selection-API module.
// This file is loaded before listener.js and provides shared helpers
// used by the panel renderer and scatter toolbar bridge.

const CASE_UI_API_GLOBAL = "__fsCaseUiApi";

function selectionApiWarn(scope, err) {
  try {
    if (typeof debugWarn === "function") debugWarn(scope, err);
  } catch (e) {
    // Optional debug logging must never affect selection behavior.
  }
}

function tokenizeImportList(rawText) {
  const txt = String(rawText || "").trim();
  if (!txt) return [];
  const parts = txt.split(/[\s,;]+/g).map((x) => x.trim()).filter((x) => x.length > 0);
  const seen = new Set();
  const out = [];
  for (const p of parts) {
    const k = p.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(p);
  }
  return out;
}

function selectedRowsForTable(ctx, allowedSet) {
  const rows = [];
  for (const caseId of Array.from(ctx.state.selectedCases)) {
    const item = ctx.caseById.get(caseId);
    const displayCase = item ? String(item.display_case || caseId) : caseId;
    rows.push({
      caseId,
      displayCase,
      hidden: !allowedSet.has(caseId),
    });
  }
  rows.sort((a, b) => a.displayCase.localeCompare(b.displayCase));
  return rows;
}

function downloadSelectedCsv(rows) {
  const lines = ["case_id,display_case,status"];
  for (const r of rows) {
    const status = r.hidden ? "hidden_by_case_parts" : "visible";
    const caseIdEsc = String(r.caseId).split('"').join('""');
    const dispEsc = String(r.displayCase).split('"').join('""');
    lines.push(
      `"${caseIdEsc}","${dispEsc}","${status}"`,
    );
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = "selected_cases.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } catch (e) {
    selectionApiWarn("downloadSelectedCsv.click", e);
  }
  try {
    URL.revokeObjectURL(url);
  } catch (e) {
    selectionApiWarn("downloadSelectedCsv.revokeObjectURL", e);
  }
}

function getApiStore() {
  const root = rootWindow();
  if (!root[CASE_UI_API_GLOBAL] || typeof root[CASE_UI_API_GLOBAL] !== "object") {
    root[CASE_UI_API_GLOBAL] = {};
  }
  return root[CASE_UI_API_GLOBAL];
}

function applyStateToPlots() {
  try {
    if (typeof scheduleApplyPasses === "function") {
      scheduleApplyPasses();
      return;
    }
  } catch (e) {
    selectionApiWarn("applyStateToPlots.schedule", e);
  }
  try {
    applyAllPlots();
  } catch (e) {
    selectionApiWarn("applyStateToPlots.apply", e);
  }
}

function notifyExternalSelectionStateChanged(ctx, scope) {
  try {
    if (typeof notifySelectionStateChanged === "function") notifySelectionStateChanged(ctx);
  } catch (e) {
    selectionApiWarn(scope || "notifyExternalSelectionStateChanged", e);
  }
}

function anyMethodEnabled(state) {
  const st = state && typeof state === "object" ? state : {};
  return Boolean(
    st.methodEnerginetEnabled
    || st.methodIecEnabled
    || st.methodPeakZEnabled
    || st.methodPeakXEnabled
    || st.methodRiskEnabled
    || st.methodOutlierEnabled,
  );
}

function commitSelectionApiChange(label, mutate) {
  const nextCtx = ensureContext();
  if (!nextCtx) return false;
  if (typeof mutate === "function") mutate(nextCtx);
  recomputeSelectedCases(nextCtx);
  nextCtx.state.importStatus = "";
  bumpStateVersion(nextCtx.state);
  renderPanel();
  applyStateToPlots();
  notifyExternalSelectionStateChanged(nextCtx, `${label}.notify`);
  return true;
}

function setMethodEnabled(nextCtx, enabledField, flag, capacitiveField) {
  nextCtx.state[enabledField] = Boolean(flag);
  if (capacitiveField && !nextCtx.state[enabledField]) {
    nextCtx.state[capacitiveField] = false;
  }
  if (!anyMethodEnabled(nextCtx.state)) {
    nextCtx.state.methodExcludedCases = new Set();
  }
}

function setCapacitiveOnly(nextCtx, enabledField, capacitiveField, flag) {
  nextCtx.state[capacitiveField] = nextCtx.state[enabledField] ? flag === true : false;
}

function registerExternalSelectionApi(ctx) {
  if (!ctx) return;
  const key = `${ctx.dataId}|${ctx.chartId}`;
  const store = getApiStore();
  if (typeof pruneStoreByStateKey === "function") {
    pruneStoreByStateKey(store, key);
  } else {
    pruneStoreByDataId(store, ctx.dataId);
  }
  store[key] = {
    getState: () => {
      const curCtx = typeof ensureContext === "function" ? ensureContext() : (ctx && ctx.state ? ctx : null);
      if (!curCtx || !curCtx.state) return null;
      const st = curCtx.state || {};
      const energinetRawSet = st.methodEnerginetCasesRaw instanceof Set ? st.methodEnerginetCasesRaw : new Set();
      const iecRawSet = st.methodIecCasesRaw instanceof Set ? st.methodIecCasesRaw : new Set();
      const iecAllRawSet = st.methodIecCasesRawAll instanceof Set ? st.methodIecCasesRawAll : iecRawSet;
      const iecCapacitiveRawSet = st.methodIecCasesRawCapacitive instanceof Set ? st.methodIecCasesRawCapacitive : iecRawSet;
      const peakZRawSet = st.methodPeakZCasesRaw instanceof Set ? st.methodPeakZCasesRaw : new Set();
      const peakZAllRawSet = st.methodPeakZCasesRawAll instanceof Set ? st.methodPeakZCasesRawAll : peakZRawSet;
      const peakZCapacitiveRawSet = st.methodPeakZCasesRawCapacitive instanceof Set ? st.methodPeakZCasesRawCapacitive : peakZRawSet;
      const peakZExactRawSet = st.methodPeakZCapacitiveOnly
        ? (st.methodPeakZExactCasesRawCapacitive instanceof Set ? st.methodPeakZExactCasesRawCapacitive : new Set())
        : (st.methodPeakZExactCasesRawAll instanceof Set ? st.methodPeakZExactCasesRawAll : new Set());
      const peakZBandRawSet = st.methodPeakZCapacitiveOnly
        ? (st.methodPeakZBandCasesRawCapacitive instanceof Set ? st.methodPeakZBandCasesRawCapacitive : new Set())
        : (st.methodPeakZBandCasesRawAll instanceof Set ? st.methodPeakZBandCasesRawAll : new Set());
      const peakXRawSet = st.methodPeakXCasesRaw instanceof Set ? st.methodPeakXCasesRaw : new Set();
      const peakXAllRawSet = st.methodPeakXCasesRawAll instanceof Set ? st.methodPeakXCasesRawAll : peakXRawSet;
      const peakXCapacitiveRawSet = st.methodPeakXCasesRawCapacitive instanceof Set ? st.methodPeakXCasesRawCapacitive : peakXRawSet;
      const peakXExactRawSet = st.methodPeakXCapacitiveOnly
        ? (st.methodPeakXExactCasesRawCapacitive instanceof Set ? st.methodPeakXExactCasesRawCapacitive : new Set())
        : (st.methodPeakXExactCasesRawAll instanceof Set ? st.methodPeakXExactCasesRawAll : new Set());
      const peakXBandRawSet = st.methodPeakXCapacitiveOnly
        ? (st.methodPeakXBandCasesRawCapacitive instanceof Set ? st.methodPeakXBandCasesRawCapacitive : new Set())
        : (st.methodPeakXBandCasesRawAll instanceof Set ? st.methodPeakXBandCasesRawAll : new Set());
      const riskRawSet = st.methodRiskCasesRaw instanceof Set ? st.methodRiskCasesRaw : new Set();
      const riskAllRawSet = st.methodRiskCasesRawAll instanceof Set ? st.methodRiskCasesRawAll : riskRawSet;
      const riskCapacitiveRawSet = st.methodRiskCasesRawCapacitive instanceof Set ? st.methodRiskCasesRawCapacitive : riskRawSet;
      const outlierRawSet = st.methodOutlierCasesRaw instanceof Set ? st.methodOutlierCasesRaw : new Set();
      const outlierAllRawSet = st.methodOutlierCasesRawAll instanceof Set ? st.methodOutlierCasesRawAll : outlierRawSet;
      const outlierCapacitiveRawSet = st.methodOutlierCasesRawCapacitive instanceof Set ? st.methodOutlierCasesRawCapacitive : outlierRawSet;
      const allowed = computeAllowedSet(curCtx);
      const selectedRows = selectedRowsForTable(curCtx, allowed);
      const hiddenSelectedCount = selectedRows.filter((row) => row.hidden).length;
      const countVisible = (srcSet) => {
        let n = 0;
        for (const cid of srcSet) {
          if (allowed.has(cid)) n += 1;
        }
        return n;
      };
      const energinetVisible = countVisible(energinetRawSet);
      const iecVisible = countVisible(iecRawSet);
      const iecAllVisible = countVisible(iecAllRawSet);
      const iecCapacitiveVisible = countVisible(iecCapacitiveRawSet);
      const peakZVisible = countVisible(peakZRawSet);
      const peakZAllVisible = countVisible(peakZAllRawSet);
      const peakZCapacitiveVisible = countVisible(peakZCapacitiveRawSet);
      const peakZExactVisible = countVisible(peakZExactRawSet);
      const peakZBandVisible = countVisible(peakZBandRawSet);
      const peakXVisible = countVisible(peakXRawSet);
      const peakXAllVisible = countVisible(peakXAllRawSet);
      const peakXCapacitiveVisible = countVisible(peakXCapacitiveRawSet);
      const peakXExactVisible = countVisible(peakXExactRawSet);
      const peakXBandVisible = countVisible(peakXBandRawSet);
      const riskVisible = countVisible(riskRawSet);
      const riskAllVisible = countVisible(riskAllRawSet);
      const riskCapacitiveVisible = countVisible(riskCapacitiveRawSet);
      const outlierVisible = countVisible(outlierRawSet);
      const outlierAllVisible = countVisible(outlierAllRawSet);
      const outlierCapacitiveVisible = countVisible(outlierCapacitiveRawSet);
      const pre = getPreselectionPayload();
      const rxInfo = typeof getScatterFrequencyInfo === "function" ? getScatterFrequencyInfo() : null;
      return {
        stateVersion: Number(st.__applyVersion != null ? st.__applyVersion : 0),
        showOnlySelected: st.showOnlySelected === true,
        selectedCount: Number(st.selectedCases instanceof Set ? st.selectedCases.size : 0),
        selectedRows: selectedRows.map((row) => ({
          caseId: String(row.caseId || ""),
          displayCase: String(row.displayCase || row.caseId || ""),
          hidden: Boolean(row.hidden),
        })),
        visibleSelectedCount: Number(Math.max(0, selectedRows.length - hiddenSelectedCount)),
        hiddenSelectedCount: Number(hiddenSelectedCount),
        visibleCaseCount: Number(allowed.size || 0),
        preselectionAvailable: Boolean(isPreselectionAvailable(curCtx)),
        preselectionError: String(pre && pre.error ? pre.error : ""),
        limitationNote: String(pre && pre.limitation_note ? pre.limitation_note : ""),
        energinetEnabled: Boolean(st.methodEnerginetEnabled),
        iecEnabled: Boolean(st.methodIecEnabled),
        iecCapacitiveOnly: Boolean(st.methodIecCapacitiveOnly),
        peakZEnabled: Boolean(st.methodPeakZEnabled),
        peakZCapacitiveOnly: Boolean(st.methodPeakZCapacitiveOnly),
        peakZExactEnabled: Boolean(st.methodPeakZExactEnabled),
        peakZBandEnabled: Boolean(st.methodPeakZBandEnabled),
        peakXEnabled: Boolean(st.methodPeakXEnabled),
        peakXCapacitiveOnly: Boolean(st.methodPeakXCapacitiveOnly),
        peakXExactEnabled: Boolean(st.methodPeakXExactEnabled),
        peakXBandEnabled: Boolean(st.methodPeakXBandEnabled),
        riskEnabled: Boolean(st.methodRiskEnabled),
        riskCapacitiveOnly: Boolean(st.methodRiskCapacitiveOnly),
        outlierEnabled: Boolean(st.methodOutlierEnabled),
        outlierCapacitiveOnly: Boolean(st.methodOutlierCapacitiveOnly),
        energinetT2: Number(st.energinetT2 || 0),
        energinetT3: Number(st.energinetT3 || 0),
        energinetT4: Number(st.energinetT4 || 0),
        energinetTopN: Number(st.methodEnerginetTopN || 0),
        iecTopN: Number(st.methodIecTopN || 0),
        peakZTopN: Number(st.methodPeakZTopN || 0),
        peakXTopN: Number(st.methodPeakXTopN || 0),
        riskTopN: Number(st.methodRiskTopN || 0),
        outlierTopN: Number(st.methodOutlierTopN || 0),
        energinetCandidateCount: Number(energinetVisible),
        iecCandidateCount: Number(iecVisible),
        iecAllCandidateCount: Number(iecAllVisible),
        iecCapacitiveCandidateCount: Number(iecCapacitiveVisible),
        peakZCandidateCount: Number(peakZVisible),
        peakZAllCandidateCount: Number(peakZAllVisible),
        peakZCapacitiveCandidateCount: Number(peakZCapacitiveVisible),
        peakZExactCandidateCount: Number(peakZExactVisible),
        peakZBandCandidateCount: Number(peakZBandVisible),
        peakXCandidateCount: Number(peakXVisible),
        peakXAllCandidateCount: Number(peakXAllVisible),
        peakXCapacitiveCandidateCount: Number(peakXCapacitiveVisible),
        peakXExactCandidateCount: Number(peakXExactVisible),
        peakXBandCandidateCount: Number(peakXBandVisible),
        riskCandidateCount: Number(riskVisible),
        riskAllCandidateCount: Number(riskAllVisible),
        riskCapacitiveCandidateCount: Number(riskCapacitiveVisible),
        outlierCandidateCount: Number(outlierVisible),
        outlierAllCandidateCount: Number(outlierAllVisible),
        outlierCapacitiveCandidateCount: Number(outlierCapacitiveVisible),
        rxCurrentFrequencyHz: Number(rxInfo && Number.isFinite(rxInfo.freqHz) ? rxInfo.freqHz : Number.NaN),
        rxFrequencyMinHz: Number(rxInfo && Number.isFinite(rxInfo.minHz) ? rxInfo.minHz : Number.NaN),
        rxFrequencyMaxHz: Number(rxInfo && Number.isFinite(rxInfo.maxHz) ? rxInfo.maxHz : Number.NaN),
        rxFrequencyStepCount: Number(rxInfo && Number.isFinite(rxInfo.stepCount) ? rxInfo.stepCount : 0),
      };
    },
    setShowOnlySelected: (flag) => {
      return commitSelectionApiChange("setShowOnlySelected", (nextCtx) => {
        nextCtx.state.showOnlySelected = flag === true;
      });
    },
    setEnerginetEnabled: (flag) => {
      return commitSelectionApiChange("setEnerginetEnabled", (nextCtx) => {
        setMethodEnabled(nextCtx, "methodEnerginetEnabled", flag);
      });
    },
    setIecEnabled: (flag) => {
      return commitSelectionApiChange("setIecEnabled", (nextCtx) => {
        setMethodEnabled(nextCtx, "methodIecEnabled", flag, "methodIecCapacitiveOnly");
      });
    },
    setPeakZEnabled: (flag) => {
      return commitSelectionApiChange("setPeakZEnabled", (nextCtx) => {
        setMethodEnabled(nextCtx, "methodPeakZEnabled", flag, "methodPeakZCapacitiveOnly");
      });
    },
    setPeakXEnabled: (flag) => {
      return commitSelectionApiChange("setPeakXEnabled", (nextCtx) => {
        setMethodEnabled(nextCtx, "methodPeakXEnabled", flag, "methodPeakXCapacitiveOnly");
      });
    },
    setRiskEnabled: (flag) => {
      return commitSelectionApiChange("setRiskEnabled", (nextCtx) => {
        setMethodEnabled(nextCtx, "methodRiskEnabled", flag, "methodRiskCapacitiveOnly");
      });
    },
    setOutlierEnabled: (flag) => {
      return commitSelectionApiChange("setOutlierEnabled", (nextCtx) => {
        setMethodEnabled(nextCtx, "methodOutlierEnabled", flag, "methodOutlierCapacitiveOnly");
      });
    },
    setEnerginetThresholds: (thresholds) => {
      return commitSelectionApiChange("setEnerginetThresholds", (nextCtx) => {
        const th = thresholds && typeof thresholds === "object" ? thresholds : {};
        const d = preselectionThresholdDefaults();
        const t2 = Number(th.t2 != null ? th.t2 : nextCtx.state.energinetT2);
        const t3 = Number(th.t3 != null ? th.t3 : nextCtx.state.energinetT3);
        const t4 = Number(th.t4 != null ? th.t4 : nextCtx.state.energinetT4);
        nextCtx.state.energinetT2 = Number.isFinite(t2) && t2 > 0 ? t2 : Number(d.t2);
        nextCtx.state.energinetT3 = Number.isFinite(t3) && t3 > 0 ? t3 : Number(d.t3);
        nextCtx.state.energinetT4 = Number.isFinite(t4) && t4 > 0 ? t4 : Number(d.t4);
      });
    },
    setEnerginetTopN: (rawVal) => {
      return commitSelectionApiChange("setEnerginetTopN", (nextCtx) => {
        nextCtx.state.methodEnerginetTopN = normalizeTopN(rawVal);
      });
    },
    setIecTopN: (rawVal) => {
      return commitSelectionApiChange("setIecTopN", (nextCtx) => {
        nextCtx.state.methodIecTopN = normalizeTopN(rawVal);
      });
    },
    setPeakZTopN: (rawVal) => {
      return commitSelectionApiChange("setPeakZTopN", (nextCtx) => {
        nextCtx.state.methodPeakZTopN = normalizeTopN(rawVal);
      });
    },
    setPeakZExactEnabled: (flag) => {
      return commitSelectionApiChange("setPeakZExactEnabled", (nextCtx) => {
        nextCtx.state.methodPeakZExactEnabled = flag === true;
      });
    },
    setPeakZBandEnabled: (flag) => {
      return commitSelectionApiChange("setPeakZBandEnabled", (nextCtx) => {
        nextCtx.state.methodPeakZBandEnabled = flag === true;
      });
    },
    setPeakXTopN: (rawVal) => {
      return commitSelectionApiChange("setPeakXTopN", (nextCtx) => {
        nextCtx.state.methodPeakXTopN = normalizeTopN(rawVal);
      });
    },
    setPeakXExactEnabled: (flag) => {
      return commitSelectionApiChange("setPeakXExactEnabled", (nextCtx) => {
        nextCtx.state.methodPeakXExactEnabled = flag === true;
      });
    },
    setPeakXBandEnabled: (flag) => {
      return commitSelectionApiChange("setPeakXBandEnabled", (nextCtx) => {
        nextCtx.state.methodPeakXBandEnabled = flag === true;
      });
    },
    setRiskTopN: (rawVal) => {
      return commitSelectionApiChange("setRiskTopN", (nextCtx) => {
        nextCtx.state.methodRiskTopN = normalizeTopN(rawVal);
      });
    },
    setOutlierTopN: (rawVal) => {
      return commitSelectionApiChange("setOutlierTopN", (nextCtx) => {
        nextCtx.state.methodOutlierTopN = normalizeTopN(rawVal);
      });
    },
    setIecCapacitiveOnly: (flag) => {
      return commitSelectionApiChange("setIecCapacitiveOnly", (nextCtx) => {
        setCapacitiveOnly(nextCtx, "methodIecEnabled", "methodIecCapacitiveOnly", flag);
      });
    },
    setPeakZCapacitiveOnly: (flag) => {
      return commitSelectionApiChange("setPeakZCapacitiveOnly", (nextCtx) => {
        setCapacitiveOnly(nextCtx, "methodPeakZEnabled", "methodPeakZCapacitiveOnly", flag);
      });
    },
    setPeakXCapacitiveOnly: (flag) => {
      return commitSelectionApiChange("setPeakXCapacitiveOnly", (nextCtx) => {
        setCapacitiveOnly(nextCtx, "methodPeakXEnabled", "methodPeakXCapacitiveOnly", flag);
      });
    },
    setRiskCapacitiveOnly: (flag) => {
      return commitSelectionApiChange("setRiskCapacitiveOnly", (nextCtx) => {
        setCapacitiveOnly(nextCtx, "methodRiskEnabled", "methodRiskCapacitiveOnly", flag);
      });
    },
    setOutlierCapacitiveOnly: (flag) => {
      return commitSelectionApiChange("setOutlierCapacitiveOnly", (nextCtx) => {
        setCapacitiveOnly(nextCtx, "methodOutlierEnabled", "methodOutlierCapacitiveOnly", flag);
      });
    },
    stepRxFrequency: (delta) => {
      const nextCtx = ensureContext();
      if (!nextCtx) return false;
      if (typeof stepScatterFrequencyByDelta !== "function") return false;
      try {
        return stepScatterFrequencyByDelta(nextCtx, Number(delta || 0)) === true;
      } catch (e) {
        selectionApiWarn("stepRxFrequency", e);
      }
      return false;
    },
    setRxFrequencyHz: (rawVal) => {
      const nextCtx = ensureContext();
      if (!nextCtx) return false;
      if (typeof setScatterFrequencyHz !== "function") return false;
      try {
        return setScatterFrequencyHz(nextCtx, rawVal) === true;
      } catch (e) {
        selectionApiWarn("setRxFrequencyHz", e);
      }
      return false;
    },
    clearSelection: () => {
      const nextCtx = ensureContext();
      if (!nextCtx) return false;
      resetSelectionState(nextCtx.state);
      recomputeSelectedCases(nextCtx);
      bumpStateVersion(nextCtx.state);
      renderPanel();
      applyStateToPlots();
      notifyExternalSelectionStateChanged(nextCtx, "clearSelection.notify");
      return true;
    },
    downloadSelectedCsv: () => {
      const nextCtx = ensureContext();
      if (!nextCtx) return false;
      const allowed = computeAllowedSet(nextCtx);
      const rows = selectedRowsForTable(nextCtx, allowed);
      downloadSelectedCsv(rows);
      return true;
    },
  };
}

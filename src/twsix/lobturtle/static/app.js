/* LobTurtle Interactive Quantitative Dashboard & Macro Strategy Engine (app.js)
 * - Dual Theme Engine: Default Institutional Dark Mode + Crisp Light Mode (persisted in localStorage)
 * - Mobile-First Touch Ergonomics: Responsive Y-axis/ticks, touch crosshair inspection, swipeable tabs & tables
 * - 5+ Years History across all chart tabs (2020/11/05 ~ Latest)
 * - Preset Zoom Buttons (<縮放區間>) + Dual-Thumb Range Slider (<顯示區間滑桿>) on EVERY chart tab
 * - Per-Chart Deep Theoretical Dissection & Real-Time Window Telemetry on ALL charts
 * - Full-Spectrum International/Domestic Macro & Multi-Horizon Investment Strategy Hub
 */
(function () {
  "use strict";

  const PRESETS = [
    { label: "近1月", days: 22 },
    { label: "近3月", days: 65 },
    { label: "近半年", days: 130 },
    { label: "近1年", days: 245 },
    { label: "近2年", days: 490 },
    { label: "近3年", days: 735 },
    { label: "近5年", days: 1220 },
    { label: "全部", days: 0 },
  ];

  let currentTab = "lobster";
  const tabRanges = {};
  let cachedStrategyOverview = null;
  const activeCharts = new Set();

  /* ==========================================================================
   * Theme Management (Default: Dark Mode) & Live Chart.js Re-Theming
   * ========================================================================== */
  function getTheme() {
    return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
  }

  function isMobileViewport() {
    return window.innerWidth <= 640;
  }

  function getYAxisWidth() {
    return isMobileViewport() ? 52 : 74;
  }

  function getMaxXTicks() {
    if (window.innerWidth <= 640) return 5;
    if (window.innerWidth <= 960) return 8;
    return 11;
  }

  function getThemePalette() {
    const dark = getTheme() === "dark";
    return {
      dark,
      indexLine: dark ? "#38bdf8" : "#0f172a",
      tickColor: dark ? "#94a3b8" : "#475569",
      gridColor: dark ? "rgba(148, 163, 184, 0.11)" : "rgba(15, 23, 42, 0.07)",
      borderColor: dark ? "rgba(148, 163, 184, 0.22)" : "rgba(15, 23, 42, 0.14)",
      crosshair: dark ? "rgba(56, 189, 248, 0.85)" : "rgba(37, 99, 235, 0.78)",
      bullSolid: dark ? "#ef4444" : "#dc2626",
      bearSolid: dark ? "#10b981" : "#16a34a",
      bullBar: dark ? "rgba(248, 113, 113, 0.86)" : "rgba(220, 38, 38, 0.85)",
      bearBar: dark ? "rgba(52, 211, 153, 0.84)" : "rgba(22, 163, 74, 0.85)",
      bullRgb: dark ? "248, 113, 113" : "220, 38, 38",
      bearRgb: dark ? "52, 211, 153" : "22, 163, 74",
      markerBorder: dark ? "#0f172a" : "#ffffff",
    };
  }

  function syncThemeButtonsUI() {
    const dark = getTheme() === "dark";
    const metaTheme = document.getElementById("meta-theme-color");
    if (metaTheme) metaTheme.setAttribute("content", dark ? "#070b14" : "#f1f5f9");

    const desktopBtn = document.getElementById("btn-theme-toggle-desktop");
    if (desktopBtn) {
      desktopBtn.querySelector(".theme-icon").textContent = dark ? "☀️" : "🌙";
      desktopBtn.querySelector(".theme-text").textContent = dark ? "淺色模式" : "深色模式";
    }
    const mobileBtn = document.getElementById("btn-theme-toggle");
    if (mobileBtn) {
      mobileBtn.querySelector(".theme-icon").textContent = dark ? "☀️" : "🌙";
      mobileBtn.querySelector(".theme-text").textContent = dark ? "淺色" : "深色";
    }
  }

  function applyChartDefaults() {
    const pal = getThemePalette();
    Chart.defaults.color = pal.tickColor;
    Chart.defaults.borderColor = pal.gridColor;
  }

  function refreshAllChartsTheme() {
    applyChartDefaults();
    const pal = getThemePalette();
    const maxTicks = getMaxXTicks();

    activeCharts.forEach((ch) => {
      if (!ch || !ch.options) return;
      if (ch.$chartKind === "indexLine" && ch.data.datasets[0]) {
        ch.data.datasets[0].borderColor = pal.indexLine;
        for (let d = 1; d < ch.data.datasets.length; d++) {
          const ds = ch.data.datasets[d];
          if (ds.label === "買進") {
            ds.pointBackgroundColor = pal.bullSolid;
            ds.pointBorderColor = pal.markerBorder;
          } else if (ds.label === "賣出") {
            ds.pointBackgroundColor = pal.bearSolid;
            ds.pointBorderColor = pal.markerBorder;
          }
        }
      }
      if (ch.$chartKind === "thresholdBar" && ch.data.datasets[0] && ch.$rawBarCfg) {
        const { values, threshold, invert } = ch.$rawBarCfg;
        ch.data.datasets[0].backgroundColor = values.map((v) => {
          if (v == null || Number.isNaN(Number(v))) return "rgba(148,163,184,0.22)";
          const isBull = invert ? !(v > threshold) : v > threshold;
          return isBull ? pal.bullBar : pal.bearBar;
        });
      }
      const xSc = ch.options.scales && ch.options.scales.x;
      const ySc = ch.options.scales && ch.options.scales.y;
      if (xSc) {
        xSc.ticks = Object.assign({}, xSc.ticks, { color: pal.tickColor, maxTicksLimit: maxTicks });
        xSc.grid = Object.assign({}, xSc.grid, { color: pal.gridColor });
        xSc.border = Object.assign({}, xSc.border, { color: pal.borderColor });
      }
      if (ySc) {
        ySc.ticks = Object.assign({}, ySc.ticks, { color: pal.tickColor });
        if (ch.$chartKind === "ribbon") {
          ySc.ticks.font = Object.assign({}, ySc.ticks.font, {
            size: isMobileViewport() ? 9.5 : 11,
            weight: "700",
          });
        } else {
          ySc.grid = Object.assign({}, ySc.grid, { color: pal.gridColor });
        }
        ySc.border = Object.assign({}, ySc.border, { color: pal.borderColor });
      }
      ch.update("none");
    });
  }

  function setTheme(nextTheme) {
    const t = nextTheme === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", t);
    try {
      localStorage.setItem("lobturtle-theme", t);
    } catch (_) {}
    syncThemeButtonsUI();
    refreshAllChartsTheme();
  }

  function registerChart(ch) {
    activeCharts.add(ch);
    return ch;
  }

  function destroyChartList(list) {
    list.forEach((c) => {
      activeCharts.delete(c);
      c.destroy();
    });
  }

  applyChartDefaults();
  syncThemeButtonsUI();

  ["btn-theme-toggle", "btn-theme-toggle-desktop"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("click", () => {
        setTheme(getTheme() === "dark" ? "light" : "dark");
      });
    }
  });

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      refreshAllChartsTheme();
    }, 120);
  });

  /* ==========================================================================
   * Shared Helpers & Calculation Utilities
   * ========================================================================== */
  async function fetchStrategyOverview(force = false) {
    if (cachedStrategyOverview && !force) return cachedStrategyOverview;
    cachedStrategyOverview = await fetch("/api/strategy/overview").then((r) => r.json());
    return cachedStrategyOverview;
  }

  function fmtNum(v, digits = 2) {
    if (v == null || Number.isNaN(Number(v))) return "-";
    return Number(v).toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function calcWindowIndexStats(points, s, e) {
    const vals = [];
    for (let i = s; i <= e; i++) {
      if (points[i] != null && !Number.isNaN(Number(points[i]))) vals.push(Number(points[i]));
    }
    if (!vals.length) return { retPct: 0, mddPct: 0, volPct: 0, hi: 0, lo: 0, last: 0 };
    const first = vals[0];
    const last = vals[vals.length - 1];
    const retPct = first > 0 ? (last / first - 1) * 100 : 0;
    let peak = vals[0];
    let mdd = 0;
    const rets = [];
    for (let i = 0; i < vals.length; i++) {
      if (vals[i] > peak) peak = vals[i];
      const dd = peak > 0 ? (vals[i] / peak - 1) * 100 : 0;
      if (dd < mdd) mdd = dd;
      if (i > 0 && vals[i - 1] > 0) rets.push((vals[i] - vals[i - 1]) / vals[i - 1]);
    }
    let volPct = 0;
    if (rets.length >= 2) {
      const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
      const variance = rets.reduce((a, b) => a + (b - mean) * (b - mean), 0) / (rets.length - 1);
      volPct = Math.sqrt(variance) * Math.sqrt(245) * 100;
    }
    return {
      retPct: Math.round(retPct * 100) / 100,
      mddPct: Math.round(mdd * 100) / 100,
      volPct: Math.round(volPct * 100) / 100,
      hi: Math.max(...vals),
      lo: Math.min(...vals),
      last,
    };
  }

  function calcSignalWindowStats(values, s, e, isBullFn = (v) => v > 0) {
    let bullCnt = 0;
    let validCnt = 0;
    let flips = 0;
    let prevBull = null;
    let streak = 0;
    for (let i = s; i <= e; i++) {
      const v = values[i];
      if (v == null || Number.isNaN(Number(v))) continue;
      const b = isBullFn(Number(v));
      validCnt++;
      if (b) bullCnt++;
      if (prevBull !== null && b !== prevBull) {
        flips++;
        streak = 1;
      } else {
        streak++;
      }
      prevBull = b;
    }
    const bullPct = validCnt > 0 ? Math.round((bullCnt / validCnt) * 1000) / 10 : 0;
    const avgHold = flips > 0 ? Math.round((validCnt / (flips + 1)) * 10) / 10 : validCnt;
    return { validCnt, bullCnt, bullPct, flips, avgHold, streak, lastBull: prevBull };
  }

  function renderAnalysisNoteHTML(pills, col1Title, col1Html, col2Title, col2Html) {
    const pillsHtml = pills
      .map((p) => `<span class="diag-pill ${p.cls || ""}">${p.text}</span>`)
      .join("");
    return `
      <div class="live-diag-bar">${pillsHtml}</div>
      <div class="chart-analysis-grid">
        <div class="chart-analysis-col">
          <strong class="col-title">🔬 ${col1Title}</strong>
          <div>${col1Html}</div>
        </div>
        <div class="chart-analysis-col">
          <strong class="col-title">🧭 ${col2Title}</strong>
          <div>${col2Html}</div>
        </div>
      </div>
    `;
  }

  function updatePdfHref() {
    const pdfBtn = document.getElementById("btn-download-pdf");
    if (!pdfBtn) return;
    const fullLbl = pdfBtn.querySelector(".btn-label-full");
    const rng = tabRanges[currentTab];
    if (rng && rng.startDate && rng.endDate) {
      pdfBtn.href = `/api/report/lobster.pdf?start=${encodeURIComponent(rng.startDate)}&end=${encodeURIComponent(rng.endDate)}`;
      if (fullLbl) fullLbl.textContent = `無浮水印 PDF 報表 (${rng.startDate}~${rng.endDate})`;
    } else {
      pdfBtn.href = "/api/report/lobster.pdf";
      if (fullLbl) fullLbl.textContent = "無浮水印 PDF 報表 (近1年)";
    }
  }

  // Synchronized vertical crosshair + ribbon & family-divider rendering plugin
  const lobCustomPlugin = {
    id: "lobCustomPlugin",
    beforeDatasetsDraw(chart) {
      const rib = chart.$ribbonRows;
      if (!rib || !rib.length) return;
      const firstValid = rib.find((r) => !r.isDivider && r.values && r.values.length);
      if (!firstValid) return;
      const { ctx, chartArea, scales } = chart;
      if (!chartArea || !scales.x || !scales.y) return;
      const pal = getThemePalette();
      const xScale = scales.x;
      const yScale = scales.y;
      const seriesLen = firstValid.values.length;
      const minIdx = Math.max(0, Math.floor(xScale.min ?? 0));
      const maxIdx = Math.min(seriesLen - 1, Math.ceil(xScale.max ?? (seriesLen - 1)));
      if (maxIdx < minIdx) return;

      const count = maxIdx - minIdx + 1;
      const stepPx = count > 1 ? (xScale.getPixelForValue(maxIdx) - xScale.getPixelForValue(minIdx)) / (count - 1) : chartArea.width;
      const halfW = Math.max(0.6, stepPx / 2 + 0.45);
      const slotH = chartArea.height / Math.max(1, rib.length);
      const bandH = rib.length === 1 ? Math.min(28, chartArea.height * 0.64) : Math.min(18, slotH * 0.76);

      ctx.save();
      ctx.beginPath();
      ctx.rect(chartArea.left, chartArea.top, chartArea.width, chartArea.height);
      ctx.clip();

      rib.forEach((row, rIdx) => {
        const cy = yScale.getPixelForValue(rIdx);
        if (row.isDivider) {
          ctx.save();
          ctx.beginPath();
          ctx.moveTo(chartArea.left, cy);
          ctx.lineTo(chartArea.right, cy);
          ctx.lineWidth = 1;
          ctx.strokeStyle = pal.borderColor;
          ctx.setLineDash([4, 4]);
          ctx.stroke();
          ctx.restore();
          return;
        }
        const topY = cy - bandH / 2;
        for (let i = minIdx; i <= maxIdx; i++) {
          const val = row.values[i];
          if (val == null) continue;
          const cx = xScale.getPixelForValue(i);
          const x0 = Math.max(chartArea.left, cx - halfW);
          const x1 = Math.min(chartArea.right, cx + halfW);
          ctx.fillStyle = val > 0 ? pal.bullSolid : pal.bearSolid;
          ctx.fillRect(x0, topY, Math.max(1, x1 - x0), bandH);
        }
      });
      ctx.restore();
    },
    afterDraw(chart) {
      const idx = chart.$hoverIdx;
      if (idx == null || idx < 0) return;
      const xScale = chart.scales.x;
      if (!xScale) return;
      const minIdx = xScale.min ?? 0;
      const maxIdx = xScale.max ?? (chart.data.labels.length - 1);
      if (idx < minIdx || idx > maxIdx) return;

      const x = xScale.getPixelForValue(idx);
      const { top, bottom, left, right } = chart.chartArea;
      if (x < left || x > right) return;

      const pal = getThemePalette();
      const ctx = chart.ctx;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.lineWidth = 1.2;
      ctx.strokeStyle = pal.crosshair;
      ctx.setLineDash([4, 3]);
      ctx.stroke();
      ctx.restore();
    },
  };
  Chart.register(lobCustomPlugin);

  function fixedLeftAxis(extra = {}) {
    const pal = getThemePalette();
    return Object.assign(
      {
        position: "left",
        ticks: { color: pal.tickColor, font: { size: isMobileViewport() ? 10 : 11 } },
        grid: { color: pal.gridColor },
        border: { color: pal.borderColor },
        afterFit(scale) {
          scale.width = getYAxisWidth();
        },
      },
      extra
    );
  }

  function baseXAxis(offsetBar = false, showLabels = true) {
    const pal = getThemePalette();
    return {
      offset: offsetBar,
      ticks: {
        display: showLabels,
        color: pal.tickColor,
        maxTicksLimit: getMaxXTicks(),
        maxRotation: 0,
        font: { size: isMobileViewport() ? 10 : 11 },
      },
      grid: { color: pal.gridColor },
      border: { color: pal.borderColor },
    };
  }

  function makeZeroSignGradient(chart, alphaTop, alphaBot) {
    const pal = getThemePalette();
    const { ctx, chartArea, scales } = chart;
    if (!chartArea || !scales.y) return `rgba(${pal.bullRgb}, ${alphaTop})`;
    const y0 = scales.y.getPixelForValue(0);
    const top = chartArea.top;
    const bottom = chartArea.bottom;
    const h = Math.max(1, bottom - top);
    const ratio = Math.max(0, Math.min(1, (y0 - top) / h));
    const grad = ctx.createLinearGradient(0, top, 0, bottom);
    grad.addColorStop(0, `rgba(${pal.bullRgb}, ${alphaTop})`);
    grad.addColorStop(ratio, `rgba(${pal.bullRgb}, ${alphaTop})`);
    grad.addColorStop(ratio, `rgba(${pal.bearRgb}, ${alphaBot})`);
    grad.addColorStop(1, `rgba(${pal.bearRgb}, ${alphaBot})`);
    return grad;
  }

  function rollingSum(values, windowSize) {
    const w = Math.max(1, parseInt(windowSize, 10) || 1);
    const out = new Array(values.length).fill(null);
    let sum = 0;
    let cnt = 0;
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      if (v != null && !Number.isNaN(Number(v))) {
        sum += Number(v);
        cnt++;
      }
      if (i >= w) {
        const old = values[i - w];
        if (old != null && !Number.isNaN(Number(old))) {
          sum -= Number(old);
          cnt--;
        }
      }
      if (i >= w - 1 && cnt > 0) {
        out[i] = Math.round(sum * 100) / 100;
      }
    }
    return out;
  }

  /**
   * Builds BOTH <縮放區間> preset buttons AND <顯示區間滑桿> dual-thumb range slider.
   */
  function buildZoomAndSliderControls(containerEl, tabName, labels, defaultDays, onRangeChange) {
    const total = labels.length;
    if (total === 0) return { getRange: () => [0, 0], applyToCharts: () => {} };

    let startIdx = defaultDays > 0 ? Math.max(0, total - defaultDays) : 0;
    let endIdx = total - 1;
    const minSpan = Math.min(5, Math.max(1, total - 1));

    containerEl.innerHTML = `
      <div class="zoom-panel">
        <div class="zoom-top-row">
          <div class="preset-group">
            <span class="zoom-label-tag">🔍 縮放區間：</span>
            ${PRESETS.map(
              (p) =>
                `<button type="button" class="preset-btn ${p.days === defaultDays ? "active" : ""}" data-days="${p.days}">${p.label}</button>`
            ).join("")}
          </div>
          <div class="zoom-right-group">
            <div class="range-dates-readout"></div>
            <button type="button" class="btn-toggle-notes" title="展開或收合圖表下方量化文字解析">📖 展開解析</button>
          </div>
        </div>
        <div class="slider-row">
          <span class="zoom-label-tag">↔️ 顯示區間滑桿：</span>
          <div class="dual-slider">
            <div class="dual-slider-track"></div>
            <div class="dual-slider-fill"></div>
            <input type="range" class="zoom-start" min="0" max="${total - 1}" value="${startIdx}" step="1" aria-label="起始日期滑桿" />
            <input type="range" class="zoom-end" min="0" max="${total - 1}" value="${endIdx}" step="1" aria-label="結束日期滑桿" />
          </div>
        </div>
      </div>
    `;

    const readout = containerEl.querySelector(".range-dates-readout");
    const toggleNotesBtn = containerEl.querySelector(".btn-toggle-notes");
    const fillEl = containerEl.querySelector(".dual-slider-fill");
    const sInput = containerEl.querySelector(".zoom-start");
    const eInput = containerEl.querySelector(".zoom-end");
    const btns = containerEl.querySelectorAll(".preset-btn");

    if (toggleNotesBtn) {
      toggleNotesBtn.addEventListener("click", () => {
        const panelEl = containerEl.closest(".subtab-panel");
        if (!panelEl) return;
        const drawers = panelEl.querySelectorAll("details.analysis-drawer");
        if (!drawers.length) return;
        const nextOpen = !drawers[0].open;
        drawers.forEach((d) => {
          d.open = nextOpen;
        });
        toggleNotesBtn.textContent = nextOpen ? "📕 收合解析" : "📖 展開解析";
      });
    }

    function updateVisuals(triggerCallback = true) {
      const denom = Math.max(1, total - 1);
      const pctL = (startIdx / denom) * 100;
      const pctR = (endIdx / denom) * 100;
      fillEl.style.left = `${pctL}%`;
      fillEl.style.width = `${Math.max(0, pctR - pctL)}%`;
      sInput.value = String(startIdx);
      eInput.value = String(endIdx);

      sInput.style.zIndex = startIdx > total - 15 ? "5" : "3";
      eInput.style.zIndex = "4";

      readout.textContent = `${labels[startIdx] || ""} → ${labels[endIdx] || ""}（${endIdx - startIdx + 1} 交易日）`;
      tabRanges[tabName] = { startIdx, endIdx, startDate: labels[startIdx], endDate: labels[endIdx] };
      if (currentTab === tabName) updatePdfHref();
      if (triggerCallback) onRangeChange(startIdx, endIdx);
    }

    sInput.addEventListener("input", () => {
      let v = parseInt(sInput.value, 10);
      if (v > endIdx - minSpan) v = Math.max(0, endIdx - minSpan);
      startIdx = v;
      btns.forEach((b) => b.classList.remove("active"));
      updateVisuals(true);
    });

    eInput.addEventListener("input", () => {
      let v = parseInt(eInput.value, 10);
      if (v < startIdx + minSpan) v = Math.min(total - 1, startIdx + minSpan);
      endIdx = v;
      btns.forEach((b) => b.classList.remove("active"));
      updateVisuals(true);
    });

    btns.forEach((btn) => {
      btn.addEventListener("click", () => {
        btns.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        const d = parseInt(btn.dataset.days, 10);
        endIdx = total - 1;
        startIdx = d > 0 ? Math.max(0, total - d) : 0;
        updateVisuals(true);
      });
    });

    updateVisuals(true);

    return {
      getRange: () => [startIdx, endIdx],
      setRange: (s, e) => {
        startIdx = Math.max(0, Math.min(total - 1, s));
        endIdx = Math.max(startIdx, Math.min(total - 1, e));
        btns.forEach((b) => b.classList.remove("active"));
        updateVisuals(true);
      },
    };
  }

  function applyZoomToCharts(charts, startIdx, endIdx) {
    charts.forEach((ch) => {
      if (!ch || !ch.options || !ch.options.scales || !ch.options.scales.x) return;
      ch.options.scales.x.min = startIdx;
      ch.options.scales.x.max = endIdx;
      if (ch.$autoFitValues) {
        let lo = Infinity;
        let hi = -Infinity;
        for (let i = startIdx; i <= endIdx; i++) {
          const v = ch.$autoFitValues[i];
          if (v != null && !Number.isNaN(Number(v))) {
            if (v < lo) lo = v;
            if (v > hi) hi = v;
          }
        }
        if (ch.$includeZero) {
          lo = Math.min(lo, ch.$baseValue ?? 0);
          hi = Math.max(hi, ch.$baseValue ?? 0);
        }
        if (Number.isFinite(lo) && Number.isFinite(hi)) {
          const pad = Math.max(1e-6, (hi - lo) * 0.08);
          ch.options.scales.y.min = Math.floor((lo - pad) * 100) / 100;
          ch.options.scales.y.max = Math.ceil((hi + pad) * 100) / 100;
        }
      }
      ch.update("none");
    });
  }

  // Supports BOTH Desktop Mouse Hover AND Mobile Finger Touch Inspection
  function bindSyncHover(charts, labels, readoutEl, itemsFn) {
    function handleClientX(ch, clientX) {
      const xScale = ch.scales.x;
      if (!xScale || !ch.chartArea) return;
      const rect = ch.canvas.getBoundingClientRect();
      const xPx = clientX - rect.left;
      if (xPx < ch.chartArea.left || xPx > ch.chartArea.right) return;

      let idx = Math.round(xScale.getValueForPixel(xPx));
      const minI = Math.max(0, Math.floor(xScale.min ?? 0));
      const maxI = Math.min(labels.length - 1, Math.ceil(xScale.max ?? (labels.length - 1)));
      idx = Math.max(minI, Math.min(maxI, idx));

      charts.forEach((c) => {
        c.$hoverIdx = idx;
        c.draw();
      });

      const items = itemsFn(idx);
      readoutEl.innerHTML =
        `<strong>📅 ${labels[idx] || ""}</strong>` +
        items
          .map((it) =>
            it.rawHtml
              ? it.rawHtml
              : `<span>${it.name}: <strong style="color:${it.color || "#f8fafc"}">${it.value ?? "-"}</strong></span>`
          )
          .join("");
    }

    charts.forEach((ch) => {
      const canvas = ch.canvas;
      canvas.addEventListener("mousemove", (evt) => handleClientX(ch, evt.clientX));
      canvas.addEventListener(
        "touchstart",
        (evt) => {
          if (evt.touches && evt.touches.length === 1) handleClientX(ch, evt.touches[0].clientX);
        },
        { passive: true }
      );
      canvas.addEventListener(
        "touchmove",
        (evt) => {
          if (evt.touches && evt.touches.length === 1) handleClientX(ch, evt.touches[0].clientX);
        },
        { passive: true }
      );
      canvas.addEventListener("mouseleave", () => {
        charts.forEach((c) => {
          c.$hoverIdx = null;
          c.draw();
        });
      });
    });
  }

  function createIndexLineChart(canvas, labels, values, offsetBar = false, extraDatasets = [], showXLabels = true) {
    const pal = getThemePalette();
    const ch = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "加權指數",
            data: values,
            borderColor: pal.indexLine,
            borderWidth: 1.85,
            pointRadius: 0,
            tension: 0.08,
            spanGaps: true,
          },
          ...extraDatasets,
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: { padding: { top: 4, bottom: 2, right: 10 } },
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: {
          x: baseXAxis(offsetBar, showXLabels),
          y: fixedLeftAxis(),
        },
      },
    });
    ch.$chartKind = "indexLine";
    ch.$autoFitValues = values;
    ch.$includeZero = false;
    return registerChart(ch);
  }

  function createSignAreaChart(canvas, labels, values, offsetBar = false, fixedRange = null, showXLabels = true) {
    const ch = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            data: values,
            fill: { target: "origin" },
            borderColor: (ctx) => makeZeroSignGradient(ctx.chart, 0.96, 0.96),
            backgroundColor: (ctx) => makeZeroSignGradient(ctx.chart, 0.34, 0.34),
            borderWidth: 1.6,
            pointRadius: 0,
            tension: 0.05,
            spanGaps: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: { padding: { top: 4, bottom: 2, right: 10 } },
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: {
          x: baseXAxis(offsetBar, showXLabels),
          y: fixedLeftAxis(fixedRange ? { min: fixedRange[0], max: fixedRange[1] } : {}),
        },
      },
    });
    ch.$chartKind = "signArea";
    if (!fixedRange) {
      ch.$autoFitValues = values;
      ch.$includeZero = true;
      ch.$baseValue = 0;
    }
    return registerChart(ch);
  }

  function createThresholdBarChart(canvas, labels, values, threshold = 0, invert = false, showXLabels = true) {
    const pal = getThemePalette();
    const bg = values.map((v) => {
      if (v == null || Number.isNaN(Number(v))) return "rgba(148,163,184,0.22)";
      const isBull = invert ? !(v > threshold) : v > threshold;
      return isBull ? pal.bullBar : pal.bearBar;
    });

    const ch = new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            data: values,
            base: threshold,
            backgroundColor: bg,
            barPercentage: 0.9,
            categoryPercentage: 0.92,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: { padding: { top: 4, bottom: 2, right: 10 } },
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: {
          x: baseXAxis(true, showXLabels),
          y: fixedLeftAxis(),
        },
      },
    });
    ch.$chartKind = "thresholdBar";
    ch.$rawBarCfg = { values, threshold, invert };
    ch.$autoFitValues = values;
    ch.$includeZero = true;
    ch.$baseValue = threshold;
    return registerChart(ch);
  }

  function createAlignedRibbonChart(canvas, labels, rowsData, showXLabels = true) {
    const pal = getThemePalette();
    const rowNames = rowsData.map((r) => r.name);
    const ch = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            data: labels.map(() => null),
            pointRadius: 0,
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: { padding: { top: 4, bottom: 2, right: 10 } },
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: {
          x: baseXAxis(false, showXLabels),
          y: fixedLeftAxis({
            min: -0.5,
            max: rowNames.length - 0.5,
            reverse: true,
            grid: { display: false },
            afterBuildTicks(scale) {
              scale.ticks = rowNames.map((_, i) => ({ value: i }));
            },
            ticks: {
              color: pal.tickColor,
              stepSize: 1,
              autoSkip: false,
              padding: 3,
              font: { size: isMobileViewport() ? 9.5 : 11, weight: "700" },
              callback: (v) => (Number.isInteger(v) && rowNames[v] ? rowNames[v] : ""),
            },
          }),
        },
      },
    });
    ch.$chartKind = "ribbon";
    ch.$ribbonRows = rowsData;
    return registerChart(ch);
  }

  function jumpToTab(tabName) {
    const btn = document.querySelector(`.subtab-btn[data-tab="${tabName}"]`);
    if (btn) btn.click();
  }

  // 1. Load DB Status & Live Executive Strip (on Lobster Homepage & Intro Tab)
  async function loadDbStatus() {
    const box = document.getElementById("db-status-box");
    const submeta = document.getElementById("header-submeta");
    const heroStrips = [
      document.getElementById("lobster-hero-strip"),
      document.getElementById("intro-hero-strip"),
    ].filter(Boolean);
    try {
      const [res, ov] = await Promise.all([
        fetch("/api/admin/lobturtle/status").then((r) => r.json()),
        fetchStrategyOverview(false).catch(() => null),
      ]);
      if (res && res.summary) {
        if (submeta && res.latestDate) {
          const firstDates = res.summary.map((s) => s.firstDate).filter(Boolean).sort();
          const earliestDate = firstDates[0] || "2020/11/05";
          submeta.textContent = `資料範圍: ${earliestDate} ~ ${res.latestDate}`;
        }
        if (box) {
          box.innerHTML = res.summary
            .map(
              (s) => `
            <div class="db-badge">
              <strong class="db-title"><span>🗄️ ${s.name}</span><span class="db-dot" title="運作正常"></span></strong>
              <div>歷史區間：<code>${s.firstDate || "-"} ~ ${s.lastDate || "-"}</code></div>
              <div>保留筆數：<strong>${(s.rowCount || 0).toLocaleString()}</strong> 筆</div>
            </div>`
            )
            .join("");
        }
      }

      if (heroStrips.length && ov && ov.ok && ov.telemetry) {
        const t = ov.telemetry;
        const stripHtml = `
          <div class="hero-stat-card" data-jump="lobster" title="檢視龍蝦指標圖表">
            <div class="hero-stat-top"><span>📈 台灣加權指數</span><span>${ov.latestDate}</span></div>
            <div class="hero-stat-val">${fmtNum(t.lastPrice, 2)}</div>
            <div class="hero-stat-sub">波段回撤 <strong class="${t.drawdownPct >= -10 ? "val-pos" : "val-neg"}">${t.drawdownPct}%</strong> · 波動率 ${t.vol20dPct}%</div>
          </div>
          <div class="hero-stat-card" data-jump="lobster" title="檢視龍蝦指標">
            <div class="hero-stat-top"><span>🦞 龍蝦短中期動能</span><span>首頁核心指標</span></div>
            <div class="hero-stat-val ${t.lobster > 0 ? "val-pos" : "val-neg"}">${t.lobster > 0 ? "+2 紅燈" : "-2 綠燈"}</div>
            <div class="hero-stat-sub">五日動能積分 <strong>${t.lobsterSum > 0 ? "+" + t.lobsterSum : t.lobsterSum}</strong> / ±10</div>
          </div>
          <div class="hero-stat-card" data-jump="turtle" title="點擊切換至海龜指標">
            <div class="hero-stat-top"><span>🐢 海龜中長線廣度</span><span>點擊進入 ➔</span></div>
            <div class="hero-stat-val ${t.turtleTotalBull >= 5 ? "val-pos" : "val-neg"}">${t.turtleTotalBull} / 10 軌偏多</div>
            <div class="hero-stat-sub">V1:${t.turtleV1Bull}/4 · V2:${t.turtleV2Bull}/3 · V3:${t.turtleV3Bull}/3</div>
          </div>
          <div class="hero-stat-card" data-jump="foreign" title="點擊切換至外資籌碼">
            <div class="hero-stat-top"><span>🏦 外資期現貨動向</span><span>點擊進入 ➔</span></div>
            <div class="hero-stat-val ${(t.spot10d ?? 0) >= 0 ? "val-pos" : "val-neg"}">${fmtNum(t.spot10d, 0)} 億</div>
            <div class="hero-stat-sub">10日現貨累計 · 期貨未平倉 ${fmtNum((t.futOiLatest ?? 0) / 1000, 1)}k 口</div>
          </div>
          <div class="hero-stat-card" data-jump="retail" title="點擊切換至散戶未平倉">
            <div class="hero-stat-top"><span>👥 散戶反向籌碼分數</span><span>點擊進入 ➔</span></div>
            <div class="hero-stat-val ${(t.retailScore ?? 0) > 0 ? "val-pos" : "val-neg"}">${(t.retailScore ?? 0) > 0 ? "+" + t.retailScore : (t.retailScore ?? "-")} 分</div>
            <div class="hero-stat-sub">小台 ${t.mxfLatest ?? "-"}% · 微台 ${t.tmfLatest ?? "-"}%</div>
          </div>
          <div class="hero-stat-card" data-jump="strategy" title="點擊切換至國際總經與實戰策略">
            <div class="hero-stat-top"><span>🌐 目標波動建議倉位</span><span>點擊進入 ➔</span></div>
            <div class="hero-stat-val" style="color:var(--heading-accent)">${t.recommendedEquityPct}% 持股</div>
            <div class="hero-stat-sub">保留現金 ${t.recommendedCashPct}% · 即時跨市場研判</div>
          </div>
        `;
        heroStrips.forEach((strip) => {
          strip.innerHTML = stripHtml;
          strip.querySelectorAll(".hero-stat-card").forEach((card) => {
            card.addEventListener("click", () => {
              const target = card.dataset.jump;
              if (currentTab === target && target === "lobster") {
                const el = document.getElementById("lob-controls");
                if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
              } else {
                jumpToTab(target);
              }
            });
          });
        });
      }
    } catch (e) {
      if (box) box.innerHTML = `<div class="val-pos">無法讀取資料庫狀態：${e.message}</div>`;
    }
  }

  function renderMiniPillsHTML(pills) {
    return pills
      .map((p) => `<span class="mini-pill ${p.cls || ""}">${p.text}</span>`)
      .join("");
  }

  function bindPanelDrawersSync(panelId) {
    const panelEl = document.getElementById(panelId);
    if (!panelEl) return;
    const drawers = panelEl.querySelectorAll("details.analysis-drawer");
    drawers.forEach((d) => {
      if (d.$syncBound) return;
      d.$syncBound = true;
      d.addEventListener("toggle", () => {
        const btn = panelEl.querySelector(".btn-toggle-notes");
        if (!btn) return;
        const anyOpen = Array.from(panelEl.querySelectorAll("details.analysis-drawer")).some((x) => x.open);
        btn.textContent = anyOpen ? "📕 收合解析" : "📖 展開解析";
      });
    });
  }

  // Helper to render 100% live-driven tactical/strategic synthesis block on Lobster & Turtle tabs
  function renderEmbeddedStrategyBlock(overview, mode) {
    if (!overview || !overview.ok) return "";
    const t = overview.telemetry;
    const reg = overview.regime;
    const gm = overview.globalMarkets || {};
    const sox = gm.SOX;
    const tsm = gm.TSM_ADR;
    const vix = gm.VIX;
    const us10y = gm.US10Y;
    const usdtwd = gm.USDTWD;
    const themes = ((overview.newsIntel || {}).activeThemes || []).map((x) => `「${x.label}」`).join("、") || "跨市場資金再平衡";
    const macro0 = overview.macroSynthesis && overview.macroSynthesis[0] ? overview.macroSynthesis[0].analysis : "";
    const macro1 = overview.macroSynthesis && overview.macroSynthesis[1] ? overview.macroSynthesis[1].analysis : "";
    const play0 = overview.actionablePlaybook && overview.actionablePlaybook[0] ? overview.actionablePlaybook[0].tactics : [];
    const play1 = overview.actionablePlaybook && overview.actionablePlaybook[1] ? overview.actionablePlaybook[1].tactics : [];
    const play2 = overview.actionablePlaybook && overview.actionablePlaybook[2] ? overview.actionablePlaybook[2].tactics : [];

    const gmLine = [
      sox ? `費半 ${fmtNum(sox.last, 1)} (${sox.chg1dPct > 0 ? "+" : ""}${sox.chg1dPct}%)` : null,
      tsm ? `台積電ADR $${fmtNum(tsm.last, 2)} (${tsm.chg1dPct > 0 ? "+" : ""}${tsm.chg1dPct}%)` : null,
      vix ? `VIX ${fmtNum(vix.last, 2)}` : null,
      us10y ? `美債10Y ${fmtNum(us10y.last, 2)}%` : null,
      usdtwd ? `USD/TWD ${fmtNum(usdtwd.last, 2)}` : null,
    ]
      .filter(Boolean)
      .join(" ｜ ");

    if (mode === "lobster") {
      return `
        <div class="regime-banner ${reg.tone}">
          <h3>🦞 龍蝦指標 × 即時國際行情與新聞情勢短中期戰術剖析（台股基準：${overview.latestDate} ｜ 國際情勢同步：${overview.intelSyncedAt || "即時"}）</h3>
          <p><strong>當前動態定調【${reg.title}】</strong>：${reg.summary}</p>
          ${gmLine ? `<p class="regime-pulse-line"><strong>🌐 跨市場即時脈搏</strong>：<code>${gmLine}</code> ｜ <strong>新聞雷達焦點</strong>：${themes}</p>` : ""}
        </div>
        <details class="analysis-drawer">
          <summary class="analysis-drawer-summary">
            <span>🧭 點擊展開／收合「跨市場總經傳導 × 龍蝦短中期進出場戰術 SOP 詳解」</span>
            <span class="drawer-chevron">▼</span>
          </summary>
          <div class="analysis-drawer-body">
            <div class="strategy-grid-2">
              <div class="strategy-card">
                <span class="cite-tag">即時國際情勢 × 外資匯率傳導</span>
                <h4>一、全球科技股連動、利率匯率與國內外即時訊息研判</h4>
                <p>${macro0}</p>
                <p style="margin-top:8px;">${macro1}</p>
              </div>
              <div class="strategy-card">
                <span class="cite-tag">動態計算倉位：建議持股 ${t.recommendedEquityPct}% / 現金 ${t.recommendedCashPct}%</span>
                <h4>二、龍蝦指標 × 散戶微結構即時進出場戰術 SOP</h4>
                <ul>
                  ${[...play0, ...play1].map((item) => `<li>${item}</li>`).join("")}
                </ul>
              </div>
            </div>
          </div>
        </details>
      `;
    }
    return `
      <div class="regime-banner ${reg.tone}">
        <h3>🐢 海龜指標 × 全球宏觀景氣與跨市場中長期資產配置策略（台股基準：${overview.latestDate} ｜ 國際情勢同步：${overview.intelSyncedAt || "即時"}）</h3>
        <p><strong>中長期趨勢廣度診斷【海龜 10 軌偏多數：${t.turtleTotalBull} / 10 ｜ V1=${t.turtleV1Bull}/4, V2=${t.turtleV2Bull}/3, V3=${t.turtleV3Bull}/3】</strong>：${reg.summary}</p>
        ${gmLine ? `<p class="regime-pulse-line"><strong>🌐 跨市場即時脈搏</strong>：<code>${gmLine}</code> ｜ <strong>新聞雷達焦點</strong>：${themes}</p>` : ""}
      </div>
      <details class="analysis-drawer">
        <summary class="analysis-drawer-summary">
          <span>🧭 點擊展開／收合「海龜危機阿爾法宏觀結構 × 多週期動態加減碼 SOP 詳解」</span>
          <span class="drawer-chevron">▼</span>
        </summary>
        <div class="analysis-drawer-body">
          <div class="strategy-grid-2">
            <div class="strategy-card">
              <span class="cite-tag">Hurst, Ooi &amp; Pedersen (JPM) 趨勢保護實證</span>
              <h4>一、海龜通道「危機阿爾法」與當前跨市場宏觀結構</h4>
              <p>${macro1}</p>
              <ul>
                <li><strong>最近一次 V1 四軌集體轉折點</strong>：<code>${t.v1LastFlipDate || "-"}</code>（加權指數 <strong>${fmtNum(t.v1LastFlipPrice, 2)}</strong> 點）；目前季線位於 <code>${fmtNum(t.ma60, 0)}</code> 點、半年線 <code>${fmtNum(t.ma120, 0)}</code> 點、年線 <code>${fmtNum(t.ma240, 0)}</code> 點。</li>
              </ul>
            </div>
            <div class="strategy-card">
              <span class="cite-tag">動態計算倉位：建議持股 ${t.recommendedEquityPct}% / 現金 ${t.recommendedCashPct}%</span>
              <h4>二、海龜多週期通道動態加減碼與核心資產配置</h4>
              <ul>
                ${[...play2, ...(overview.actionablePlaybook?.[3]?.tactics || [])].map((item) => `<li>${item}</li>`).join("")}
              </ul>
            </div>
          </div>
        </div>
      </details>
    `;
  }

  // 2. Lobster Tab
  let lobLoaded = false;
  let lobCharts = [];
  async function initLobsterTab(forceReload = false) {
    if (lobLoaded && !forceReload) return;
    lobLoaded = true;

    const [data, overview] = await Promise.all([
      fetch("/api/charts/lobster/data").then((r) => r.json()),
      fetchStrategyOverview(forceReload),
    ]);
    document.getElementById("lob-meta").textContent =
      `資料期間：${data.labels[0] || ""} ~ ${data.dataDate}（共 ${data.labels.length.toLocaleString()} 個交易日，逾 5 年完整回溯）`;

    const ctrlEl = document.getElementById("lob-controls");
    const stackEl = document.getElementById("lob-charts");
    const readoutEl = document.getElementById("lob-readout");
    const stratEl = document.getElementById("lob-strategy-box");
    destroyChartList(lobCharts);
    lobCharts = [];
    stackEl.innerHTML = "";

    const dockGroup = document.createElement("div");
    dockGroup.className = "docked-chart-group";
    dockGroup.innerHTML = `
      <div class="docked-pane">
        <div class="chart-box-header">
          <span>圖一：台灣加權指數 (TWSE)</span>
          <span class="pane-pills" id="lob-pills-1"></span>
        </div>
        <div class="chart-canvas-wrap pane-h-idx"><canvas id="lob-cv-1"></canvas></div>
      </div>
      <div class="docked-pane">
        <div class="chart-box-header">
          <span>圖二：LOBSTER 多空狀態色帶（紅 +2 偏多 · 綠 -2 偏空）</span>
          <span class="pane-pills" id="lob-pills-2"></span>
        </div>
        <div class="chart-canvas-wrap pane-h-lob-rib"><canvas id="lob-cv-2"></canvas></div>
      </div>
      <div class="docked-pane">
        <div class="chart-box-header">
          <span>圖三：LOBSTER_SUM 五日滾動動能積分（-10 ~ +10）</span>
          <span class="pane-pills" id="lob-pills-3"></span>
        </div>
        <div class="chart-canvas-wrap pane-h-lob-sum"><canvas id="lob-cv-3"></canvas></div>
      </div>
    `;
    stackEl.appendChild(dockGroup);

    const drawerEl = document.createElement("details");
    drawerEl.className = "analysis-drawer";
    drawerEl.innerHTML = `
      <summary class="analysis-drawer-summary">
        <span>📖 點擊展開／收合「龍蝦指標三層動能架構與波動率量化解析」（共 3 則）</span>
        <span class="drawer-chevron">▼</span>
      </summary>
      <div class="analysis-drawer-body">
        <div class="chart-analysis-note" id="lob-note-1"></div>
        <div class="chart-analysis-note" id="lob-note-2"></div>
        <div class="chart-analysis-note" id="lob-note-3"></div>
      </div>
    `;
    stackEl.appendChild(drawerEl);

    stratEl.innerHTML = renderEmbeddedStrategyBlock(overview, "lobster");
    bindPanelDrawersSync("panel-lobster");

    lobCharts = [
      createIndexLineChart(dockGroup.querySelector("#lob-cv-1"), data.labels, data.point, false, [], false),
      createAlignedRibbonChart(dockGroup.querySelector("#lob-cv-2"), data.labels, [{ name: "LOBSTER", values: data.lobster }], false),
      createSignAreaChart(dockGroup.querySelector("#lob-cv-3"), data.labels, data.lobster_sum, false, [-11, 11], true),
    ];

    function updateLobsterNotes(s, e) {
      const idxStat = calcWindowIndexStats(data.point, s, e);
      const lobStat = calcSignalWindowStats(data.lobster, s, e, (v) => v > 0);
      const curLob = data.lobster[e];
      const curSum = data.lobster_sum[e];
      let sumPos10 = 0;
      let sumNeg10 = 0;
      for (let i = s; i <= e; i++) {
        if (data.lobster_sum[i] === 10) sumPos10++;
        if (data.lobster_sum[i] === -10) sumNeg10++;
      }

      document.getElementById("lob-pills-1").innerHTML = renderMiniPillsHTML([
        { text: `漲跌 ${idxStat.retPct > 0 ? "+" : ""}${idxStat.retPct}%`, cls: idxStat.retPct >= 0 ? "bull" : "bear" },
        { text: `MDD ${idxStat.mddPct}%`, cls: idxStat.mddPct < -12 ? "bear" : "" },
        { text: `波動率 ${idxStat.volPct}%` },
      ]);
      document.getElementById("lob-pills-2").innerHTML = renderMiniPillsHTML([
        { text: curLob > 0 ? "期末 +2 紅燈" : "期末 -2 綠燈", cls: curLob > 0 ? "bull" : "bear" },
        { text: `連維持 ${lobStat.streak} 日` },
        { text: `偏多 ${lobStat.bullPct}%` },
      ]);
      document.getElementById("lob-pills-3").innerHTML = renderMiniPillsHTML([
        { text: `SUM = ${curSum > 0 ? "+" + curSum : curSum}`, cls: curSum > 0 ? "bull" : "bear" },
        { text: `+10 鈍化 ${sumPos10}日`, cls: "bull" },
        { text: `-10 恐慌 ${sumNeg10}日`, cls: "bear" },
      ]);

      document.getElementById("lob-note-1").innerHTML = renderAnalysisNoteHTML(
        [
          { text: `區間收盤：${fmtNum(idxStat.last, 2)} 點` },
          { text: `區間漲跌幅：${idxStat.retPct > 0 ? "+" : ""}${idxStat.retPct}%`, cls: idxStat.retPct >= 0 ? "bull" : "bear" },
          { text: `區間最大回撤 (MDD)：${idxStat.mddPct}%`, cls: idxStat.mddPct < -12 ? "bear" : "" },
          { text: `年化實現波動率：${idxStat.volPct}%` },
        ],
        "價格慣性與波動率聚類原理 (Volatility Clustering)",
        "加權指數作為龍蝦指標之基礎價格序列，反映台股權值半導體與內外資流動性合力。金融計量實證顯示股市報酬具備顯著「波動率聚類」與「左尾肥尾（Fat-Tail）」特徵：緩漲階段波動率低而趨勢穩定；急跌階段波動率驟升並伴隨融資追繳與外資期現貨同步拋售。",
        "圖表實戰判讀要領",
        `觀察目前區間高低點（<code>${fmtNum(idxStat.lo, 0)} ~ ${fmtNum(idxStat.hi, 0)}</code>）：當年化波動率高於 28% 時（目前區間 <code>${idxStat.volPct}%</code>），單日漲跌動輒逾千點，切忌單憑價格絕對跌幅猜底，務必對照下方 <code>LOBSTER</code> 狀態帶是否完成止跌翻紅確認。`
      );

      document.getElementById("lob-note-2").innerHTML = renderAnalysisNoteHTML(
        [
          { text: `區間期末訊號：${curLob > 0 ? "+2 (紅燈偏多)" : "-2 (綠燈偏空)"}`, cls: curLob > 0 ? "bull" : "bear" },
          { text: `連續維持：${lobStat.streak} 個交易日` },
          { text: `區間偏多佔比：${lobStat.bullPct}%` },
          { text: `翻轉 ${lobStat.flips} 次（平均每段維持 ${lobStat.avgHold} 日）` },
        ],
        "非對稱施密特遲滯濾波機制 (Asymmetric Hysteresis State Machine)",
        "為解決傳統短均線在橫盤震盪時頻繁「雙巴（Whipsaw）」之缺陷，<code>LOBSTER</code> 對雙日均線設定非對稱遲滯門檻：空翻多要求收盤超越雙日均線 <code>+0.30%</code>（確認買盤具突破動能），多翻空要求跌破 <code>-0.25%</code> 且排除十日線陡峭主升段保護，使單一狀態平均可維持約一週（5~7 個交易日）。",
        "短中期轉折操作法則",
        "<strong>紅翻綠首日（+2 → -2）</strong>代表短線慣性破壞，短波段多單應立即減碼或鎖利，絕不在綠燈延續期間盲目向下攤平；<strong>綠翻紅首日（-2 → +2）</strong>若同步伴隨小台／微台散戶多空比降溫，則為高勝率之右側短波段起漲訊號。"
      );

      document.getElementById("lob-note-3").innerHTML = renderAnalysisNoteHTML(
        [
          { text: `區間期末五日動能：LOBSTER_SUM = ${curSum > 0 ? "+" + curSum : curSum}`, cls: curSum > 0 ? "bull" : "bear" },
          { text: `+10 極強鈍化天數：${sumPos10} 日`, cls: "bull" },
          { text: `-10 極弱恐慌天數：${sumNeg10} 日`, cls: "bear" },
        ],
        "五日滾動動能積分與能量階層 (-10, -6, -2, +2, +6, +10)",
        "<code>LOBSTER_SUM</code> 將近 5 個交易日之 <code>LOBSTER</code> 加總，將二元方向訊號轉化為六階動能推力曲線：<code>+10</code> 代表連五日紅燈鎖定多頭主升推力；<code>-10</code> 代表連五日綠燈處於極端空方動能宣洩；<code>-2 / +2</code> 零軸穿越區則是多空動能正式易位之樞紐。",
        "高檔鈍化、低檔竭盡與背離判讀",
        "（1）<strong>動能起漲確認</strong>：由 <code>-10 / -6</code> 翻越零軸升至 <code>+2 / +6</code>，代表五日內至少 3~4 日站穩多方，波段續航力最強；（2）<strong>高檔動能背離</strong>：指數創高但 <code>LOBSTER_SUM</code> 無法回到 <code>+10</code> 而落於 <code>+2 / -2</code> 震盪，預警上攻力道衰竭；（3）<strong>低檔 <code>-10</code> 鈍化</strong>：主跌段中 <code>-10</code> 會連續鈍化，須待指數不再破底且分數回升至 <code>-6 → -2</code> 方可視為止跌。"
      );
    }

    bindSyncHover(lobCharts, data.labels, readoutEl, (i) => [
      { name: "加權指數", value: data.point[i] != null ? data.point[i].toLocaleString() : "-" },
      {
        name: "漲跌",
        value: data.change && data.change[i] != null ? (data.change[i] > 0 ? `+${data.change[i]}` : data.change[i]) : "-",
        color: (data.change?.[i] ?? 0) >= 0 ? "#f87171" : "#34d399",
      },
      { name: "LOBSTER", value: data.lobster[i], color: data.lobster[i] > 0 ? "#f87171" : "#34d399" },
      { name: "LOBSTER_SUM", value: data.lobster_sum[i], color: data.lobster_sum[i] > 0 ? "#f87171" : "#34d399" },
    ]);

    buildZoomAndSliderControls(ctrlEl, "lobster", data.labels, 245, (s, e) => {
      applyZoomToCharts(lobCharts, s, e);
      updateLobsterNotes(s, e);
    });
  }

  // 3. Foreign Chip Tab
  let forLoaded = false;
  let forCharts = [];
  async function initForeignTab(forceReload = false) {
    if (forLoaded && !forceReload) return;
    forLoaded = true;

    const data = await fetch("/api/charts/lobster/foreign").then((r) => r.json());
    document.getElementById("for-meta").textContent =
      `資料期間：${data.labels[0] || ""} ~ ${data.dataDate}（共 ${data.labels.length.toLocaleString()} 個交易日，逾 5 年完整回溯）`;

    const ctrlEl = document.getElementById("for-controls");
    const stackEl = document.getElementById("for-charts");
    const readoutEl = document.getElementById("for-readout");
    let rollDays = 10;
    let currentRange = [Math.max(0, data.labels.length - 245), data.labels.length - 1];
    let updateForeignNotesFn = () => {};

    function buildForeignCharts() {
      const prevOpen = Boolean(stackEl.querySelector("details.analysis-drawer")?.open);
      destroyChartList(forCharts);
      forCharts = [];
      stackEl.innerHTML = "";

      const spotAll = data.series[0].values;
      const rollAll = rollingSum(spotAll, rollDays);
      const ftrAll = data.series[1].values;
      const foiAll = data.series[2].values;

      const dockGroup = document.createElement("div");
      dockGroup.className = "docked-chart-group";
      dockGroup.innerHTML = `
        <div class="docked-pane">
          <div class="chart-box-header">
            <span>圖一：加權指數 (TWSE)</span>
            <span class="pane-pills" id="for-pills-0"></span>
          </div>
          <div class="chart-canvas-wrap pane-h-idx"><canvas id="for-cv-0"></canvas></div>
        </div>
        <div class="docked-pane">
          <div class="chart-box-header">
            <span>圖二：外資現貨累積買賣超(億)</span>
            <span class="pane-pills">
              <span id="for-pills-1" class="pane-pills"></span>
              <span>累積 N：<input id="inp-roll-n" type="number" min="1" max="250" value="${rollDays}" style="width:56px"> 日</span>
            </span>
          </div>
          <div class="chart-canvas-wrap pane-h-sub"><canvas id="for-cv-1"></canvas></div>
        </div>
        <div class="docked-pane">
          <div class="chart-box-header">
            <span>圖三：外資現貨單日買賣超(億)</span>
            <span class="pane-pills" id="for-pills-2"></span>
          </div>
          <div class="chart-canvas-wrap pane-h-sub"><canvas id="for-cv-2"></canvas></div>
        </div>
        <div class="docked-pane">
          <div class="chart-box-header">
            <span>圖四：外資台指期單日交易淨口數(口)</span>
            <span class="pane-pills" id="for-pills-3"></span>
          </div>
          <div class="chart-canvas-wrap pane-h-sub"><canvas id="for-cv-3"></canvas></div>
        </div>
        <div class="docked-pane">
          <div class="chart-box-header">
            <span>圖五：外資台指期未平倉淨口數(口)</span>
            <span class="pane-pills" id="for-pills-4"></span>
          </div>
          <div class="chart-canvas-wrap pane-h-sub-bottom"><canvas id="for-cv-4"></canvas></div>
        </div>
      `;
      stackEl.appendChild(dockGroup);

      const drawerEl = document.createElement("details");
      drawerEl.className = "analysis-drawer";
      if (prevOpen) drawerEl.open = true;
      drawerEl.innerHTML = `
        <summary class="analysis-drawer-summary">
          <span>📖 點擊展開／收合「外資期現貨五維度籌碼微結構解析」（共 5 則）</span>
          <span class="drawer-chevron">▼</span>
        </summary>
        <div class="analysis-drawer-body">
          <div class="chart-analysis-note" id="for-note-0"></div>
          <div class="chart-analysis-note" id="for-note-1"></div>
          <div class="chart-analysis-note" id="for-note-2"></div>
          <div class="chart-analysis-note" id="for-note-3"></div>
          <div class="chart-analysis-note" id="for-note-4"></div>
        </div>
      `;
      stackEl.appendChild(drawerEl);
      bindPanelDrawersSync("panel-foreign");

      forCharts.push(createIndexLineChart(dockGroup.querySelector("#for-cv-0"), data.labels, data.point, true, [], false));
      forCharts.push(createSignAreaChart(dockGroup.querySelector("#for-cv-1"), data.labels, rollAll, true, null, false));
      forCharts.push(createThresholdBarChart(dockGroup.querySelector("#for-cv-2"), data.labels, spotAll, 0, false, false));
      forCharts.push(createThresholdBarChart(dockGroup.querySelector("#for-cv-3"), data.labels, ftrAll, 0, false, false));
      forCharts.push(createSignAreaChart(dockGroup.querySelector("#for-cv-4"), data.labels, foiAll, true, null, true));

      updateForeignNotesFn = (s, e) => {
        const idxStat = calcWindowIndexStats(data.point, s, e);
        let spotSumWin = 0;
        for (let i = s; i <= e; i++) if (spotAll[i] != null) spotSumWin += Number(spotAll[i]);

        document.getElementById("for-pills-0").innerHTML = renderMiniPillsHTML([
          { text: `報酬 ${idxStat.retPct > 0 ? "+" : ""}${idxStat.retPct}%`, cls: idxStat.retPct >= 0 ? "bull" : "bear" },
          { text: `區間現貨 ${fmtNum(spotSumWin, 0)}億`, cls: spotSumWin >= 0 ? "bull" : "bear" },
        ]);
        document.getElementById("for-pills-1").innerHTML = renderMiniPillsHTML([
          { text: `期末 ${fmtNum(rollAll[e], 1)}億`, cls: (rollAll[e] ?? 0) >= 0 ? "bull" : "bear" },
        ]);
        document.getElementById("for-pills-2").innerHTML = renderMiniPillsHTML([
          { text: `期末 ${fmtNum(spotAll[e], 1)}億`, cls: (spotAll[e] ?? 0) >= 0 ? "bull" : "bear" },
        ]);
        document.getElementById("for-pills-3").innerHTML = renderMiniPillsHTML([
          { text: `期末 ${fmtNum(ftrAll[e], 0)}口`, cls: (ftrAll[e] ?? 0) >= 0 ? "bull" : "bear" },
        ]);
        document.getElementById("for-pills-4").innerHTML = renderMiniPillsHTML([
          { text: `未平倉 ${fmtNum(foiAll[e], 0)}口`, cls: (foiAll[e] ?? 0) >= 0 ? "bull" : "bear" },
        ]);

        document.getElementById("for-note-0").innerHTML = renderAnalysisNoteHTML(
          [
            { text: `區間指數報酬：${idxStat.retPct > 0 ? "+" : ""}${idxStat.retPct}%`, cls: idxStat.retPct >= 0 ? "bull" : "bear" },
            { text: `區間外資現貨總累計：${fmtNum(spotSumWin, 1)} 億元`, cls: spotSumWin >= 0 ? "bull" : "bear" },
          ],
          "外資對台股定價權機制",
          "外資持有台股上市總市值近四成（尤其高度集中於半導體權值龍頭），其買賣決策直接受美債實質殖利率、美元指數（DXY）、費城半導體指數（SOX）及新台幣匯率驅動。",
          "跨圖聯動觀察重點",
          "當大盤拉回但外資現貨累積曲線未破前低、或期貨空單開始大幅回補時，往往領先揭示國際資金賣壓竭盡。"
        );
        document.getElementById("for-note-1").innerHTML = renderAnalysisNoteHTML(
          [{ text: `期末 ${rollDays} 日累積現貨：${fmtNum(rollAll[e], 2)} 億元`, cls: (rollAll[e] ?? 0) >= 0 ? "bull" : "bear" }],
          `${rollDays} 日滾動資金潮汐濾波`,
          `單日外資買賣超易受 MSCI 權重調整、ETF 被動換股或富時結算干擾；透過 <code>${rollDays} 日滾動加總</code> 可平滑單日雜訊，清晰呈現外資波段匯入／匯出之真實斜率。`,
          "波段轉折判讀",
          "當綠區面積由極端擴張轉為連續 3~5 日收斂（底背離），即便絕對值仍為負，常為跌深反彈之先行訊號；翻紅站上零軸則確認波段外資回流。"
        );
        document.getElementById("for-note-2").innerHTML = renderAnalysisNoteHTML(
          [{ text: `期末單日現貨買賣超：${fmtNum(spotAll[e], 2)} 億元`, cls: (spotAll[e] ?? 0) >= 0 ? "bull" : "bear" }],
          "機構現貨籃子執行強度",
          "單日現貨買賣超逾 ±300 億至 ±800 億元代表全球宏觀基金（Global Macro）或主權／長線共同基金啟動資產再平衡（Rebalancing）。",
          "極值訊號意義",
          "在急跌末段若出現歷史級單日巨額賣超但指數留下長下影線或隔日不再破底，代表內資政策護盤／長線買盤成功承接外資恐慌拋售。"
        );
        document.getElementById("for-note-3").innerHTML = renderAnalysisNoteHTML(
          [{ text: `期末台指期單日淨交易：${fmtNum(ftrAll[e], 0)} 口`, cls: (ftrAll[e] ?? 0) >= 0 ? "bull" : "bear" }],
          "期貨高流動性先行點火效應",
          "期貨交易成本低、槓桿高，外資面對盤後美股財報或總經數據衝擊時，會優先於台指期（TX）加減碼，往往領先現貨半日至一日反映態度轉變。",
          "期現貨背離戰法",
          "若現貨仍大賣逾數百億，但台指期單日交易轉為大額淨買進（紅柱逾 +3,000 ~ +5,000 口），顯示外資正於低檔優先回補空單鎖定獲利，短彈一觸即發。"
        );
        document.getElementById("for-note-4").innerHTML = renderAnalysisNoteHTML(
          [{ text: `期末台指期未平倉淨部位：${fmtNum(foiAll[e], 0)} 口`, cls: (foiAll[e] ?? 0) >= 0 ? "bull" : "bear" }],
          "結構性避險（Hedging）與方向性投機複合部位",
          "外資持有龐大台股現貨多頭，平時常態維持一定比例之台指期淨空單進行 Delta 避險及逆價差套利，因此不宜單以「淨空單為負」直接看空，而須觀察其『邊際增減變化率』與『歷史分位極值』。",
          "關鍵水位判讀",
          "當未平倉淨空單急速擴大並逼近歷史極端水位（如 -5 萬至 -9 萬口以上）時，反映外資對系統性風險高度戒備；一旦空單自極端峰值連續數日回補逾萬口，即為壓抑大盤之最大鍋蓋鬆動訊號。"
        );
      };

      dockGroup.querySelector("#inp-roll-n").addEventListener("change", (ev) => {
        rollDays = Math.max(1, Math.min(250, parseInt(ev.target.value, 10) || 10));
        buildForeignCharts();
      });

      bindSyncHover(forCharts, data.labels, readoutEl, (i) => [
        { name: "加權指數", value: data.point[i] != null ? data.point[i].toLocaleString() : "-" },
        { name: `${rollDays}日累積(億)`, value: rollAll[i], color: (rollAll[i] ?? 0) > 0 ? "#f87171" : "#34d399" },
        { name: "外資現貨(億)", value: spotAll[i], color: (spotAll[i] ?? 0) > 0 ? "#f87171" : "#34d399" },
        { name: "期貨買賣超(口)", value: ftrAll[i], color: (ftrAll[i] ?? 0) > 0 ? "#f87171" : "#34d399" },
        { name: "期貨未平倉(口)", value: foiAll[i], color: (foiAll[i] ?? 0) > 0 ? "#f87171" : "#34d399" },
      ]);

      applyZoomToCharts(forCharts, currentRange[0], currentRange[1]);
      updateForeignNotesFn(currentRange[0], currentRange[1]);
    }

    buildForeignCharts();
    buildZoomAndSliderControls(ctrlEl, "foreign", data.labels, 245, (s, e) => {
      currentRange = [s, e];
      applyZoomToCharts(forCharts, s, e);
      updateForeignNotesFn(s, e);
    });
  }

  // 4. Retail Open Interest Tab
  let retLoaded = false;
  let retCharts = [];
  async function initRetailTab(forceReload = false) {
    if (retLoaded && !forceReload) return;
    retLoaded = true;

    const data = await fetch("/api/charts/lobster/retail").then((r) => r.json());
    document.getElementById("ret-meta").textContent =
      `資料期間：${data.labels[0] || ""} ~ ${data.dataDate}（共 ${data.labels.length.toLocaleString()} 個交易日；微台期 TMF 自 2024/07/29 掛牌日起收錄）`;

    const ctrlEl = document.getElementById("ret-controls");
    const stackEl = document.getElementById("ret-charts");
    const readoutEl = document.getElementById("ret-readout");
    let thMxf = 15;
    let thTmf = 30;
    let thDiff = -5;
    let currentRange = [Math.max(0, data.labels.length - 245), data.labels.length - 1];
    let updateRetailNotesFn = () => {};

    function buildRetailCharts() {
      const prevOpen = Boolean(stackEl.querySelector("details.analysis-drawer")?.open);
      destroyChartList(retCharts);
      retCharts = [];
      stackEl.innerHTML = "";

      const mxfAll = data.series[0].values;
      const tmfAll = data.series[1].values;
      const diffAll = mxfAll.map((m, i) =>
        m != null && tmfAll[i] != null ? Math.round((m - tmfAll[i]) * 100) / 100 : null
      );
      const scoreAll = mxfAll.map((m, i) => {
        if (m == null || tmfAll[i] == null || diffAll[i] == null) return null;
        const s1 = !(m > thMxf) ? 1 : -1;
        const s2 = !(tmfAll[i] > thTmf) ? 1 : -1;
        const s3 = diffAll[i] > thDiff ? 1 : -1;
        return s1 + s2 + s3;
      });

      const dockGroup = document.createElement("div");
      dockGroup.className = "docked-chart-group";
      dockGroup.innerHTML = `
        <div class="docked-pane">
          <div class="chart-box-header">
            <span>圖一：加權指數 (TWSE)</span>
            <span class="pane-pills" id="ret-pills-0"></span>
          </div>
          <div class="chart-canvas-wrap pane-h-idx"><canvas id="ret-cv-0"></canvas></div>
        </div>
        <div class="docked-pane">
          <div class="chart-box-header">
            <span>圖二：散戶多空綜合分數（-3 ~ +3）</span>
            <span class="pane-pills" id="ret-pills-score"></span>
          </div>
          <div class="chart-canvas-wrap pane-h-sub"><canvas id="ret-cv-score"></canvas></div>
        </div>
        <div class="docked-pane">
          <div class="chart-box-header">
            <span>圖三：小台散戶多空比(%) [&lt;= 門檻為紅偏多]</span>
            <span class="pane-pills">
              <span id="ret-pills-1" class="pane-pills"></span>
              <span>門檻：<input id="th-mxf" type="number" value="${thMxf}" style="width:54px">%</span>
            </span>
          </div>
          <div class="chart-canvas-wrap pane-h-sub"><canvas id="ret-cv-1"></canvas></div>
        </div>
        <div class="docked-pane">
          <div class="chart-box-header">
            <span>圖四：微台散戶多空比(%) [&lt;= 門檻偏多 · 2024/07/29 掛牌]</span>
            <span class="pane-pills">
              <span id="ret-pills-2" class="pane-pills"></span>
              <span>門檻：<input id="th-tmf" type="number" value="${thTmf}" style="width:54px">%</span>
            </span>
          </div>
          <div class="chart-canvas-wrap pane-h-sub"><canvas id="ret-cv-2"></canvas></div>
        </div>
        <div class="docked-pane">
          <div class="chart-box-header">
            <span>圖五：小台 − 微台散戶差值(%) [&gt; 門檻為紅偏多]</span>
            <span class="pane-pills">
              <span id="ret-pills-3" class="pane-pills"></span>
              <span>門檻：<input id="th-diff" type="number" value="${thDiff}" style="width:54px">%</span>
            </span>
          </div>
          <div class="chart-canvas-wrap pane-h-sub-bottom"><canvas id="ret-cv-3"></canvas></div>
        </div>
      `;
      stackEl.appendChild(dockGroup);

      const drawerEl = document.createElement("details");
      drawerEl.className = "analysis-drawer";
      if (prevOpen) drawerEl.open = true;
      drawerEl.innerHTML = `
        <summary class="analysis-drawer-summary">
          <span>📖 點擊展開／收合「大小散戶反向籌碼與處分效應量化解析」（共 5 則）</span>
          <span class="drawer-chevron">▼</span>
        </summary>
        <div class="analysis-drawer-body">
          <div class="chart-analysis-note" id="ret-note-0"></div>
          <div class="chart-analysis-note" id="ret-note-score"></div>
          <div class="chart-analysis-note" id="ret-note-1"></div>
          <div class="chart-analysis-note" id="ret-note-2"></div>
          <div class="chart-analysis-note" id="ret-note-3"></div>
        </div>
      `;
      stackEl.appendChild(drawerEl);
      bindPanelDrawersSync("panel-retail");

      retCharts.push(createIndexLineChart(dockGroup.querySelector("#ret-cv-0"), data.labels, data.point, true, [], false));
      retCharts.push(createThresholdBarChart(dockGroup.querySelector("#ret-cv-score"), data.labels, scoreAll, 0, false, false));
      retCharts.push(createThresholdBarChart(dockGroup.querySelector("#ret-cv-1"), data.labels, mxfAll, thMxf, true, false));
      retCharts.push(createThresholdBarChart(dockGroup.querySelector("#ret-cv-2"), data.labels, tmfAll, thTmf, true, false));
      retCharts.push(createThresholdBarChart(dockGroup.querySelector("#ret-cv-3"), data.labels, diffAll, thDiff, false, true));

      updateRetailNotesFn = (s, e) => {
        const curSc = scoreAll[e];
        const curM = mxfAll[e];
        const curT = tmfAll[e];
        const curD = diffAll[e];

        document.getElementById("ret-pills-0").innerHTML = renderMiniPillsHTML([
          { text: `收盤 ${fmtNum(data.point[e], 0)} 點` },
        ]);
        document.getElementById("ret-pills-score").innerHTML = renderMiniPillsHTML([
          { text: `綜合分數 ${curSc != null ? (curSc > 0 ? "+" + curSc : curSc) : "-"} / ±3`, cls: (curSc ?? 0) > 0 ? "bull" : "bear" },
        ]);
        document.getElementById("ret-pills-1").innerHTML = renderMiniPillsHTML([
          { text: `期末 ${curM != null ? curM + "%" : "-"}`, cls: curM != null && !(curM > thMxf) ? "bull" : "bear" },
        ]);
        document.getElementById("ret-pills-2").innerHTML = renderMiniPillsHTML([
          { text: `期末 ${curT != null ? curT + "%" : "未掛牌"}`, cls: curT != null && !(curT > thTmf) ? "bull" : "bear" },
        ]);
        document.getElementById("ret-pills-3").innerHTML = renderMiniPillsHTML([
          { text: `差值 ${curD != null ? curD + "%" : "-"}`, cls: curD != null && curD > thDiff ? "bull" : "bear" },
        ]);

        document.getElementById("ret-note-0").innerHTML = renderAnalysisNoteHTML(
          [
            { text: `期末指數：${fmtNum(data.point[e], 2)} 點` },
            { text: `期末散戶綜合分數：${curSc ?? "-"} 分`, cls: (curSc ?? 0) > 0 ? "bull" : "bear" },
          ],
          "行為財務學『處分效應』實證 (Barber, Lee, Liu & Odean, RFS)",
          "國際頂尖期刊針對台灣期現貨市場實證指出：自然人交易者普遍存在「上漲過早獲利了結甚至反手摸頭放空、下跌卻逆勢不斷攤平接刀」之行為偏誤，使散戶未平倉淨部位成為法人對手盤最穩定之反向指標（Contrarian Indicator）。",
          "軋空行情 vs. 多殺多行情",
          "當大盤創高而小台／微台散戶持續維持負值（散戶放空被軋），漲勢往往欲小不易；反之當大盤破線下跌而散戶多空比飆高（綠柱高聳），代表籌碼凌亂，切忌與散戶同側搶短。"
        );
        document.getElementById("ret-note-score").innerHTML = renderAnalysisNoteHTML(
          [{ text: `期末分數：${curSc ?? "-"} / ±3`, cls: (curSc ?? 0) > 0 ? "bull" : "bear" }],
          "三因子合成籌碼濾網 (-3, -1, +1, +3)",
          `綜合評估（1）小台散戶 <code>&lt;= ${thMxf}%</code>、（2）微台散戶 <code>&lt;= ${thTmf}%</code>、（3）小台−微台差值 <code>&gt; ${thDiff}%</code>。每滿足一項得 <code>+1</code> 分，否則 <code>-1</code> 分。`,
          "實戰倉位加減碼依據",
          "<code>+3 分（全紅）</code>代表大小散戶同步退潮甚至翻空，為極佳做多籌碼溫床；<code>-3 分（全綠）</code>代表散戶全面重倉套牢且微台極度擁擠，多單必須嚴格防守。"
        );
        document.getElementById("ret-note-1").innerHTML = renderAnalysisNoteHTML(
          [
            { text: `期末小台散戶比：${curM != null ? curM + "%" : "-"}`, cls: curM != null && !(curM > thMxf) ? "bull" : "bear" },
            { text: `多空門檻：<= ${thMxf}% 偏多` },
          ],
          "小台指 (MTX，每點 50 元) — 傳統自然人與中實戶指標",
          "小台契約規格為微台之 5 倍，參與者保證金門檻較高。在牛市常態偏多環境中，小台散戶多空比即使略大於 0（只要 <code>&lt;= 15%</code>）仍不構成籌碼威脅；一旦飆破 <code>20% ~ 35%</code> 以上，代表散戶大舉槓桿抄底。",
          "斷頭清洗訊號（Capitulation）",
          "若重挫當日小台散戶比單日驟降逾 10 個百分點（例如由 30%+ 急殺回落至 15% 附近），代表期貨商盤中強制砍倉（斷頭追繳）已清洗首波浮額，短線反彈機率大增。"
        );
        document.getElementById("ret-note-2").innerHTML = renderAnalysisNoteHTML(
          [
            { text: `期末微台散戶比：${curT != null ? curT + "%" : "未掛牌"}`, cls: curT != null && !(curT > thTmf) ? "bull" : "bear" },
            { text: `多空門檻：<= ${thTmf}% 偏多` },
          ],
          "微台指 (TMF，每點 10 元) — 極小資散戶情緒溫度計",
          "2024/07/29 掛牌後迅速成為年輕與小額自然人首選工具。因單口保證金低、凹單容忍度高，微台散戶在大跌時更容易呈現『死抱不退』甚至極端高達 <code>+45% ~ +55%</code> 之擁擠多單。",
          "真正市場底之檢驗標準",
          "僅小台斷頭往往只能造就第一波反彈；唯有等到微台散戶因反彈解套或失去耐心而回落至 <code>&lt;= 30%</code> 以下（轉紅柱），才代表中級底部籌碼真正沉澱完畢。"
        );
        document.getElementById("ret-note-3").innerHTML = renderAnalysisNoteHTML(
          [
            { text: `期末 (小台 − 微台) 差值：${curD != null ? curD + "%" : "-"}`, cls: curD != null && curD > thDiff ? "bull" : "bear" },
            { text: `正向門檻：> ${thDiff}% 偏多` },
          ],
          "跨資金級距結構差（Capital-Tier Divergence）",
          "注意本圖為<strong>正向指標（非反指標）</strong>：比較資金較大之小台帳戶與極小額微台帳戶之相對態度。當『小台散戶比 &gt; 微台散戶比 - 5%』時為紅柱；當微台散戶比遠高於小台（例如小台已停損或轉空、微台卻狂買，使差值深跌至 <code>-15% ~ -30%</code> 綠柱），揭示市場仍充滿小資盲目接刀籌碼。",
          "底部收斂訊號",
          "急跌過後若觀察到綠柱由 <code>-25%</code> 以下快速收斂並重新翻上 <code>-5%</code> 紅柱區，即確認大小散戶結構分歧消除、籌碼重回健康狀態。"
        );
      };

      dockGroup.querySelector("#th-mxf").addEventListener("change", (ev) => {
        thMxf = parseFloat(ev.target.value) || 0;
        buildRetailCharts();
      });
      dockGroup.querySelector("#th-tmf").addEventListener("change", (ev) => {
        thTmf = parseFloat(ev.target.value) || 0;
        buildRetailCharts();
      });
      dockGroup.querySelector("#th-diff").addEventListener("change", (ev) => {
        thDiff = parseFloat(ev.target.value) || 0;
        buildRetailCharts();
      });

      bindSyncHover(retCharts, data.labels, readoutEl, (i) => [
        { name: "加權指數", value: data.point[i] != null ? data.point[i].toLocaleString() : "-" },
        { name: "散戶分數", value: scoreAll[i], color: (scoreAll[i] ?? 0) > 0 ? "#f87171" : "#34d399" },
        { name: "小台(%)", value: mxfAll[i], color: mxfAll[i] != null && !(mxfAll[i] > thMxf) ? "#f87171" : "#34d399" },
        { name: "微台(%)", value: tmfAll[i], color: tmfAll[i] != null && !(tmfAll[i] > thTmf) ? "#f87171" : "#34d399" },
        { name: "小台−微台(%)", value: diffAll[i], color: diffAll[i] != null && diffAll[i] > thDiff ? "#f87171" : "#34d399" },
      ]);

      applyZoomToCharts(retCharts, currentRange[0], currentRange[1]);
      updateRetailNotesFn(currentRange[0], currentRange[1]);
    }

    buildRetailCharts();
    buildZoomAndSliderControls(ctrlEl, "retail", data.labels, 245, (s, e) => {
      currentRange = [s, e];
      applyZoomToCharts(retCharts, s, e);
      updateRetailNotesFn(s, e);
    });
  }

  // 5. Lobster Backtest Tab
  let btLoaded = false;
  let btCharts = [];
  async function initBacktestTab(forceReload = false) {
    if (btLoaded && !forceReload) return;
    btLoaded = true;

    const data = await fetch("/api/charts/lobster/backtest").then((r) => r.json());
    document.getElementById("bt-meta").textContent =
      `完整資料庫期間：${data.labels[0] || ""} ~ ${data.dataDate}（共 ${data.labels.length.toLocaleString()} 個交易日；若啟用條件4微台則自動自 2024/07/29 起算，停用微台可回測完整 5+ 年）`;

    const condPanel = document.getElementById("bt-cond-panel");
    const ctrlEl = document.getElementById("bt-controls");
    const tradePanel = document.getElementById("bt-trade-panel");
    const stackEl = document.getElementById("bt-charts");
    const resEl = document.getElementById("bt-results");
    const readoutEl = document.getElementById("bt-readout");
    let currentRange = [0, Math.max(0, data.labels.length - 1)];

    const opOptions = (def) => `
      <option value="both" ${def === "both" ? "selected" : ""}>雙向 ±1</option>
      <option value="gt" ${def === "gt" ? "selected" : ""}>大於 (&gt;)</option>
      <option value="lt" ${def === "lt" ? "selected" : ""}>小於 (&lt;)</option>
      <option value="" ${def === "" ? "selected" : ""}>停用 (空白)</option>
    `;

    condPanel.innerHTML = `
      <div class="cond-panel-title">📊 多空分數條件設定（小台／微台為反指標；停用微台即可回測完整 2020~2026 六年區間）</div>
      <div class="cond-grid">
        <div class="cond-item">
          <strong>1. Lobster</strong>
          <span><select id="c1-op">${opOptions("both")}</select> <input type="number" id="c1-th" value="0" style="width:62px"></span>
        </div>
        <div class="cond-item">
          <strong>2. Lobster_Sum</strong>
          <span><select id="c2-op">${opOptions("both")}</select> <input type="number" id="c2-th" value="0" style="width:62px"></span>
        </div>
        <div class="cond-item">
          <strong>3. 小台散戶(%)</strong>
          <span><select id="c3-op">${opOptions("both")}</select> <input type="number" id="c3-th" value="15" style="width:62px"></span>
        </div>
        <div class="cond-item">
          <strong>4. 微台散戶(%)</strong>
          <span><select id="c4-op">${opOptions("both")}</select> <input type="number" id="c4-th" value="30" style="width:62px"></span>
        </div>
      </div>
    `;

    tradePanel.innerHTML = `
      <div class="cond-panel-title">⚡ 狀態轉換買賣回測條件</div>
      <div class="cond-row">
        <span>📈 <strong>買進條件</strong>：前 <input type="number" id="bt-buy-days" value="30"> 日內分數曾 &lt;= <input type="number" id="bt-buy-from" value="-1"> 分，且今日分數升至 &gt;= <input type="number" id="bt-buy-to" value="2"> 分</span>
      </div>
      <div class="cond-row">
        <span>📉 <strong>賣出條件</strong>：前 <input type="number" id="bt-sell-days" value="30"> 日內分數曾 &gt;= <input type="number" id="bt-sell-from" value="2"> 分，且今日分數降至 &lt;= <input type="number" id="bt-sell-to" value="-1"> 分</span>
        <button type="button" id="btn-run-bt" class="btn btn-pdf">🚀 執行回測</button>
      </div>
    `;

    const zoomCtrl = buildZoomAndSliderControls(ctrlEl, "backtest", data.labels, 0, (s, e) => {
      currentRange = [s, e];
      applyZoomToCharts(btCharts, s, e);
    });

    async function runBacktest() {
      const payload = {
        c1_op: document.getElementById("c1-op").value,
        c1_threshold: parseFloat(document.getElementById("c1-th").value) || 0,
        c2_op: document.getElementById("c2-op").value,
        c2_threshold: parseFloat(document.getElementById("c2-th").value) || 0,
        c3_op: document.getElementById("c3-op").value,
        c3_threshold: parseFloat(document.getElementById("c3-th").value) || 0,
        c4_op: document.getElementById("c4-op").value,
        c4_threshold: parseFloat(document.getElementById("c4-th").value) || 0,
        buyDays: parseInt(document.getElementById("bt-buy-days").value, 10) || 30,
        buyFrom: parseInt(document.getElementById("bt-buy-from").value, 10),
        buyTo: parseInt(document.getElementById("bt-buy-to").value, 10),
        sellDays: parseInt(document.getElementById("bt-sell-days").value, 10) || 30,
        sellFrom: parseInt(document.getElementById("bt-sell-from").value, 10),
        sellTo: parseInt(document.getElementById("bt-sell-to").value, 10),
      };

      const btRes = await fetch("/api/charts/lobster/backtest/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then((r) => r.json());

      const prevOpen = Boolean(stackEl.querySelector("details.analysis-drawer")?.open);
      destroyChartList(btCharts);
      btCharts = [];
      stackEl.innerHTML = "";

      const buyMarkers = new Array(data.labels.length).fill(null);
      const sellMarkers = new Array(data.labels.length).fill(null);
      (btRes.trades || []).forEach((t) => {
        if (t.buyIdx != null) buyMarkers[t.buyIdx] = t.buyPrice;
        if (t.sellIdx != null) sellMarkers[t.sellIdx] = t.sellPrice;
      });
      if (btRes.holding && btRes.holding.buyIdx != null) {
        buyMarkers[btRes.holding.buyIdx] = btRes.holding.buyPrice;
      }

      const s = btRes.summary || {};
      const lastSc = btRes.scores[btRes.scores.length - 1];

      const dockGroup = document.createElement("div");
      dockGroup.className = "docked-chart-group";
      dockGroup.innerHTML = `
        <div class="docked-pane">
          <div class="chart-box-header">
            <span>圖一：加權指數 (TWSE) 實盤進出點位映射（紅▲買進 / 綠▼賣出）</span>
            <span class="pane-pills">
              ${renderMiniPillsHTML([
                { text: `起算 ${btRes.effectiveStartDate || "-"}` },
                { text: `勝率 ${s.winRatePct ?? 0}%`, cls: (s.winRatePct ?? 0) >= 55 ? "bull" : "" },
                { text: `複利 ${s.cumReturnPct ?? 0}%`, cls: (s.cumReturnPct ?? 0) >= 0 ? "bull" : "bear" },
              ])}
            </span>
          </div>
          <div class="chart-canvas-wrap pane-h-idx"><canvas id="bt-cv-0"></canvas></div>
        </div>
        <div class="docked-pane">
          <div class="chart-box-header">
            <span>圖二：多條件合成多空分數曲線（價格動能 × 散戶反向籌碼）</span>
            <span class="pane-pills">
              ${renderMiniPillsHTML([
                { text: `期末分數 ${lastSc ?? "-"}`, cls: (lastSc ?? 0) > 0 ? "bull" : "bear" },
              ])}
            </span>
          </div>
          <div class="chart-canvas-wrap pane-h-lob-sum"><canvas id="bt-cv-1"></canvas></div>
        </div>
      `;
      stackEl.appendChild(dockGroup);

      const drawerEl = document.createElement("details");
      drawerEl.className = "analysis-drawer";
      if (prevOpen) drawerEl.open = true;
      drawerEl.innerHTML = `
        <summary class="analysis-drawer-summary">
          <span>📖 點擊展開／收合「狀態轉換進出場機制與多因子正交解析」（共 2 則）</span>
          <span class="drawer-chevron">▼</span>
        </summary>
        <div class="analysis-drawer-body">
          <div class="chart-analysis-note">${renderAnalysisNoteHTML(
            [
              { text: `已實現交易：${s.totalTrades ?? 0} 筆` },
              { text: `歷史勝率：${s.winRatePct ?? 0}%`, cls: (s.winRatePct ?? 0) >= 55 ? "bull" : "" },
              { text: `累積複利報酬：${s.cumReturnPct ?? 0}%`, cls: (s.cumReturnPct ?? 0) >= 0 ? "bull" : "bear" },
            ],
            "狀態轉換進出場機制 (Regime-Transition Trigger)",
            "不同於單純分數突破即買進，本回測引擎要求『先經歷洗盤沉澱（過去 N 日內分數曾落入負值區），再由低檔強勢躍升跨越多方門檻』才觸發紅▲買進，能有效過濾高檔鈍化末段之追高風險。",
            "跨週期驗證技巧",
            "將條件 4（微台散戶）設為『停用』即可將回測區間完整拉長至 2020/11 起逾 5 年牛熊循環（涵蓋 2022 升息熊市與 2024~2026 AI 大波段），檢驗策略在不同利率環境下之穩健度。"
          )}</div>
          <div class="chart-analysis-note">${renderAnalysisNoteHTML(
            [{ text: `期末綜合分數：${lastSc ?? "-"}`, cls: (lastSc ?? 0) > 0 ? "bull" : "bear" }],
            "多因子正交互補效應 (Factor Orthogonality)",
            "價格動能因子（<code>Lobster</code> / <code>Lobster_Sum</code>）負責確認市場資金已點火向上；籌碼反向因子（<code>小台 / 微台散戶比</code>）負責確認散戶浮額已清洗乾淨。雙維度正交結合能大幅降低單一技術指標假突破機率。",
            "分數極值意義",
            "當合成曲線由綠區深處（<code>-4 / -2</code>）快速穿軸躍升至紅區（<code>+2 / +4</code>），代表『價格翻多＋散戶退場』同步達成，為期望值最高之波段切入點。"
          )}</div>
        </div>
      `;
      stackEl.appendChild(drawerEl);
      bindPanelDrawersSync("panel-backtest");

      const pal = getThemePalette();
      const markerDatasets = [
        {
          label: "買進",
          data: buyMarkers,
          showLine: false,
          pointRadius: 6.5,
          pointStyle: "triangle",
          pointBackgroundColor: pal.bullSolid,
          pointBorderColor: pal.markerBorder,
          pointBorderWidth: 1.3,
        },
        {
          label: "賣出",
          data: sellMarkers,
          showLine: false,
          pointRadius: 6.5,
          pointStyle: "triangle",
          pointRotation: 180,
          pointBackgroundColor: pal.bearSolid,
          pointBorderColor: pal.markerBorder,
          pointBorderWidth: 1.3,
        },
      ];

      btCharts.push(createIndexLineChart(dockGroup.querySelector("#bt-cv-0"), data.labels, data.point, false, markerDatasets, false));
      btCharts.push(createSignAreaChart(dockGroup.querySelector("#bt-cv-1"), data.labels, btRes.scores, false, null, true));

      if (btRes.effectiveStartIdx != null && currentRange[0] < btRes.effectiveStartIdx && payload.c4_op !== "") {
        zoomCtrl.setRange(btRes.effectiveStartIdx, data.labels.length - 1);
      } else {
        applyZoomToCharts(btCharts, currentRange[0], currentRange[1]);
      }

      bindSyncHover(btCharts, data.labels, readoutEl, (i) => [
        { name: "加權指數", value: data.point[i] != null ? data.point[i].toLocaleString() : "-" },
        { name: "多空分數", value: btRes.scores[i] ?? "-", color: (btRes.scores[i] ?? 0) > 0 ? "#f87171" : "#34d399" },
        { name: "Lobster", value: data.lobster[i] },
        { name: "Sum", value: data.lobster_sum[i] },
        { name: "小台(%)", value: data.mxf[i] ?? "-" },
        { name: "微台(%)", value: data.tmf[i] ?? "-" },
      ]);

      const h = btRes.holding;
      resEl.innerHTML = `
        ${
          h
            ? `<div class="holding-banner">📌 <strong>目前持倉中（未平倉部位，不計入已實現勝率統計）</strong>：於 <code>${h.buyDate}</code> 以 <strong>${h.buyPrice.toLocaleString()}</strong> 點買進（持有 ${h.holdDays} 日，最新 ${h.lastPrice.toLocaleString()} 點，浮動損益 <strong class="${h.profitPts >= 0 ? "val-pos" : "val-neg"}">${h.profitPts > 0 ? "+" : ""}${h.profitPts} 點 / ${h.returnPct > 0 ? "+" : ""}${h.returnPct}%</strong>）</div>`
            : ""
        }
        <div class="kpi-grid">
          <div class="kpi-card"><div class="kpi-label">已實現交易次數</div><div class="kpi-val">${s.totalTrades ?? 0} 次</div></div>
          <div class="kpi-card"><div class="kpi-label">勝率 (Win Rate)</div><div class="kpi-val">${s.winRatePct ?? 0}%</div></div>
          <div class="kpi-card"><div class="kpi-label">平均單筆報酬</div><div class="kpi-val ${(s.avgReturnPct ?? 0) >= 0 ? "val-pos" : "val-neg"}">${s.avgReturnPct ?? 0}%</div></div>
          <div class="kpi-card"><div class="kpi-label">累積複利報酬</div><div class="kpi-val ${(s.cumReturnPct ?? 0) >= 0 ? "val-pos" : "val-neg"}">${s.cumReturnPct ?? 0}%</div></div>
          <div class="kpi-card"><div class="kpi-label">累積總點數</div><div class="kpi-val ${(s.totalProfitPts ?? 0) >= 0 ? "val-pos" : "val-neg"}">${s.totalProfitPts ?? 0} 點</div></div>
        </div>
        <div class="table-scroll-wrap">
          <table class="trade-table">
            <thead>
              <tr>
                <th>#</th><th>買進日期</th><th>買進指數</th><th>賣出日期</th><th>賣出指數</th><th>持有天數</th><th>損益點數</th><th>報酬率(%)</th>
              </tr>
            </thead>
            <tbody>
              ${(btRes.trades || [])
                .map(
                  (t, idx) => `
                <tr>
                  <td>${idx + 1}</td>
                  <td>${t.buyDate}</td>
                  <td>${t.buyPrice.toLocaleString()}</td>
                  <td>${t.sellDate}</td>
                  <td>${t.sellPrice.toLocaleString()}</td>
                  <td>${t.holdDays}</td>
                  <td class="${t.profitPts >= 0 ? "val-pos" : "val-neg"}">${t.profitPts > 0 ? "+" : ""}${t.profitPts}</td>
                  <td class="${t.returnPct >= 0 ? "val-pos" : "val-neg"}">${t.returnPct > 0 ? "+" : ""}${t.returnPct}%</td>
                </tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>
      `;
    }

    document.getElementById("btn-run-bt").addEventListener("click", runBacktest);
    ["c1-op", "c1-th", "c2-op", "c2-th", "c3-op", "c3-th", "c4-op", "c4-th"].forEach((id) => {
      document.getElementById(id).addEventListener("change", runBacktest);
    });
    await runBacktest();
  }

  // 6. Turtle Tab (Unified 10-Track Docked Matrix — Desktop & Mobile Single-Screen View)
  let turLoaded = false;
  let turCharts = [];
  async function initTurtleTab(forceReload = false) {
    if (turLoaded && !forceReload) return;
    turLoaded = true;

    const [data, overview] = await Promise.all([
      fetch("/api/charts/turtle/data").then((r) => r.json()),
      fetchStrategyOverview(forceReload),
    ]);
    document.getElementById("tur-meta").textContent =
      `資料期間：${data.labels[0] || ""} ~ ${data.dataDate}（共 ${data.labels.length.toLocaleString()} 個交易日，逾 5 年完整回溯）`;

    const ctrlEl = document.getElementById("tur-controls");
    const stackEl = document.getElementById("tur-charts");
    const readoutEl = document.getElementById("tur-readout");
    const stratEl = document.getElementById("tur-strategy-box");
    destroyChartList(turCharts);
    turCharts = [];
    stackEl.innerHTML = "";

    const v1Rows = data.v1.map((r) => ({ name: `V1_${r.name}`, values: r.values }));
    const v2Rows = data.v2.map((r) => ({ name: `V2_${r.name}`, values: r.values }));
    const v3Rows = data.v3.map((r) => ({ name: `V3_${r.name}`, values: r.values }));
    const allRows = [...v1Rows, ...v2Rows, ...v3Rows];

    // Unified 10-Track Matrix with visual group separator rows between V1 / V2 / V3
    const matrixRows = [
      ...v1Rows,
      { name: "", isDivider: true, values: [] },
      ...v2Rows,
      { name: "", isDivider: true, values: [] },
      ...v3Rows,
    ];

    const dockGroup = document.createElement("div");
    dockGroup.className = "docked-chart-group";
    dockGroup.innerHTML = `
      <div class="docked-pane">
        <div class="chart-box-header">
          <span>圖一：台灣加權指數 (TWSE)</span>
          <span class="pane-pills" id="tur-pills-0"></span>
        </div>
        <div class="chart-canvas-wrap pane-h-idx"><canvas id="tur-cv-0"></canvas></div>
      </div>
      <div class="docked-pane">
        <div class="chart-box-header">
          <span>圖二：海龜 V1・V2・V3 全系列 10 軌共振矩陣（紅 +1 偏多 · 綠 -1 偏空）</span>
          <span class="pane-pills" id="tur-pills-1"></span>
        </div>
        <div class="chart-canvas-wrap pane-h-tur-matrix"><canvas id="tur-cv-1"></canvas></div>
      </div>
    `;
    stackEl.appendChild(dockGroup);

    const drawerEl = document.createElement("details");
    drawerEl.className = "analysis-drawer";
    drawerEl.innerHTML = `
      <summary class="analysis-drawer-summary">
        <span>📖 點擊展開／收合「海龜 V1 / V2 / V3 十軌共振機制與資金水位計解析」（共 4 則）</span>
        <span class="drawer-chevron">▼</span>
      </summary>
      <div class="analysis-drawer-body">
        <div class="chart-analysis-note" id="tur-note-0"></div>
        <div class="chart-analysis-note" id="tur-note-1"></div>
        <div class="chart-analysis-note" id="tur-note-2"></div>
        <div class="chart-analysis-note" id="tur-note-3"></div>
      </div>
    `;
    stackEl.appendChild(drawerEl);

    stratEl.innerHTML = renderEmbeddedStrategyBlock(overview, "turtle");
    bindPanelDrawersSync("panel-turtle");

    turCharts = [
      createIndexLineChart(dockGroup.querySelector("#tur-cv-0"), data.labels, data.point, false, [], false),
      createAlignedRibbonChart(dockGroup.querySelector("#tur-cv-1"), data.labels, matrixRows, true),
    ];

    function updateTurtleNotes(s, e) {
      const idxStat = calcWindowIndexStats(data.point, s, e);
      const sV1A = calcSignalWindowStats(v1Rows[0].values, s, e);
      const sV1D = calcSignalWindowStats(v1Rows[3].values, s, e);
      const sV2_4 = calcSignalWindowStats(v2Rows[2].values, s, e);
      const sV2_5 = calcSignalWindowStats(v2Rows[0].values, s, e);
      const sV3_5 = calcSignalWindowStats(v3Rows[0].values, s, e);

      const v1Now = v1Rows.filter((r) => r.values[e] > 0).length;
      const v2Now = v2Rows.filter((r) => r.values[e] > 0).length;
      const v3Now = v3Rows.filter((r) => r.values[e] > 0).length;
      const totNow = v1Now + v2Now + v3Now;

      document.getElementById("tur-pills-0").innerHTML = renderMiniPillsHTML([
        { text: `漲跌 ${idxStat.retPct > 0 ? "+" : ""}${idxStat.retPct}%`, cls: idxStat.retPct >= 0 ? "bull" : "bear" },
        { text: `MDD ${idxStat.mddPct}%`, cls: idxStat.mddPct < -15 ? "bear" : "" },
      ]);
      document.getElementById("tur-pills-1").innerHTML = renderMiniPillsHTML([
        { text: `V1: ${v1Now}/4`, cls: v1Now >= 2 ? "bull" : "bear" },
        { text: `V2: ${v2Now}/3`, cls: v2Now >= 2 ? "bull" : "bear" },
        { text: `V3: ${v3Now}/3`, cls: v3Now >= 2 ? "bull" : "bear" },
        { text: `總廣度: ${totNow}/10 偏多`, cls: totNow >= 5 ? "bull" : "bear" },
      ]);

      document.getElementById("tur-note-0").innerHTML = renderAnalysisNoteHTML(
        [
          { text: `區間指數報酬：${idxStat.retPct > 0 ? "+" : ""}${idxStat.retPct}%`, cls: idxStat.retPct >= 0 ? "bull" : "bear" },
          { text: `區間最大回撤：${idxStat.mddPct}%`, cls: idxStat.mddPct < -15 ? "bear" : "" },
          { text: `期末海龜總廣度：${totNow} / 10 偏多`, cls: totNow >= 5 ? "bull" : "bear" },
        ],
        "中長期宏觀景氣與流動性定價",
        "台股中長期軌跡受全球半導體庫存週期（Silicon Cycle）、AI 基礎建設資本支出週期及聯準會流動性循環三大慢變數主導。海龜指標之核心價值不在抓最低點，而在於『完整咬住長達數月至一整年的主升段，並在熊市主跌段強制空手保住勝利果實』。",
        "10 軌共振資金水位計",
        "將下方 10 條海龜訊號視為<strong>核心持股配置比例尺</strong>：當 <code>8~10 軌全紅</code> 時可維持高水位順勢部位；當跌至 <code>0~2 軌偏多</code> 時，無論新聞題材多樂觀，皆代表大盤處於空方趨勢保護期，嚴禁擴大槓桿。"
      );

      document.getElementById("tur-note-1").innerHTML = renderAnalysisNoteHTML(
        [
          { text: `期末 V1 偏多數：${v1Now} / 4`, cls: v1Now >= 2 ? "bull" : "bear" },
          { text: `V1_A 翻轉 ${sV1A.flips} 次（偏多 ${sV1A.bullPct}%）` },
          { text: `V1_D 翻轉 ${sV1D.flips} 次（平均每段 ${sV1D.avgHold} 日）` },
        ],
        "非對稱唐奇安通道 (Asymmetric Donchian Breakout：階梯進場、同步出場)",
        "源於經典海龜交易系統（System 2）之跨週期演進：<code>V1_A → V1_B → V1_C → V1_D</code> 進場突破視窗由快至慢遞增（約 45 至 115 個交易日），因此底部翻多時會呈現<strong>由上而下階梯式依序翻紅</strong>，天然契合「金字塔分批加碼」邏輯；反之跌破中線防守通道（約 42 日低點）時四軌<strong>同步由紅翻綠</strong>，確保崩盤初期果斷離場。",
        "V1 戰略判讀法則",
        "<code>V1_D</code> 為全系統最沉穩之牛熊分水嶺（5 年僅翻轉十餘次）；當 <code>V1_A</code> 率先翻紅代表長線初露曙光，待 <code>V1_C / V1_D</code> 全數翻紅即確認進入結構性大牛市；若四軌同日集體翻綠，務必無條件執行長線停利與避險。"
      );

      document.getElementById("tur-note-2").innerHTML = renderAnalysisNoteHTML(
        [
          { text: `期末 V2 偏多數：${v2Now} / 3`, cls: v2Now >= 2 ? "bull" : "bear" },
          { text: `V2_4（最靈敏）翻轉 ${sV2_4.flips} 次` },
          { text: `V2_5（最穩健）翻轉 ${sV2_5.flips} 次` },
        ],
        "中線通道突破結合 4.0% / 4.5% / 5.0% 移動停損機制",
        "單純長線通道在高點劇烈拉回時回吐幅度較大，<code>V2</code> 系列引入百分比移動停損與自低點反彈確認梯度（<code>4.0% / 4.5% / 5.0%</code>）：數字愈小（<code>V2_4</code>）對波段頭部回檔與底部反彈愈敏感；數字愈大（<code>V2_5</code>）容忍震盪空間愈寬。",
        "領先預警與波段鎖利應用",
        "在高檔轉折初期（如 2026 年 10 月中下旬），<code>V2_4 → V2_4.5 → V2_5</code> 會比 <code>V1</code> 提早數週翻綠，提供絕佳之<strong>高檔分批減碼預警</strong>；而在空頭跌深反彈時，<code>V2_4</code> 亦是海龜家族中最先翻紅之右側試單前哨兵。"
      );

      document.getElementById("tur-note-3").innerHTML = renderAnalysisNoteHTML(
        [
          { text: `期末 V3 偏多數：${v3Now} / 3`, cls: v3Now >= 2 ? "bull" : "bear" },
          { text: `V3_5 翻轉 ${sV3_5.flips} 次（平均每段 ${sV3_5.avgHold} 日）` },
        ],
        "長週期突破過濾 × 移動停損複合系統 (Regime-Filtered Trailing System)",
        "對比 V2 與 V3 可見：<code>V3</code> 保留了 <code>5.0% / 4.5% / 4.0%</code> 的高檔停損敏感度，但拉長了進場突破確認週期，有效過濾掉 <code>V2</code> 在空頭熊市中途反彈或大型箱型整理區間的短暫紅綠切換雜訊。",
        "V2 與 V3 交叉比對實戰技巧",
        "（1）<code>V2 翻紅但 V3 仍綠</code>：定調為空頭架構下之中級跌深反彈，反彈遇壓宜見好就收；（2）<code>V2 與 V3 同步全紅</code>：代表中線動能與長線趨勢達成共振，可安心抱牢核心波段部位不被短線震盪洗出場。"
      );
    }

    const renderGroupChips = (prefix, rows, i) => {
      const chips = rows
        .map((r) => {
          const shortLbl = r.name.replace(/^V[123]_/, "");
          const isBull = r.values[i] > 0;
          return `<span class="trk-chip ${isBull ? "bull" : "bear"}" title="${r.name}: ${isBull ? "偏多(+1)" : "偏空(-1)"}">${shortLbl}</span>`;
        })
        .join("");
      return `<span class="trk-group"><strong>${prefix}</strong>${chips}</span>`;
    };

    bindSyncHover(turCharts, data.labels, readoutEl, (i) => {
      const bullCnt = allRows.filter((r) => r.values[i] > 0).length;
      return [
        { name: "加權指數", value: data.point[i] != null ? data.point[i].toLocaleString() : "-" },
        {
          name: "偏多廣度",
          value: `${bullCnt}/10`,
          color: bullCnt >= 5 ? "#f87171" : "#34d399",
        },
        { rawHtml: renderGroupChips("V1", v1Rows, i) },
        { rawHtml: renderGroupChips("V2", v2Rows, i) },
        { rawHtml: renderGroupChips("V3", v3Rows, i) },
      ];
    });

    buildZoomAndSliderControls(ctrlEl, "turtle", data.labels, 245, (s, e) => {
      applyZoomToCharts(turCharts, s, e);
      updateTurtleNotes(s, e);
    });
  }

  // 7. Full-Spectrum Macro & Constructive Investment Strategy Hub Tab
  let stratLoaded = false;
  async function initStrategyTab(forceReload = false) {
    if (stratLoaded && !forceReload) return;
    stratLoaded = true;

    const box = document.getElementById("strategy-hub-content");
    try {
      const ov = await fetchStrategyOverview(forceReload);
      if (!ov || !ov.ok) {
        box.innerHTML = `<div class="val-pos">無法載入策略報告</div>`;
        return;
      }
      const t = ov.telemetry;
      const reg = ov.regime;
      const gm = ov.globalMarkets || {};
      const gmList = Object.values(gm);
      const news = ov.newsIntel || {};
      const themes = news.activeThemes || [];
      const headlines = news.topHeadlines || [];

      box.innerHTML = `
        <div class="regime-banner ${reg.tone}">
          <div class="regime-banner-top">
            <h3>📌 即時跨市場量化總體定調：${reg.title}</h3>
            <span class="regime-sync-meta">台股資料日：<code>${ov.latestDate}</code> ｜ 國際行情與新聞同步：<code>${ov.intelSyncedAt || "即時"}</code></span>
          </div>
          <p>${reg.summary}</p>
          ${ov.aiChiefMemo ? `<div class="ai-memo-box"><strong>🤖 AI 首席策略長即時備忘錄</strong>：${ov.aiChiefMemo}</div>` : ""}
        </div>

        <h3 class="strategy-section-title">【零、全球跨市場即時行情脈搏 (Live 8-Asset Global Pulse)】</h3>
        <div class="global-pulse-grid">
          ${gmList
            .map((m) => {
              const riskOffAsset = m.key === "VIX" || m.key === "US10Y" || m.key === "USDTWD";
              const c1 = m.chg1dPct === 0 ? "" : m.chg1dPct > 0 ? (riskOffAsset ? "val-neg" : "val-pos") : riskOffAsset ? "val-pos" : "val-neg";
              const c5 = m.chg5dPct === 0 ? "" : m.chg5dPct > 0 ? (riskOffAsset ? "val-neg" : "val-pos") : riskOffAsset ? "val-pos" : "val-neg";
              return `
              <div class="pulse-card">
                <div class="pulse-name">${m.label} <span class="pulse-date">(${m.date})</span></div>
                <div class="pulse-val">${fmtNum(m.last, 2)} <span class="pulse-unit">${m.unit}</span></div>
                <div class="pulse-sub">
                  <span>1日: <strong class="${c1}">${m.chg1dPct > 0 ? "+" : ""}${m.chg1dPct}%</strong></span>
                  <span>5日: <strong class="${c5}">${m.chg5dPct > 0 ? "+" : ""}${m.chg5dPct}%</strong></span>
                </div>
              </div>`;
            })
            .join("")}
        </div>

        <h3 class="strategy-section-title">【一、台股 9 大資料庫即時量化遙測看板】</h3>
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">加權指數 / 波段回撤</div>
            <div class="kpi-val ${t.drawdownPct >= -10 ? "val-pos" : "val-neg"}">${fmtNum(t.lastPrice, 0)} <span style="font-size:13px">(${t.drawdownPct}%)</span></div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">20日年化波動率 (常態 ${t.volHistPct}%)</div>
            <div class="kpi-val ${t.vol20dPct <= 24 ? "val-pos" : "val-neg"}">${t.vol20dPct}%</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">龍蝦短中期 (LOB / SUM)</div>
            <div class="kpi-val ${t.lobster > 0 ? "val-pos" : "val-neg"}">${t.lobster > 0 ? "+2" : "-2"} / ${t.lobsterSum}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">海龜中長線偏多廣度</div>
            <div class="kpi-val ${t.turtleTotalBull >= 5 ? "val-pos" : "val-neg"}">${t.turtleTotalBull} / 10 軌</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">外資 10日現貨 / 期貨未平倉</div>
            <div class="kpi-val ${(t.spot10d ?? 0) >= 0 ? "val-pos" : "val-neg"}">${fmtNum(t.spot10d, 0)}億 / ${fmtNum((t.futOiLatest ?? 0) / 1000, 1)}k口</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">波動率目標建議持股 / 現金</div>
            <div class="kpi-val accent">${t.recommendedEquityPct}% / ${t.recommendedCashPct}%</div>
          </div>
        </div>

        <h3 class="strategy-section-title">【二、國際政經情勢、全球金融市場與台股微結構動態研判】</h3>
        <div class="strategy-grid-2">
          ${(ov.macroSynthesis || [])
            .map(
              (m) => `
            <div class="strategy-card">
              <h4>🌍 ${m.dimension}</h4>
              <p>${m.analysis}</p>
            </div>`
            )
            .join("")}
          <div class="strategy-card">
            <h4>📊 均線結構與小台／微台跨級距籌碼實盤透視</h4>
            <p>
              目前大盤收於 <strong>${fmtNum(t.lastPrice, 2)}</strong> 點（10日線 <code>${fmtNum(t.ma10, 0)}</code>、月線 <code>${fmtNum(t.ma20, 0)}</code>、季線 <code>${fmtNum(t.ma60, 0)}</code>、年線 <code>${fmtNum(t.ma240, 0)}</code>）。
              籌碼微結構呈現關鍵分層：小台散戶多空比最新為 <strong>${t.mxfLatest ?? "-"}%</strong>（前一日 <code>${t.mxfPrev ?? "-"}%</code>），微台散戶多空比則為 <strong>${t.tmfLatest ?? "-"}%</strong>，<code>小台 − 微台</code> 差值達 <strong>${t.retailDiff ?? "-"}%</strong>（散戶綜合分數 <code>${t.retailScore ?? "-"}</code> 分）。
              透過追蹤小台與微台收斂速度，可精準判斷市場是由「短線斷頭反彈」邁向「籌碼徹底沉澱之真正市場底」。
            </p>
          </div>
        </div>

        <h3 class="strategy-section-title">【三、建設性四階段實戰投資策略與動態執行藍圖 (Actionable Playbook)】</h3>
        <div class="strategy-grid-2">
          ${(ov.actionablePlaybook || [])
            .map(
              (p) => `
            <div class="strategy-card">
              <span class="cite-tag">${p.allocation}</span>
              <h4>🎯 ${p.phase}</h4>
              <ul>
                ${(p.tactics || []).map((item) => `<li>${item}</li>`).join("")}
              </ul>
            </div>`
            )
            .join("")}
        </div>

        <h3 class="strategy-section-title">【四、即時國內外財經與政經新聞情報雷達 (共掃描 ${news.headlineCount || 0} 則最新訊息)】</h3>
        <div class="theme-pills-row">
          ${
            themes.length
              ? themes.map((th) => `<span class="diag-pill ${th.tone || ""}">📡 ${th.label}（熱度 ${th.hits}）</span>`).join("")
              : `<span class="diag-pill">目前新聞情緒中性平穩</span>`
          }
        </div>
        <div class="news-list">
          ${headlines
            .map(
              (h) => `
            <div class="news-item">
              <a href="${h.link}" target="_blank" rel="noopener noreferrer">${h.title}</a>
              <div class="news-meta">🏷️ ${h.channel} ｜ ${h.source || "財經媒體"} ｜ 🕒 ${h.publishedAt}</div>
            </div>`
            )
            .join("")}
        </div>

        <h3 class="strategy-section-title">【五、內化國際頂尖金融期刊與機構量化研究理論基石 (Knowledge Base)】</h3>
        <div class="strategy-grid-2">
          ${(ov.academicPillars || [])
            .map(
              (a) => `
            <div class="strategy-card">
              <span class="cite-tag">📚 ${a.citation}</span>
              <h4>${a.title}</h4>
              <p>${a.essence}</p>
            </div>`
            )
            .join("")}
        </div>
      `;
    } catch (err) {
      box.innerHTML = `<div class="val-pos">載入策略報告失敗：${err.message}</div>`;
    }
  }

  function reloadActiveStrategyViews() {
    lobLoaded = false;
    turLoaded = false;
    stratLoaded = false;
    loadDbStatus();
    if (currentTab === "lobster") initLobsterTab(true);
    if (currentTab === "turtle") initTurtleTab(true);
    if (currentTab === "strategy") initStrategyTab(true);
  }

  // Brand Logo & Title Homepage Link (Returns to "龍蝦指標" Homepage)
  const homeLink = document.getElementById("brand-home-link");
  if (homeLink) {
    homeLink.addEventListener("click", (e) => {
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
      e.preventDefault();
      if (currentTab !== "lobster") {
        jumpToTab("lobster");
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  // Tab switching (auto-centers active tab on mobile horizontal ribbon)
  document.querySelectorAll(".subtab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".subtab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      try {
        btn.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
      } catch (_) {}
      const tab = btn.dataset.tab;
      currentTab = tab;
      updatePdfHref();
      document.querySelectorAll(".subtab-panel").forEach((p) => (p.style.display = "none"));
      document.getElementById(`panel-${tab}`).style.display = "block";
      if (tab === "lobster") initLobsterTab();
      if (tab === "foreign") initForeignTab();
      if (tab === "retail") initRetailTab();
      if (tab === "backtest") initBacktestTab();
      if (tab === "turtle") initTurtleTab();
      if (tab === "strategy") initStrategyTab();
    });
  });

  const toastEl = document.getElementById("update-toast");

  // Peer-to-Peer Bidirectional Sync (Local <-> Synology NAS)
  const syncPanel = document.getElementById("peer-sync-panel");
  const openSyncBtn = document.getElementById("btn-open-sync");
  const closeSyncBtn = document.getElementById("btn-close-sync");
  const execSyncBtn = document.getElementById("btn-exec-sync");
  const peerUrlInput = document.getElementById("input-peer-url");
  const syncDirSelect = document.getElementById("select-sync-dir");
  const chkSyncCode = document.getElementById("chk-sync-code");
  const lastSyncSpan = document.getElementById("peer-last-sync");

  async function loadPeerConfig() {
    try {
      const cfg = await fetch("/api/admin/lobturtle/peer-config").then((r) => r.json());
      if (peerUrlInput && cfg.peerUrl && !peerUrlInput.value) {
        peerUrlInput.value = cfg.peerUrl;
      }
      if (syncDirSelect && cfg.direction) {
        syncDirSelect.value = cfg.direction;
      }
      if (lastSyncSpan && cfg.lastSyncedAt) {
        lastSyncSpan.textContent = `（上次同步：${cfg.lastSyncedAt}）`;
      }
      if (chkSyncCode && cfg.isContainer) {
        chkSyncCode.checked = false;
      }
    } catch (_) {}
  }

  if (openSyncBtn && syncPanel) {
    openSyncBtn.addEventListener("click", () => {
      const hidden = syncPanel.style.display === "none";
      syncPanel.style.display = hidden ? "block" : "none";
      if (hidden) loadPeerConfig();
    });
  }
  if (closeSyncBtn && syncPanel) {
    closeSyncBtn.addEventListener("click", () => {
      syncPanel.style.display = "none";
    });
  }
  if (execSyncBtn) {
    execSyncBtn.addEventListener("click", async () => {
      const peerUrl = (peerUrlInput ? peerUrlInput.value : "").trim();
      const direction = syncDirSelect ? syncDirSelect.value : "both";
      const syncCode = Boolean(chkSyncCode && chkSyncCode.checked);
      execSyncBtn.disabled = true;
      const orig = execSyncBtn.textContent;
      execSyncBtn.textContent = "⏳ 雙向比對同步中...";
      toastEl.style.display = "block";
      toastEl.textContent = `正在與遠端節點 (${peerUrl || "未填寫"}) 執行 9 大資料庫${syncCode ? "與網站介面程式" : ""}無損雙向同步...`;
      try {
        const res = await fetch("/api/admin/lobturtle/peer-sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ peerUrl, direction, syncCode }),
        }).then((r) => r.json());
        if (!res.ok) {
          toastEl.textContent = `❌ 同步失敗：${res.error || "未知錯誤"}`;
          return;
        }
        if (lastSyncSpan && res.syncedAt) {
          lastSyncSpan.textContent = `（上次同步：${res.syncedAt}）`;
        }
        cachedStrategyOverview = null;
        await loadDbStatus();
        lobLoaded = false;
        forLoaded = false;
        retLoaded = false;
        btLoaded = false;
        turLoaded = false;
        stratLoaded = false;
        if (currentTab === "lobster") initLobsterTab(true);
        if (currentTab === "foreign") initForeignTab(true);
        if (currentTab === "retail") initRetailTab(true);
        if (currentTab === "backtest") initBacktestTab(true);
        if (currentTab === "turtle") initTurtleTab(true);
        if (currentTab === "strategy") initStrategyTab(true);
        const codeMsg = syncCode ? `、推送更新程式檔 ${res.codeUpdatedCount || 0} 個` : "";
        toastEl.textContent = `✅ 同步成功（${res.syncedAt}）！從遠端補入 ${res.pulledRows} 筆、推送至遠端 ${res.pushedRows} 筆${codeMsg}｜最新日期已對齊至 ${res.localLatestDate}！`;
      } catch (err) {
        toastEl.textContent = `❌ 同步連線失敗：${err.message}`;
      } finally {
        execSyncBtn.disabled = false;
        execSyncBtn.textContent = orig;
      }
    });
  }

  // Helper to update button state without destroying responsive .btn-label-full / .btn-label-short spans
  function setActionButtonBusy(btn, busy, busyFull, busyShort) {
    if (!btn) return;
    btn.disabled = busy;
    const full = btn.querySelector(".btn-label-full");
    const short = btn.querySelector(".btn-label-short");
    if (busy) {
      if (full) {
        btn.dataset.origFull = full.textContent;
        full.textContent = busyFull;
      }
      if (short) {
        btn.dataset.origShort = short.textContent;
        short.textContent = busyShort;
      }
    } else {
      if (full && btn.dataset.origFull) full.textContent = btn.dataset.origFull;
      if (short && btn.dataset.origShort) short.textContent = btn.dataset.origShort;
    }
  }

  // Live Global Market & International News Intelligence Sync Button
  const intelBtn = document.getElementById("btn-refresh-intel");
  if (intelBtn) {
    intelBtn.addEventListener("click", async () => {
      setActionButtonBusy(intelBtn, true, "同步全球市場中...", "同步中...");
      toastEl.style.display = "block";
      toastEl.textContent = "正在即時連線抓取費半/ADR/美股/VIX/美債殖利率/匯率及國內外最新政經新聞並重算投資策略...";
      try {
        const ov = await fetch("/api/strategy/refresh", { method: "POST" }).then((r) => r.json());
        cachedStrategyOverview = ov;
        reloadActiveStrategyViews();
        const mCnt = Object.keys(ov.globalMarkets || {}).length;
        const hCnt = (ov.newsIntel || {}).headlineCount || 0;
        toastEl.textContent = `✅ 國際情勢與策略重算完成（${ov.intelSyncedAt || ""}）：已同步 ${mCnt} 項全球跨市場指標與 ${hCnt} 則最新財經新聞！`;
      } catch (err) {
        toastEl.textContent = `❌ 國際情勢同步失敗：${err.message}`;
      } finally {
        setActionButtonBusy(intelBtn, false);
      }
    });
  }

  // One-Click Incremental Live Data Update (TWSE/TAIFEX 9 DBs + Global Macro & News)
  const refreshBtn = document.getElementById("btn-refresh-db");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", async () => {
      setActionButtonBusy(refreshBtn, true, "連線證交所更新中...", "更新中...");
      toastEl.style.display = "block";
      toastEl.textContent = "正在向 TWSE / TAIFEX / FinMind 與全球行情新聞源同步最新數據，並逐筆寫回 SQLite 資料庫...";
      try {
        const res = await fetch("/api/admin/lobturtle/refresh", { method: "POST" }).then((r) => r.json());
        cachedStrategyOverview = null;
        await loadDbStatus();
        lobLoaded = false;
        forLoaded = false;
        retLoaded = false;
        btLoaded = false;
        turLoaded = false;
        stratLoaded = false;
        if (currentTab === "lobster") initLobsterTab(true);
        if (currentTab === "foreign") initForeignTab(true);
        if (currentTab === "retail") initRetailTab(true);
        if (currentTab === "backtest") initBacktestTab(true);
        if (currentTab === "turtle") initTurtleTab(true);
        if (currentTab === "strategy") initStrategyTab(true);

        if (res.totalInsertedRows > 0) {
          toastEl.textContent = `✅ 更新完成！已新增 ${res.totalInsertedRows} 筆新盤後數據寫回資料庫（最新日期：${res.latestDate}），並同步 ${res.globalMarketCount || 0} 項全球指標與 ${res.headlineCount || 0} 則即時新聞！`;
        } else {
          toastEl.textContent = `✅ 同步完成（${res.checkedAt || ""}）：9 大資料庫維持最新交易日 ${res.latestDate}，並已更新 ${res.globalMarketCount || 0} 項全球指標與 ${res.headlineCount || 0} 則國內外新聞！`;
        }
      } catch (err) {
        toastEl.textContent = `❌ 更新失敗：${err.message}`;
      } finally {
        setActionButtonBusy(refreshBtn, false);
      }
    });
  }

  // Global Floating Back-to-Top Arrow Button across all tabs/pages
  const backToTopBtn = document.getElementById("btn-back-to-top");
  function syncBackToTopVisibility() {
    if (!backToTopBtn) return;
    const scrolled = (window.scrollY || document.documentElement.scrollTop || 0) > 140;
    backToTopBtn.classList.toggle("visible", scrolled);
  }
  if (backToTopBtn) {
    window.addEventListener("scroll", syncBackToTopVisibility, { passive: true });
    backToTopBtn.addEventListener("click", () => {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    syncBackToTopVisibility();
  }

  loadDbStatus();
  initLobsterTab();
  updatePdfHref();
})();

/* Landosaur's 50-state land data atlas, charts, inventory, and county price explorer. */
(function () {
  "use strict";
  var root = document.getElementById("atlas-app");
  if (!root) return;
  var base = document.body.getAttribute("data-base") || "";

  function money(v) {
    if (v == null || isNaN(v)) return "–";
    return "$" + Math.round(v).toLocaleString("en-US");
  }
  function pct(v) {
    if (v == null || isNaN(v)) return "–";
    return (v > 0 ? "+" : "") + Number(v).toFixed(1) + "%";
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // Standard 11x8 geographic U.S. State Tile Grid [row, col]
  var GRID = {
    AK:[0,0], ME:[0,10],
    VT:[1,9], NH:[1,10],
    WA:[2,0], ID:[2,1], MT:[2,2], ND:[2,3], MN:[2,4], WI:[2,5], MI:[2,7], NY:[2,8], MA:[2,9], RI:[2,10],
    OR:[3,0], NV:[3,1], WY:[3,2], SD:[3,3], IA:[3,4], IL:[3,5], IN:[3,6], OH:[3,7], PA:[3,8], NJ:[3,9], CT:[3,10],
    CA:[4,0], UT:[4,1], CO:[4,2], NE:[4,3], MO:[4,4], KY:[4,5], WV:[4,6], VA:[4,7], MD:[4,8], DE:[4,9],
    AZ:[5,1], NM:[5,2], KS:[5,3], AR:[5,4], TN:[5,5], NC:[5,6], SC:[5,7],
    OK:[6,3], LA:[6,4], MS:[6,5], AL:[6,6], GA:[6,7],
    HI:[7,0], TX:[7,3], FL:[7,8]
  };

  fetch(base + "/data/atlas.json")
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (atlas) {
      initCartogram(atlas);
      initMultiStateChart(atlas);
      initMomentum(atlas);
      initRegions(atlas);
      initSupplyCharts(atlas);
      initCountyExplorer(atlas);
    })
    .catch(function () {
      const missing = document.createElement("p");
      missing.className = "callout";
      missing.textContent = "The Atlas data could not be loaded.";
      document.getElementById("main").appendChild(missing);
    });

  // ------------------------------------------------------- 1. 50-State Interactive U.S. Cartogram
  function initCartogram(atlas) {
    var box = document.getElementById("atlas-cartogram");
    var tip = document.getElementById("cartogram-readout");
    var btns = Array.prototype.slice.call(document.querySelectorAll("[data-carto-metric]"));
    if (!box) return;

    var byCode = {};
    atlas.states.forEach(function (s) { byCode[s.code] = s; });
    var metric = "fre";

    function colorScale(t) {
      t = Math.max(0, Math.min(1, t));
      var stops = [
        [233, 246, 236],
        [156, 224, 174],
        [63, 176, 108],
        [22, 101, 52],
        [12, 62, 34]
      ];
      var p = t * (stops.length - 1);
      var i = Math.min(stops.length - 2, Math.floor(p));
      var f = p - i;
      var c = stops[i].map(function (v, k) { return Math.round(v + (stops[i + 1][k] - v) * f); });
      return { bg: "rgb(" + c.join(",") + ")", fg: t > 0.52 ? "#ffffff" : "#0f261b" };
    }

    function metricVal(s) {
      if (metric === "fre") return s.fre || s.county_median;
      if (metric === "chg16") return s.chg_all;
      if (metric === "chg5") return s.chg_5yr;
      return s.active;
    }

    function metricFmt(s) {
      var v = metricVal(s);
      if (v == null) return "–";
      if (metric === "fre") return v >= 1000 ? ("$" + (v / 1000).toFixed(1) + "k") : money(v);
      if (metric === "chg16" || metric === "chg5") return pct(v);
      return v >= 1000 ? ((v / 1000).toFixed(1) + "k") : String(v);
    }

    function render() {
      var vals = atlas.states.map(metricVal).filter(function (v) { return v != null && isFinite(v); });
      var minV = Math.min.apply(null, vals);
      var maxV = Math.max.apply(null, vals);
      if (metric === "active") {
        minV = Math.log10(Math.max(1, minV));
        maxV = Math.log10(Math.max(2, maxV));
      }
      box.innerHTML = "";
      Object.keys(GRID).forEach(function (code) {
        var s = byCode[code];
        if (!s) return;
        var pos = GRID[code];
        var v = metricVal(s);
        var norm = 0.15;
        if (v != null && maxV > minV) {
          var vv = metric === "active" ? Math.log10(Math.max(1, v)) : v;
          norm = (vv - minV) / (maxV - minV);
        }
        var col = v == null ? { bg: "var(--surface-2)", fg: "var(--muted)" } : colorScale(norm);
        var a = document.createElement("a");
        a.className = "us-tile";
        a.href = base + (metric === "active" ? s.browse_path : s.price_path);
        a.style.gridRow = String(pos[0] + 1);
        a.style.gridColumn = String(pos[1] + 1);
        a.style.background = col.bg;
        a.style.color = col.fg;
        a.innerHTML = "<strong>" + code + "</strong><span>" + esc(metricFmt(s)) + "</span>";
        a.addEventListener("mouseenter", function () {
          if (!tip) return;
          tip.innerHTML =
            "<strong>" + esc(s.name) + " (" + code + ")</strong> · " +
            "2026 Avg: <strong>" + money(s.fre || s.county_median) + "/ac</strong>" +
            (s.chg_all != null ? (" · 2010–" + atlas.latest_year + ": <strong>" + pct(s.chg_all) + "</strong>") : "") +
            (s.chg_5yr != null ? (" · 5-Yr: <strong>" + pct(s.chg_5yr) + "</strong>") : "") +
            " · Live Parcels: <strong>" + s.active.toLocaleString("en-US") + "</strong>" +
            " · <a href='" + base + s.browse_path + "'>Browse Land →</a> · <a href='" + base + s.price_path + "'>Full State Data →</a>";
        });
        box.appendChild(a);
      });
    }

    btns.forEach(function (b) {
      b.addEventListener("click", function () {
        metric = b.getAttribute("data-carto-metric");
        btns.forEach(function (x) { x.classList.toggle("active", x === b); });
        render();
      });
    });
    render();
  }

  // ------------------------------------------------------- 2. Multi-State 2010–2026 Interactive Comparison Chart
  function initMultiStateChart(atlas) {
    var svgBox = document.getElementById("atlas-compare-chart");
    var statBox = document.getElementById("atlas-compare-stats");
    var selEls = [
      document.getElementById("cmp-st-1"),
      document.getElementById("cmp-st-2"),
      document.getElementById("cmp-st-3"),
      document.getElementById("cmp-st-4")
    ].filter(Boolean);
    var metricSel = document.getElementById("cmp-metric");
    var scaleSel = document.getElementById("cmp-scale");
    if (!svgBox || !selEls.length) return;

    var PALETTE = ["#16a34a", "#f59e0b", "#38bdf8", "#e879f9"];
    var optionsHtml = "<option value=''>None</option><option value='US'>U.S. National Average</option>" +
      atlas.states
        .filter(function (s) { return atlas.series[s.code]; })
        .map(function (s) { return "<option value='" + s.code + "'>" + esc(s.name) + "</option>"; })
        .join("");

    var defaults = ["US", "TX", "MT", "FL"];
    selEls.forEach(function (sel, idx) {
      sel.innerHTML = optionsHtml;
      sel.value = defaults[idx] || "";
      sel.addEventListener("change", draw);
    });
    if (metricSel) metricSel.addEventListener("change", draw);
    if (scaleSel) scaleSel.addEventListener("change", draw);

    function draw() {
      var mKey = metricSel ? metricSel.value : "farm_real_estate";
      var indexed = scaleSel && scaleSel.value === "index";
      var real = scaleSel && scaleSel.value === "real";
      var cpi = atlas.inflation;
      var inflationNote = document.getElementById("atlas-inflation-note");
      if (inflationNote) {
        inflationNote.textContent = "";
        if (real && cpi) {
          const lastMonth = new Intl.DateTimeFormat("en", { month: "long", timeZone: "UTC" })
            .format(new Date(Date.UTC(cpi.reference_year, cpi.reference_month - 1, 1)));
          const reference = cpi.years[cpi.reference_year];
          inflationNote.append(cpi.reference_year + " dollars using the " +
            (reference.months === 12 ? "annual CPI-U average" : "CPI-U average through " + lastMonth) +
            ". Years with missing observations use the months BLS published. ");
          const source = document.createElement("a");
          source.href = cpi.source;
          source.textContent = "BLS CPI-U via FRED";
          inflationNote.append(source);
        }
      }
      var years = atlas.years;
      var activeSeries = [];
      selEls.forEach(function (sel, idx) {
        var code = sel.value;
        if (!code || !atlas.series[code]) return;
        var raw = atlas.series[code][mKey] || [];
        var pts = [];
        var baseVal = null;
        for (var i = 0; i < years.length; i++) {
          var v = raw[i];
          if (v != null && v > 0) {
            if (baseVal == null) baseVal = v;
            const factor = real ? cpi?.years[cpi.reference_year]?.mean / cpi?.years[years[i]]?.mean : 1;
            if (!Number.isFinite(factor)) continue;
            pts.push({ y: years[i], v: indexed ? (v / baseVal) * 100 : v * factor, raw: v * factor });
          }
        }
        if (pts.length >= 2) {
          var label = code === "US" ? "U.S. Average" : ((atlas.states.find(function (x) { return x.code === code; }) || {}).name || code);
          activeSeries.push({ code: code, label: label, color: PALETTE[idx % PALETTE.length], pts: pts });
        }
      });

      if (!activeSeries.length) {
        svgBox.innerHTML = "<p class='small'>Select at least one geography with published USDA data for this metric.</p>";
        if (statBox) statBox.innerHTML = "";
        return;
      }

      var allVals = [];
      activeSeries.forEach(function (s) { s.pts.forEach(function (p) { allVals.push(p.v); }); });
      var yMin = indexed ? Math.min(90, Math.min.apply(null, allVals)) : 0;
      var yMax = Math.max.apply(null, allVals) * 1.08;
      var W = Math.max(320, Math.min(820, svgBox.clientWidth));
      var H = W < 500 ? 228 : 310, padL = 63, padR = 20, padT = 20, padB = 34;
      var pw = W - padL - padR, ph = H - padT - padB;
      var y0 = years[0], yN = years[years.length - 1];
      function xPos(yr) { return padL + ((yr - y0) / Math.max(1, yN - y0)) * pw; }
      function yPos(v) { return padT + ph - ((v - yMin) / Math.max(1, yMax - yMin)) * ph; }

      var grid = "";
      for (var t = 0; t <= 4; t++) {
        var gv = yMin + ((yMax - yMin) * t) / 4;
        var gy = yPos(gv).toFixed(1);
        var lbl = indexed ? Math.round(gv) : ("$" + Math.round(gv).toLocaleString("en-US"));
        grid += "<line x1='" + padL + "' y1='" + gy + "' x2='" + (W - padR) + "' y2='" + gy + "' stroke='currentColor' stroke-opacity='0.14' stroke-dasharray='3 4'/>";
        grid += "<text x='" + (padL - 8) + "' y='" + (Number(gy) + 4) + "' text-anchor='end' font-size='11' fill='currentColor' fill-opacity='0.72'>" + lbl + "</text>";
      }
      for (var yi = 0; yi < years.length; yi += W < 500 ? 4 : 2) {
        var yr = years[yi];
        grid += "<text x='" + xPos(yr).toFixed(1) + "' y='" + (H - 10) + "' text-anchor='middle' font-size='11' fill='currentColor' fill-opacity='0.72'>" + yr + "</text>";
      }

      var paths = "";
      activeSeries.forEach(function (s) {
        var d = s.pts.map(function (p, i) { return (i ? "L" : "M") + xPos(p.y).toFixed(1) + "," + yPos(p.v).toFixed(1); }).join(" ");
        paths += "<path d='" + d + "' fill='none' stroke='" + s.color + "' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/>";
        var last = s.pts[s.pts.length - 1];
        paths += "<circle cx='" + xPos(last.y).toFixed(1) + "' cy='" + yPos(last.v).toFixed(1) + "' r='4.5' fill='" + s.color + "'/>";
      });

      svgBox.innerHTML =
        "<svg viewBox='0 0 " + W + " " + H + "' style='width:100%;height:auto;display:block' role='img' aria-label='Multi-state land price comparison chart'>" +
        grid + paths + "</svg>";

      if (statBox) {
        statBox.innerHTML = activeSeries.map(function (s) {
          var first = s.pts[0], last = s.pts[s.pts.length - 1];
          var totalChg = ((last.raw / first.raw) - 1) * 100;
          var span = Math.max(1, last.y - first.y);
          var cagr = (Math.pow(last.raw / first.raw, 1 / span) - 1) * 100;
          return "<div class='kpi-card' style='border-top:3px solid " + s.color + "'>" +
            "<span>" + esc(s.label) + " (" + last.y + ")</span>" +
            "<strong>" + money(last.raw) + "/ac</strong>" +
            "<small>" + first.y + "–" + last.y + ": " + pct(totalChg) + " · CAGR " + pct(cagr) + "/yr</small></div>";
        }).join("");
      }
    }
    draw();
    if (window.ResizeObserver) {
      let width = svgBox.clientWidth;
      new ResizeObserver(() => {
        if (svgBox.clientWidth === width) return;
        width = svgBox.clientWidth;
        draw();
      }).observe(svgBox);
    }
  }

  function initMomentum(atlas) {
    const box = document.getElementById("atlas-scatter");
    if (!box) return;
    const note = document.getElementById("atlas-scatter-note");
    const available = atlas.states.filter((state) => state.fre > 0 && Number.isFinite(state.chg_all));
    if (!available.length) return;
    const xValues = available.map((state) => Math.log10(state.fre));
    const yValues = available.map((state) => state.chg_all);
    const mid = (values) => values.slice().sort((a, b) => a - b)[Math.floor(values.length / 2)];
    const logLow = Math.min(...xValues) - .03, logHigh = Math.max(...xValues) + .03;
    const yLow = Math.floor((Math.min(0, ...yValues) - 4) / 20) * 20;
    const yHigh = Math.ceil((Math.max(...yValues) + 4) / 20) * 20;
    const x = (value) => 47 + ((Math.log10(value) - logLow) / (logHigh - logLow)) * 302;
    const y = (value) => 193 - ((value - yLow) / (yHigh - yLow)) * 166;
    const lines = [
      `<path d="M47 26V193H349" fill="none" stroke="currentColor" opacity=".42"/>`,
      `<path d="M${x(10 ** mid(xValues))} 26V193 M47 ${y(mid(yValues))}H349" fill="none" stroke="currentColor" opacity=".35" stroke-dasharray="4 3"/>`,
    ];
    for (const mark of [500, 1000, 2000, 5000, 10000, 20000, 50000]) {
      if (x(mark) < 47 || x(mark) > 349) continue;
      lines.push(`<text x="${x(mark)}" y="206" text-anchor="middle">${money(mark)}</text>`);
    }
    for (let i = 0; i <= 4; i++) {
      const mark = yLow + ((yHigh - yLow) / 4) * i;
      lines.push(`<text x="41" y="${y(mark) + 3}" text-anchor="end">${Math.round(mark)}%</text>`);
    }
    const peak = Math.max(1, ...available.map((state) => state.active));
    const detail = (state) => state.name + " · " + money(state.fre) + "/acre · " +
      pct(state.chg_all) + " nominal appreciation · " + state.active.toLocaleString() + " active parcels";
    const points = available.slice().sort((a, b) => b.active - a.active).map((state) => {
      const radius = Math.sqrt(11 + 135 * state.active / peak);
      return `<a href="${base + state.price_path}" data-state-point="${state.code}" aria-label="${esc(detail(state))}">` +
        `<circle cx="${x(state.fre)}" cy="${y(state.chg_all)}" r="${radius}"><title>${esc(detail(state))}</title></circle></a>`;
    });
    box.innerHTML = '<svg class="atlas-scatter-svg" viewBox="0 0 365 231" aria-label="State price and appreciation scatter plot">' +
      '<text x="48" y="14">Nominal appreciation</text>' + lines.join("") + points.join("") +
      '<text x="200" y="224" text-anchor="middle">USD per acre (log scale)</text></svg>';
    note.textContent = available.length + " states with published price and history. Lines show the median of those states.";
    box.querySelectorAll("[data-state-point]").forEach((point) => {
      const state = available.find((item) => item.code === point.dataset.statePoint);
      const show = () => { note.textContent = detail(state); };
      point.addEventListener("focus", show);
      point.addEventListener("pointerenter", show);
    });
  }

  function initRegions(atlas) {
    const box = document.getElementById("atlas-regions");
    if (!box || !atlas.regions?.length) return;
    const maximum = Math.max(1, ...atlas.regions.map((region) => region.farm_real_estate || 0));
    box.innerHTML = atlas.regions.map((region) => {
      const width = (region.farm_real_estate || 0) / maximum * 100;
      return '<div class="atlas-region-row"><strong>' + esc(region.name) + '</strong><div class="bench-track">' +
        '<div class="bench-fill" style="width:' + width.toFixed(2) + '%"></div></div><strong>' +
        money(region.farm_real_estate) + '/ac</strong><small>' + pct(region.five_year_cagr_pct) +
        ' 5-year annualized growth · ' + region.active.toLocaleString() + ' active parcels · ' +
        region.reporting_states + '/' + region.total_states + ' states reporting</small></div>';
    }).join("");
  }

  // ------------------------------------------------------- 3. Live 50-State Supply & Discount Analytics
  function initSupplyCharts(atlas) {
    var topBox = document.getElementById("atlas-top-states");
    var acreBox = document.getElementById("atlas-acre-tiers");
    var modeBox = document.getElementById("atlas-mode-split");
    var discBox = document.getElementById("atlas-discount-table");

    if (modeBox && atlas.supply) {
      var tot = Math.max(1, atlas.supply.total_active);
      var rows = [
        { lbl: "Buy It Now (Fixed Price)", n: atlas.supply.buy_now, color: "#16a34a" },
        { lbl: "Auction / Tax-Sale / Min Bid", n: atlas.supply.auction, color: "#d97706" },
        { lbl: "Land Bank / Surplus / Offer", n: atlas.supply.offer, color: "#0d9488" },
      ];
      modeBox.innerHTML = rows.map(function (r) {
        var w = Math.max(2, (r.n / tot) * 100);
        return "<div class='bench-gauge-row'><strong>" + esc(r.lbl) + "</strong>" +
          "<div class='bench-track'><div class='bench-fill' style='width:" + w.toFixed(1) + "%;background:" + r.color + "'></div></div>" +
          "<span class='card-metric'>" + r.n.toLocaleString("en-US") + " (" + (r.n / tot * 100).toFixed(1) + "%)</span></div>";
      }).join("");
    }

    if (topBox) {
      var top = atlas.states.slice().sort(function (a, b) { return b.active - a.active; }).slice(0, 18);
      var mx = Math.max(1, top[0].active);
      topBox.innerHTML = top.map(function (s) {
        var w = Math.max(3, (s.active / mx) * 100);
        return "<div class='bench-gauge-row'><a href='" + base + s.browse_path + "'><strong>" + esc(s.name) + "</strong></a>" +
          "<div class='bench-track'><div class='bench-fill' style='width:" + w.toFixed(1) + "%'></div></div>" +
          "<span class='card-metric'>" + s.active.toLocaleString("en-US") + " parcels</span></div>";
      }).join("");
    }

    if (acreBox && atlas.supply && atlas.supply.acre_tiers) {
      var mxA = Math.max.apply(null, atlas.supply.acre_tiers.map(function (t) { return t.count; })) || 1;
      acreBox.innerHTML = atlas.supply.acre_tiers.map(function (t) {
        var w = Math.max(2, (t.count / mxA) * 100);
        return "<div class='bench-gauge-row'><strong>" + esc(t.label) + "</strong>" +
          "<div class='bench-track'><div class='bench-fill' style='width:" + w.toFixed(1) + "%'></div></div>" +
          "<span class='card-metric'>" + t.count.toLocaleString("en-US") + "</span></div>";
      }).join("");
    }

    if (discBox && atlas.priced_states) {
      discBox.innerHTML =
        "<div class='scroll'><table class='data'><thead><tr><th>State</th><th class='n'>Priced Parcels</th><th class='n'>Lowest Price / Bid</th><th class='n'>Listing Median $/ac</th><th class='n'>USDA State Avg $/ac</th><th>Explore</th></tr></thead><tbody>" +
        atlas.priced_states.map(function (s) {
          return "<tr><td><strong>" + esc(s.name) + "</strong></td>" +
            "<td class='n'>" + s.priced_count.toLocaleString("en-US") + "</td>" +
            "<td class='n'>" + money(s.min_price) + "</td>" +
            "<td class='n'>" + (s.median_ppa ? (money(s.median_ppa) + "/ac") : "–") + "</td>" +
            "<td class='n'>" + (s.usda_fre ? (money(s.usda_fre) + "/ac") : "–") + "</td>" +
            "<td><a href='" + base + s.browse_path + "'>View parcels →</a></td></tr>";
        }).join("") +
        "</tbody></table></div>";
    }
  }

  // County land value explorer
  function initCountyExplorer(atlas) {
    var stSel = document.getElementById("county-st-filter");
    var qIn = document.getElementById("county-q-filter");
    var sortSel = document.getElementById("county-sort");
    var tbody = document.getElementById("county-explorer-body");
    var countEl = document.getElementById("county-explorer-count");
    var csvBtn = document.getElementById("county-export-csv");
    if (!tbody || !atlas.counties) return;

    if (stSel) {
      stSel.innerHTML = "<option value=''>All 50 states (" + atlas.counties.length.toLocaleString("en-US") + " counties and equivalents)</option>" +
        atlas.states.map(function (s) { return "<option value='" + s.code + "'>" + esc(s.name) + "</option>"; }).join("");
    }

    var stateFre = {};
    atlas.states.forEach(function (s) { stateFre[s.code] = s.fre || s.county_median; });
    var lastRows = [];

    function render() {
      var st = stSel ? stSel.value : "";
      var q = qIn ? qIn.value.trim().toLowerCase() : "";
      var sort = sortSel ? sortSel.value : "val_asc";
      var rows = atlas.counties.filter(function (c) {
        if (st && c[2] !== st) return false;
        if (q && (c[1] + " " + c[2] + " " + c[3]).toLowerCase().indexOf(q) < 0) return false;
        return true;
      });
      rows.sort(function (a, b) {
        if (sort === "val_desc") return (b[4] || -1) - (a[4] || -1);
        if (sort === "name_asc") return a[1] < b[1] ? -1 : 1;
        return (a[4] == null ? 1e12 : a[4]) - (b[4] == null ? 1e12 : b[4]);
      });
      lastRows = rows;
      if (countEl) countEl.textContent = "Showing top " + Math.min(100, rows.length) + " of " + rows.length.toLocaleString("en-US") + " U.S. counties.";
      tbody.innerHTML = rows.slice(0, 100).map(function (c) {
        var stAvg = stateFre[c[2]];
        var vs = (c[4] && stAvg) ? pct(((c[4] / stAvg) - 1) * 100) : "–";
        var svcHref = base + "/services/?service=unlisted_outreach&county=" + encodeURIComponent(c[1]) + "&state=" + encodeURIComponent(c[2]);
        return "<tr><td><strong>" + esc(c[1]) + "</strong></td><td>" + esc(c[2]) + "</td>" +
          "<td class='n'><strong>" + (c[4] ? (money(c[4]) + "/ac") : "Not reported") + "</strong></td>" +
          "<td class='n'>" + esc(vs) + "</td>" +
          "<td><a href='" + base + "/land-prices/" + encodeURIComponent(c[3]) + "/'>State Data</a> · <a href='" + svcHref + "'>Acquire Off-Market ($20) →</a></td></tr>";
      }).join("");
    }

    if (stSel) stSel.addEventListener("change", render);
    if (qIn) qIn.addEventListener("input", render);
    if (sortSel) sortSel.addEventListener("change", render);
    if (csvBtn) {
      csvBtn.addEventListener("click", function () {
        var header = "fips,county,state,usd_per_acre_2026\n";
        var lines = lastRows.map(function (c) {
          return '"' + c[0] + '","' + c[1].replace(/"/g, '""') + '","' + c[2] + '",' + (c[4] == null ? "" : c[4]);
        });
        var blob = new Blob([header + lines.join("\n") + "\n"], { type: "text/csv;charset=utf-8" });
        var u = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = u; a.download = "landosaur-us-counties-land-values.csv";
        document.body.appendChild(a); a.click();
        setTimeout(function () { URL.revokeObjectURL(u); a.remove(); }, 400);
      });
    }
    render();
  }
})();

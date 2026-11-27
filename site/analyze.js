/* Landosaur Land Deal, Financing, Electricity & Valuation Workbench (/analyze/).
 * Deterministic planning calculations ported from original/src/lib/analysis.ts.
 * Runs 100% in the browser; never submits user inputs or invents estimates. */
(function () {
  "use strict";
  var root = document.getElementById("analyzer-app");
  if (!root) return;

  function num(v) {
    if (v === "" || v == null) return 0;
    var n = parseFloat(v);
    return isFinite(n) && n >= 0 ? n : 0;
  }
  function rawNum(v) {
    if (v === "" || v == null) return NaN;
    var n = parseFloat(v);
    return isFinite(n) ? n : NaN;
  }
  function money(v) {
    if (v == null || !isFinite(v)) return "–";
    var neg = v < 0 ? "-" : "";
    var a = Math.abs(v);
    return neg + "$" + (Math.abs(a - Math.round(a)) < 0.005
      ? Math.round(a).toLocaleString("en-US")
      : a.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  }
  function pct(v) {
    if (v == null || !isFinite(v)) return "–";
    return (v > 0 ? "+" : "") + v.toFixed(1) + "%";
  }

  // Tabs
  var tabs = Array.prototype.slice.call(root.querySelectorAll("[role=tab]"));
  var panels = Array.prototype.slice.call(root.querySelectorAll("[role=tabpanel]"));
  function activateTab(id) {
    tabs.forEach(function (t) {
      var on = t.getAttribute("aria-controls") === id;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
    });
    panels.forEach(function (p) {
      p.hidden = p.id !== id;
    });
  }
  tabs.forEach(function (t) {
    t.addEventListener("click", function () { activateTab(t.getAttribute("aria-controls")); });
  });

  // --- 1. All-in Cost & Financing ---
  var fCost = document.getElementById("form-cost");
  function calcFinancing(principal, annualRatePct, amortMonths, balloonMonths, holdMonths) {
    if (principal <= 0 || amortMonths < 1) {
      return { monthly: 0, interest: 0, principalPaid: 0, balloon: 0, exitPayoff: 0, totalCash: 0, balloonDue: false };
    }
    var r = annualRatePct / 1200;
    var monthly = r === 0 ? principal / amortMonths : (principal * r) / (1 - Math.pow(1 + r, -amortMonths));
    var cap = Math.min(holdMonths, balloonMonths > 0 ? balloonMonths : amortMonths, amortMonths);
    var bal = principal, interest = 0, pPaid = 0, sched = 0;
    for (var m = 0; m < cap; m++) {
      var intr = bal * r;
      var prin = m === amortMonths - 1 ? bal : Math.min(bal, Math.max(0, monthly - intr));
      bal = Math.max(0, bal - prin);
      interest += intr;
      pPaid += prin;
      sched += prin + intr;
    }
    var balloonDue = balloonMonths > 0 && balloonMonths <= holdMonths && principal > 0;
    var balloon = balloonDue ? bal : 0;
    return {
      monthly: monthly,
      interest: interest,
      principalPaid: pPaid,
      balloon: balloon,
      exitPayoff: balloonDue ? 0 : bal,
      totalCash: sched + balloon,
      balloonDue: balloonDue,
    };
  }

  var lastCostState = { unlevered: 0, cashRequired: 0, econ: 0, exitPayoff: 0, holdMonths: 12 };

  function updateCost() {
    if (!fCost) return;
    var price = num(fCost.price.value);
    var acres = num(fCost.acres.value);
    var closingPct = Math.min(100, num(fCost.closingPct.value));
    var diligence = num(fCost.diligence.value);
    var roadFt = num(fCost.roadFt.value);
    var roadRate = num(fCost.roadRate.value);
    var utilities = num(fCost.utilities.value);
    var siteWork = num(fCost.siteWork.value);
    var contingencyPct = Math.min(100, num(fCost.contingencyPct.value));
    var annualTax = num(fCost.annualTax.value);
    var monthlyOther = num(fCost.monthlyOther.value);
    var holdMonths = Math.min(600, Math.round(num(fCost.holdMonths.value)));
    var sellPct = Math.min(99.9, num(fCost.sellPct.value));

    var closing = price * closingPct / 100;
    var road = roadFt * roadRate;
    var works = road + utilities + siteWork;
    var contingency = works * contingencyPct / 100;
    var holding = (annualTax * holdMonths / 12) + (monthlyOther * holdMonths);
    var unlevered = price + closing + diligence + works + holding + contingency;

    var useFin = fCost.useFin && fCost.useFin.checked;
    var finBox = document.getElementById("fin-fields");
    if (finBox) finBox.hidden = !useFin;

    var principal = 0, origFee = 0, fin = null;
    if (useFin && price > 0) {
      var down = Math.min(price, num(fCost.downPayment.value));
      principal = Math.max(0, price - down);
      var rate = Math.min(100, num(fCost.apr.value));
      var amort = Math.max(1, Math.min(600, Math.round(num(fCost.amortMonths.value) || 120)));
      var balloonM = Math.round(num(fCost.balloonMonths.value));
      origFee = principal * Math.min(100, num(fCost.origPct.value)) / 100;
      fin = calcFinancing(principal, rate, amort, balloonM > 0 ? balloonM : 0, holdMonths);
    }
    var financeCost = (fin ? fin.interest : 0) + origFee;
    var cashRequired = unlevered - principal + (fin ? fin.totalCash : 0) + origFee;
    var econ = unlevered + financeCost;
    var breakEven = econ > 0 ? econ / (1 - sellPct / 100) : 0;

    lastCostState = {
      unlevered: unlevered,
      cashRequired: cashRequired,
      econ: econ,
      exitPayoff: fin ? fin.exitPayoff : 0,
      holdMonths: holdMonths,
    };

    function setT(id, val) { var e = document.getElementById(id); if (e) e.textContent = val; }
    setT("out-closing", money(closing));
    setT("out-works", money(works + contingency));
    setT("out-holding", money(holding));
    setT("out-unlevered", price > 0 || works > 0 ? money(unlevered) : "–");
    setT("out-monthly", fin ? money(fin.monthly) + "/mo" : "Cash purchase");
    setT("out-balloon", fin && fin.balloonDue ? money(fin.balloon) + " due in hold" : (fin ? money(fin.exitPayoff) + " balance at exit" : "–"));
    setT("out-cash-req", price > 0 || works > 0 ? money(cashRequired) : "–");
    setT("out-econ", price > 0 || works > 0 ? money(econ) : "–");
    setT("out-ppa", acres > 0 && econ > 0 ? money(econ / acres) + " / acre" : "Enter acres & price");
    setT("out-breakeven", econ > 0 ? money(breakEven) : "–");
    updateGates();
  }
  if (fCost) fCost.addEventListener("input", updateCost);

  // --- 2. Power & Electricity Feasibility (Grid vs Off-Grid) ---
  var fPower = document.getElementById("form-power");
  function updatePower() {
    if (!fPower) return;
    var years = Math.max(1, num(fPower.horizonYears.value) || 10);
    var distFt = num(fPower.distFt.value);
    var perFt = num(fPower.perFt.value);
    var xfmr = num(fPower.transformer.value);
    var ease = num(fPower.easement.value);
    var baseMo = num(fPower.baseCharge.value);
    var kwhMo = num(fPower.kwhMonth.value);
    var kwhRate = num(fPower.kwhRate.value);

    var gridCapex = distFt * perFt + xfmr + ease;
    var gridOp = (baseMo + kwhMo * kwhRate) * 12 * years;
    var gridTotal = gridCapex + gridOp;

    var solarCapex = num(fPower.solarArray.value) + num(fPower.battery.value) + num(fPower.generator.value);
    var batReplace = num(fPower.batteryReplace.value);
    var offOp = (num(fPower.fuelAnnual.value) + num(fPower.maintAnnual.value)) * years + batReplace;
    var offTotal = solarCapex + offOp;

    function setT(id, val) { var e = document.getElementById(id); if (e) e.textContent = val; }
    setT("pwr-grid-capex", gridCapex > 0 ? money(gridCapex) : "–");
    setT("pwr-grid-total", gridTotal > 0 ? money(gridTotal) : "–");
    setT("pwr-grid-yr", gridTotal > 0 ? money(gridTotal / years) + "/yr" : "–");
    setT("pwr-off-capex", solarCapex > 0 ? money(solarCapex) : "–");
    setT("pwr-off-total", offTotal > 0 ? money(offTotal) : "–");
    setT("pwr-off-yr", offTotal > 0 ? money(offTotal / years) + "/yr" : "–");

    var note = document.getElementById("pwr-verdict");
    if (note) {
      if (gridTotal <= 0 || offTotal <= 0) {
        note.textContent = "Enter both utility extension quotes and off-grid system quotes to compare paths. Unknown material inputs prevent a definitive cheapest label.";
      } else {
        var diff = Math.abs(gridTotal - offTotal);
        var lower = gridTotal < offTotal ? "Utility grid extension" : "Off-grid solar + battery + generator";
        note.textContent = lower + " is lower by " + money(diff) + " over " + years + " years based strictly on your entered figures. Confirm line-extension tariffs, easement rights, and inverter/battery warranties before committing.";
      }
    }
  }
  if (fPower) fPower.addEventListener("input", updatePower);

  // --- 3. Comparable Closed-Sales Envelope ---
  var compList = document.getElementById("comp-rows");
  var addCompBtn = document.getElementById("add-comp");
  var compAcresIn = document.getElementById("comp-subject-acres");

  function makeCompRow(prefill) {
    var tr = document.createElement("tr");
    tr.innerHTML =
      '<td><input type="url" name="url" placeholder="https://county-recorder..." value="' + (prefill.url || "") + '"></td>' +
      '<td><input type="number" name="price" min="0" step="any" placeholder="Closed $" value="' + (prefill.price || "") + '"></td>' +
      '<td><input type="number" name="acres" min="0" step="any" placeholder="Acres" value="' + (prefill.acres || "") + '"></td>' +
      '<td><input type="date" name="date" value="' + (prefill.date || "") + '"></td>' +
      '<td><input type="number" name="adj" min="-50" max="50" step="1" value="' + (prefill.adj || "0") + '"></td>' +
      '<td><input type="text" name="reason" placeholder="Reason if adjusted" value="' + (prefill.reason || "") + '"></td>' +
      '<td><label class="inline-chk"><input type="checkbox" name="verified"> Verified closed</label></td>' +
      '<td><button type="button" class="button ghost sm rm-comp" aria-label="Remove comparable">×</button></td>';
    tr.querySelector(".rm-comp").addEventListener("click", function () { tr.remove(); updateComps(); });
    tr.addEventListener("input", updateComps);
    tr.addEventListener("change", updateComps);
    return tr;
  }

  function updateComps() {
    if (!compList) return;
    var subj = rawNum(compAcresIn && compAcresIn.value);
    var accepted = [], issues = [];
    Array.prototype.forEach.call(compList.querySelectorAll("tr"), function (tr, idx) {
      var u = tr.querySelector("[name=url]").value.trim();
      var p = rawNum(tr.querySelector("[name=price]").value);
      var a = rawNum(tr.querySelector("[name=acres]").value);
      var d = tr.querySelector("[name=date]").value.trim();
      var adj = rawNum(tr.querySelector("[name=adj]").value) || 0;
      var reason = tr.querySelector("[name=reason]").value.trim();
      var ver = tr.querySelector("[name=verified]").checked;
      if (!u && isNaN(p) && isNaN(a)) return; // empty row
      var errs = [];
      if (!/^https?:\/\/[^ ]+/.test(u)) errs.push("public source URL required");
      if (!(p > 0)) errs.push("positive closed price required");
      if (!(a > 0)) errs.push("positive acres required");
      else if (subj > 0 && (a / subj < 0.5 || a / subj > 2.0)) errs.push("acres outside 0.5×–2× subject band");
      if (!d) errs.push("sale date required");
      if (!ver) errs.push("mark Verified closed after checking deed/source");
      if (adj < -50 || adj > 50) errs.push("adjustment must be -50% to +50%");
      if (adj !== 0 && !reason) errs.push("explain nonzero adjustment");
      if (errs.length) issues.push("Row " + (idx + 1) + ": " + errs.join("; "));
      else accepted.push({ price: p * (1 + adj / 100), ppa: (p * (1 + adj / 100)) / a });
    });

    var outEl = document.getElementById("comp-summary");
    if (!outEl) return;
    if (accepted.length >= 3) {
      var ps = accepted.map(function (c) { return c.price; }).sort(function (a, b) { return a - b; });
      var ppas = accepted.map(function (c) { return c.ppa; }).sort(function (a, b) { return a - b; });
      var mid = Math.floor(ps.length / 2);
      var medP = ps.length % 2 ? ps[mid] : (ps[mid - 1] + ps[mid]) / 2;
      var medPpa = ppas.length % 2 ? ppas[mid] : (ppas[mid - 1] + ppas[mid]) / 2;
      outEl.innerHTML =
        '<div class="kpi-grid">' +
        '<div class="kpi-card"><span>Eligible Comps</span><strong>' + accepted.length + '</strong><small>Verified closed sales</small></div>' +
        '<div class="kpi-card"><span>Adjusted Low</span><strong>' + money(ps[0]) + '</strong><small>' + money(ppas[0]) + '/acre</small></div>' +
        '<div class="kpi-card"><span>Adjusted Median</span><strong>' + money(medP) + '</strong><small>' + money(medPpa) + '/acre</small></div>' +
        '<div class="kpi-card"><span>Adjusted High</span><strong>' + money(ps[ps.length - 1]) + '</strong><small>' + money(ppas[ppas.length - 1]) + '/acre</small></div>' +
        '</div><p class="small">Range is the min–max of your reviewed closed sales, not a statistical confidence interval or appraisal.</p>';
    } else {
      outEl.innerHTML = '<p class="callout"><strong>' + accepted.length + ' of 3</strong> eligible verified closed sales entered. Add at least three verified closed sales within 0.5×–2× subject acreage to display a comparison envelope.' +
        (issues.length ? '<br><span class="small">Needs attention: ' + issues.join(" · ") + '</span>' : '') + '</p>';
    }
  }
  if (compList) {
    for (var k = 0; k < 3; k++) compList.appendChild(makeCompRow({}));
    if (addCompBtn) addCompBtn.addEventListener("click", function () { compList.appendChild(makeCompRow({})); });
    if (compAcresIn) compAcresIn.addEventListener("input", updateComps);
  }

  // --- 4. 6-Gate Opportunity, Income & Residual ---
  var fGates = document.getElementById("form-gates");
  function updateGates() {
    if (!fGates) return;
    var exitVal = num(fGates.exitValue.value);
    var sellPct = Math.min(99.9, num(fGates.exitSellPct.value));
    var discPct = Math.min(100, num(fGates.discountPct.value));
    var selects = Array.prototype.slice.call(fGates.querySelectorAll("select[data-gate]"));
    var failed = [], missing = [];
    selects.forEach(function (s) {
      if (s.value === "failed") failed.push(s.getAttribute("data-gate"));
      else if (s.value !== "verified") missing.push(s.getAttribute("data-gate"));
    });
    var netExit = exitVal * (1 - sellPct / 100);
    var unlev = lastCostState.unlevered;
    var holdYrs = (lastCostState.holdMonths || 12) / 12;
    var surplus = unlev > 0 ? netExit - unlev : NaN;
    var discSurplus = unlev > 0 ? (netExit / Math.pow(1 + discPct / 100, holdYrs)) - unlev : NaN;
    var eqSurplus = unlev > 0 ? netExit - lastCostState.exitPayoff - lastCostState.cashRequired : NaN;

    var status = failed.length ? "Critical issue to resolve"
      : missing.length ? "Evidence needed (" + missing.length + " gate" + (missing.length === 1 ? "" : "s") + " unverified)"
      : (isFinite(eqSurplus) && eqSurplus > 0 && discSurplus > 0) ? "Positive planning scenario"
      : (unlev > 0 && exitVal > 0 ? "Below cost / return threshold" : "Enter purchase & exit figures");

    function setT(id, val) { var e = document.getElementById(id); if (e) e.textContent = val; }
    setT("gate-status", status);
    setT("gate-net-exit", exitVal > 0 ? money(netExit) : "–");
    setT("gate-surplus", isFinite(surplus) && exitVal > 0 ? money(surplus) + " (" + pct(surplus / unlev * 100) + ")" : "–");
    setT("gate-npv", isFinite(discSurplus) && exitVal > 0 ? money(discSurplus) : "–");
  }
  if (fGates) {
    fGates.addEventListener("input", updateGates);
    fGates.addEventListener("change", updateGates);
  }

  var fIncome = document.getElementById("form-income");
  function updateIncome() {
    if (!fIncome) return;
    var gross = num(fIncome.grossRent.value);
    var vac = Math.min(100, num(fIncome.vacancyPct.value));
    var op = num(fIncome.opCost.value);
    var res = num(fIncome.reserve.value);
    var cap = num(fIncome.capRate.value);
    var noi = gross * (1 - vac / 100) - op - res;
    var val = noi > 0 && cap > 0 ? noi / (cap / 100) : NaN;
    var eNoi = document.getElementById("inc-noi");
    var eVal = document.getElementById("inc-val");
    if (eNoi) eNoi.textContent = gross > 0 ? money(noi) + "/yr" : "–";
    if (eVal) eVal.textContent = isFinite(val) ? money(val) : "–";
  }
  if (fIncome) fIncome.addEventListener("input", updateIncome);

  var fResid = document.getElementById("form-residual");
  function updateResidual() {
    if (!fResid) return;
    var units = Math.round(num(fResid.units.value));
    var ppu = num(fResid.pricePerUnit.value);
    var months = num(fResid.monthsToSale.value);
    var disc = num(fResid.resDiscount.value);
    var base = num(fResid.hard.value) + num(fResid.soft.value) + num(fResid.infra.value);
    var cont = base * Math.min(100, num(fResid.resCont.value)) / 100;
    var gross = units * ppu;
    var sell = gross * Math.min(100, num(fResid.resSell.value)) / 100;
    var prof = gross * Math.min(100, num(fResid.resProfit.value)) / 100;
    var discRec = (gross - sell - prof) / Math.pow(1 + disc / 100, months / 12);
    var budget = discRec - base - cont;
    var eG = document.getElementById("res-gross");
    var eB = document.getElementById("res-budget");
    if (eG) eG.textContent = gross > 0 ? money(gross) : "–";
    if (eB) eB.textContent = gross > 0 ? money(budget) : "–";
  }
  if (fResid) fResid.addEventListener("input", updateResidual);

  // Prefill from query string (?title=...&price=...&acres=...) or URL hash (#a=...)
  var params = new URLSearchParams(location.search);
  var parcelBanner = document.getElementById("analyzer-parcel-banner");
  if (params.get("title") && parcelBanner) {
    parcelBanner.hidden = false;
    var span = parcelBanner.querySelector("strong");
    if (span) span.textContent = params.get("title");
    var back = parcelBanner.querySelector("a");
    if (back && params.get("id")) back.href = (document.body.getAttribute("data-base") || "") + "/land/" + encodeURIComponent(params.get("id")) + "/";
    else if (back) back.hidden = true;
  }
  if (fCost) {
    if (params.get("price")) fCost.price.value = params.get("price");
    if (params.get("acres")) {
      fCost.acres.value = params.get("acres");
      if (compAcresIn) compAcresIn.value = params.get("acres");
    }
  }
  var hashMatch = location.hash.match(/a=([^&]+)/);
  if (hashMatch && fCost) {
    decodeURIComponent(hashMatch[1]).split(",").forEach(function (kv) {
      var p = kv.split(":");
      var el = fCost.elements[p[0]] || (fPower && fPower.elements[p[0]]);
      if (!el) return;
      if (el.type === "checkbox") el.checked = p[1] === "1";
      else if (p[1] != null) el.value = p[1];
    });
  }

  var copyBtn = document.getElementById("copy-analysis");
  if (copyBtn && fCost) {
    copyBtn.addEventListener("click", function () {
      var parts = [];
      [fCost, fPower].forEach(function (fm) {
        if (!fm) return;
        Array.prototype.forEach.call(fm.elements, function (e) {
          if (!e.name) return;
          if (e.type === "checkbox") { if (e.checked) parts.push(e.name + ":1"); }
          else if (e.value !== "") parts.push(e.name + ":" + e.value);
        });
      });
      var url = location.href.split("#")[0] + "#a=" + encodeURIComponent(parts.join(","));
      history.replaceState(null, "", url);
      if (navigator.clipboard) navigator.clipboard.writeText(url).then(function () { copyBtn.textContent = "Analysis link copied"; });
      else copyBtn.textContent = "Link updated in address bar";
    });
  }

  updateCost();
  updatePower();
  updateComps();
  updateIncome();
  updateResidual();
})();

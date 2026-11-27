/* Landosaur /services/ — $20 + 10% Land Agent Acquisition Concierge (Listed & Unlisted/Off-Market Land across all 50 States). */
(function () {
  "use strict";
  var root = document.getElementById("services-app");
  if (!root) return;
  var base = document.body.getAttribute("data-base") || "";
  var sp = new URLSearchParams(location.search);

  function money(v) {
    if (v == null || isNaN(v)) return "–";
    return "$" + (Math.abs(v - Math.round(v)) < 0.005
      ? Math.round(v).toLocaleString("en-US")
      : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  var form = document.getElementById("concierge-form");
  var banner = document.getElementById("selected-parcel-banner");
  var feePreview = document.getElementById("fee-breakdown-live");
  var mapWrap = document.getElementById("unlisted-pin-wrap");
  var previewEl = document.getElementById("concierge-xray-preview");
  var brief = document.getElementById("acquisition-brief");
  var boundary = window.LandosaurGeo ? window.LandosaurGeo.decode(sp.get("boundary")) : [];
  var outBox = document.getElementById("concierge-result");
  var submitBtn = document.getElementById("concierge-submit");
  var serviceCards = Array.prototype.slice.call(document.querySelectorAll("[data-select-service]"));

  function updateFeePreview() {
    if (!feePreview || !form) return;
    var official = parseFloat(form.official_price.value);
    var budget = parseFloat(form.max_budget.value);
    var baseAmt = (!isNaN(official) && official > 0) ? official : ((!isNaN(budget) && budget > 0) ? budget : null);
    if (baseAmt) {
      var fee10 = Math.round(baseAmt * 0.1 * 100) / 100;
      var total = Math.round((baseAmt + fee10) * 100) / 100;
      feePreview.innerHTML =
        "<div class='fee-line'><span>Base parcel price / target offer</span><strong>" + money(baseAmt) + "</strong></div>" +
        "<div class='fee-line'><span>Landosaur Land Agent Acquisition &amp; Transfer Fee (10% on close)</span><strong>+" + money(fee10) + "</strong></div>" +
        "<div class='fee-line total'><span>Estimated Turnkey All-In Total</span><strong>" + money(total) + "</strong></div>" +
        "<div class='fee-line due'><span>Due today to initiate full verification &amp; acquisition</span><strong>$20.00</strong></div>";
    } else {
      feePreview.innerHTML =
        "<div class='fee-line'><span>Parcel purchase / bid amount</span><strong>Confirmed after agency or owner response</strong></div>" +
        "<div class='fee-line'><span>Landosaur Land Agent Transfer Fee</span><strong>10% only upon successful closing</strong></div>" +
        "<div class='fee-line due'><span>Due today to initiate Land Agent work</span><strong>$20.00</strong></div>";
    }
  }

  function setActiveService(svc, scrollToForm) {
    if (!form) return;
    form.service_type.value = svc;
    serviceCards.forEach(function (c) {
      c.classList.toggle("active-service", c.getAttribute("data-select-service") === svc);
    });
    if (mapWrap) {
      mapWrap.hidden = svc === "listed_acquisition" && Boolean(form.parcel_id.value);
      if (!mapWrap.hidden && pinMap) setTimeout(function () { pinMap.invalidateSize(); }, 80);
    }
    updateFeePreview();
    updateBrief();
    if (scrollToForm) {
      var anchor = document.getElementById("start-land-agent");
      if (anchor) anchor.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  serviceCards.forEach(function (card) {
    card.addEventListener("click", function () {
      setActiveService(card.getAttribute("data-select-service"), true);
    });
  });

  function updateBrief() {
    if (!form || !brief) return;
    var county = form.county.value.trim(), state = form.state.value.trim().toUpperCase();
    var apn = form.apn.value.trim(), loc = form.location.value.trim();
    var coords = form.lat.value && form.lon.value ? form.lat.value + ", " + form.lon.value : "";
    var acres = Number(form.acres.value);
    brief.hidden = form.service_type.value !== "unlisted_outreach" || !(coords || loc || apn && county);
    if (brief.hidden) return;
    document.getElementById("brief-target").textContent = [
      [county, state].filter(Boolean).join(", "), apn && "APN " + apn, loc, coords,
      acres > 0 && acres.toLocaleString("en-US", { maximumFractionDigits: 4 }) + " approximate acres",
      boundary.length && boundary.length + "-point drawn boundary",
    ].filter(Boolean).join(" · ");
    var budget = Number(form.max_budget.value);
    document.getElementById("brief-offer").textContent = budget > 0 ?
      "I would like to discuss purchasing the parcel identified above for up to " + money(budget) +
      ", subject to confirming title, access and boundaries, completing due diligence, and agreeing to written purchase terms." :
      "I would like to discuss purchasing the parcel identified above, subject to agreeing on a price and completing due diligence.";
    var buyer = form.buyer_name.value.trim();
    document.getElementById("brief-buyer").textContent = buyer ? "Sincerely, " + buyer : "Sincerely, ____________________";
  }

  document.getElementById("print-acquisition-brief")?.addEventListener("click", function () {
    document.body.classList.add("print-acquisition");
    window.addEventListener("afterprint", function () { document.body.classList.remove("print-acquisition"); }, { once: true });
    window.print();
  });

  // Drop-a-pin satellite map for Unlisted / Off-Market Land Acquisition
  var pinMapEl = document.getElementById("concierge-pin-map");
  var pinMap = null, pinMarker = null;
  if (pinMapEl && window.L) {
    var aerial = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 20, attribution: "USGS Imagery" });
    var streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxNativeZoom: 19, maxZoom: 20, attribution: "&copy; OpenStreetMap" });
    pinMap = L.map(pinMapEl, { scrollWheelZoom: true, doubleClickZoom: true, touchZoom: true, maxZoom: 20, layers: [aerial] }).setView([38.5, -96.0], 4);
    L.control.layers({ "USGS Satellite": aerial, "Streets": streets }).addTo(pinMap);
    pinMap.on("click", function (ev) {
      if (pinBoundary) pinMap.removeLayer(pinBoundary);
      pinBoundary = null;
      boundary = [];
      setPin(ev.latlng.lat, ev.latlng.lng, true);
    });
  }

  var pinBoundary = null, pinRequest = 0;
  function setPin(lat, lon, runX) {
    lat = Math.round(Number(lat) * 100000) / 100000;
    lon = Math.round(Number(lon) * 100000) / 100000;
    if (!isFinite(lat) || !isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return;
    var revision = ++pinRequest;
    if (form) {
      form.lat.value = lat;
      form.lon.value = lon;
    }
    updateBrief();
    if (pinMap) {
      if (pinMarker) pinMap.removeLayer(pinMarker);
      pinMarker = L.circleMarker([lat, lon], { radius: 8, color: "#fff", weight: 2.5, fillColor: "#c8f189", fillOpacity: 1 }).addTo(pinMap);
      pinMap.setView([lat, lon], Math.max(pinMap.getZoom(), 14));
    }
    if (runX && previewEl) {
      previewEl.hidden = false;
      previewEl.innerHTML = "<p class='small'>Running live federal Parcel X-Ray on pinned parcel…</p>";
      fetch(base + "/api/xray/?lat=" + encodeURIComponent(lat) + "&lon=" + encodeURIComponent(lon))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (revision !== pinRequest) return;
          if (!d || d.error) { previewEl.innerHTML = "<p class='small'>Pin placed at " + lat + ", " + lon + ".</p>"; return; }
          if (d.county) {
            if (form && !form.county.value && d.county.county_name) form.county.value = d.county.county_name;
            if (form && !form.state.value && d.county.state_code) form.state.value = d.county.state_code;
          }
          updateBrief();
          var bits = [];
          if (d.county && d.county.county_name) bits.push("<strong>" + esc(d.county.county_name) + ", " + esc(d.county.state_code) + "</strong>");
          if (d.usgs && d.usgs.elevation_ft != null) bits.push("Elev " + d.usgs.elevation_ft.toLocaleString("en-US") + " ft");
          if (d.fema && d.fema.zone) bits.push("FEMA Zone " + esc(d.fema.zone));
          if (d.roads && d.roads.nearest_road_ft != null) bits.push("Road ~" + d.roads.nearest_road_ft.toLocaleString("en-US") + " ft");
          if (d.county && d.county.benchmark_usd_per_acre) bits.push("County avg " + money(d.county.benchmark_usd_per_acre) + "/ac");
          previewEl.innerHTML = "<p style='margin:0'><strong>Unlisted Parcel X-Ray:</strong> " + bits.join(" · ") + "</p>";
        })
        .catch(function () { if (revision === pinRequest) previewEl.hidden = true; });
    }
  }

  var locBtn = document.getElementById("concierge-locate-btn");
  if (locBtn && form) {
    locBtn.addEventListener("click", function () {
      var q = (form.location.value || "").trim();
      if (!q) return;
      if (previewEl) { previewEl.hidden = false; previewEl.innerHTML = "<p class='small'>Locating \"" + esc(q) + "\"…</p>"; }
      fetch(base + "/api/xray/?q=" + encodeURIComponent(q))
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok || !res.d || res.d.error) {
            if (previewEl) previewEl.innerHTML = "<p class='small'>" + esc((res.d && res.d.error) || "Location not found.") + "</p>";
            return;
          }
          setPin(res.d.lat, res.d.lon, true);
        });
    });
  }

  var returningFromCheckout = sp.get("paid") === "1";
  var lastCode = "";
  try { lastCode = sessionStorage.getItem("lando_last_agt") || ""; } catch (e) {}

  var pId = sp.get("parcel") || "";
  var pTitle = sp.get("title") || "";
  var pPrice = sp.get("price") || "";
  var pAcres = sp.get("acres") || "";
  var pCounty = sp.get("county") || "";
  var pState = sp.get("state") || "";
  var pApn = sp.get("apn") || "";
  var pMode = sp.get("mode") || "";
  var pLat = sp.get("lat") || "";
  var pLon = sp.get("lon") || "";
  var pSvc = sp.get("service") || (pId ? (pMode === "auction" ? "auction_proxy" : (pMode === "landbank" ? "landbank_application" : "listed_acquisition")) : "unlisted_outreach");

  if (form) {
    if (pId) form.parcel_id.value = pId;
    if (pTitle) form.parcel_title.value = pTitle;
    if (pPrice) form.official_price.value = pPrice;
    if (pAcres) form.acres.value = pAcres;
    if (pCounty) form.county.value = pCounty;
    if (pState) form.state.value = pState;
    if (pApn) form.apn.value = pApn;
    if (pLat && pLon) setPin(parseFloat(pLat), parseFloat(pLon), false);
    if (boundary.length && pinMap) {
      pinBoundary = L.polygon(boundary.map(function (point) { return [point[1], point[0]]; }), { color: "#176e41", weight: 3, interactive: false }).addTo(pinMap);
      setTimeout(function () { if (pinBoundary) pinMap.fitBounds(pinBoundary.getBounds(), { padding: [20, 20], maxZoom: 17 }); }, 100);
    }
    if (!Array.from(form.service_type.options).some(function (option) { return option.value === pSvc; })) pSvc = "unlisted_outreach";
    setActiveService(pSvc, false);
    if (returningFromCheckout && banner) {
      banner.hidden = false;
      banner.innerHTML = "<h3>Check your Land Agent payment</h3><p>Payment status comes from the order record. Use your confirmation code below to check for Stripe verification.</p><a href='#track-order'>Go to the order tracker ↓</a>";
    }

    if (pId && banner && !returningFromCheckout) {
      var pr = parseFloat(pPrice);
      var fee10 = (!isNaN(pr) && pr > 0) ? Math.round(pr * 0.1 * 100) / 100 : null;
      var tot = fee10 != null ? Math.round((pr + fee10) * 100) / 100 : null;
      banner.hidden = false;
      banner.innerHTML =
        "<div class='eyebrow'>Selected Parcel Locked In for Land Agent Acquisition</div>" +
        "<h3 style='margin:4px 0 6px'>" + esc(pTitle || ("Parcel " + pId)) + "</h3>" +
        "<p style='margin:0'>" +
        (pCounty || pState ? ("<strong>Location:</strong> " + esc([pCounty, pState].filter(Boolean).join(", ")) + " · ") : "") +
        (pApn ? ("<strong>APN:</strong> <code>" + esc(pApn) + "</code> · ") : "") +
        (pAcres ? ("<strong>Acres:</strong> " + esc(pAcres) + " ac · ") : "") +
        (tot != null
          ? ("<strong>Official:</strong> " + money(pr) + " + <strong>10% Land Agent:</strong> " + money(fee10) + " = <strong>Est. Turnkey: " + money(tot) + "</strong>")
          : "<strong>Land Agent Fee:</strong> 10% only on close · <strong>$20 to initiate today</strong>") +
        "</p>";
    }

    form.service_type.addEventListener("change", function () { setActiveService(form.service_type.value, false); });
    form.official_price.addEventListener("input", updateFeePreview);
    form.max_budget.addEventListener("input", updateFeePreview);
    form.addEventListener("input", updateBrief);

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      submitBtn.disabled = true;
      submitBtn.textContent = "Creating Acquisition Dossier ($20)…";
      outBox.hidden = false;
      outBox.textContent = "Logging acquisition request & running Federal Parcel X-Ray…";

      var payload = {
        service_type: form.service_type.value,
        parcel_id: form.parcel_id.value.trim() || undefined,
        parcel_title: form.parcel_title.value.trim() || undefined,
        apn: form.apn.value.trim() || undefined,
        county: form.county.value.trim() || undefined,
        state: form.state.value.trim() || undefined,
        location: form.location.value.trim() || undefined,
        lat: form.lat.value ? parseFloat(form.lat.value) : undefined,
        lon: form.lon.value ? parseFloat(form.lon.value) : undefined,
        acres: form.acres.value ? parseFloat(form.acres.value) : undefined,
        boundary: boundary.length ? boundary : undefined,
        official_price: form.official_price.value ? parseFloat(form.official_price.value) : undefined,
        max_budget: form.max_budget.value ? parseFloat(form.max_budget.value) : undefined,
        financing: form.financing.value,
        buyer_name: form.buyer_name.value.trim(),
        buyer_email: form.buyer_email.value.trim(),
        buyer_phone: form.buyer_phone.value.trim(),
        notes: form.notes.value.trim(),
        website_hp: form.website_hp ? form.website_hp.value : "",
        submitted_by_agent: "landosaur-services-web",
      };

      fetch(base + "/api/concierge/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok || !res.d || !res.d.ok) {
            outBox.innerHTML = "<strong>Could not start order:</strong> " + esc((res.d && res.d.error) || "Please check required fields.");
            return;
          }
          var d = res.d;
          try { if (d.confirmation_code) sessionStorage.setItem("lando_last_agt", d.confirmation_code); } catch (e) {}
          var stripeHtml = d.stripe_checkout_url
            ? "<p style='margin-top:12px'><a class='button' href='" + esc(d.stripe_checkout_url) + "'>Pay $20 Land Agent Initiation on Stripe →</a></p>"
            : "<p class='small' style='margin-top:8px'>Your order is queued in our Land Agent ledger under confirmation code <code>" + esc(d.confirmation_code) + "</code>. Watch your inbox for the $20 Stripe initiation checkout link.</p>";
          var estHtml = d.estimated_turnkey_total
            ? "<p class='small'><strong>Itemized Estimate:</strong> Base " + money(d.official_price || payload.max_budget) + " + 10% Land Agent Fee (" + money(d.concierge_fee_10pct) + ") = <strong>" + money(d.estimated_turnkey_total) + "</strong> · $20 due today.</p>"
            : "";
          outBox.innerHTML =
            "<h3>Land Agent Dossier Opened · <code>" + esc(d.confirmation_code) + "</code></h3>" +
            "<p>" + esc(d.message) + "</p>" + estHtml + stripeHtml;
          if (trackForm) trackForm.code.value = d.confirmation_code;
        })
        .catch(function () {
          outBox.textContent = "Network error submitting acquisition request. Please try again.";
        })
        .finally(function () {
          submitBtn.disabled = false;
          submitBtn.textContent = "Start Acquisition with Land Agent — $20 →";
        });
    });
  }

  var trackForm = document.getElementById("track-order-form");
  var trackOut = document.getElementById("track-order-out");
  var stages = {
    dossier_opened: "Dossier opened",
    initiation_confirmed: "$20 initiation confirmed",
    diligence: "Federal X-Ray and county title / lien audit",
    outreach: "Agency bid or landowner outreach",
    transfer: "Licensed title and deed transfer",
  };
  var orderRequest = 0;

  function showOrder(order) {
    var html = "<h3>" + esc(order.parcel_title || "Land Agent order") + "</h3><p><code>" +
      esc(order.confirmation_code) + "</code></p>";
    var steps = Array.isArray(order.progress) ? order.progress : [];
    html += "<ol class='order-progress'>" + steps.map(function (step) {
      var state = ["complete", "current", "pending"].includes(step.state) ? step.state : "pending";
      var stamp = step.at && Number.isFinite(Date.parse(step.at)) ? new Date(step.at).toLocaleDateString("en-US") : "";
      return "<li class='order-step-" + state + "'" + (state === "current" ? " aria-current='step'" : "") + "><strong>" +
        esc(stages[step.id] || "") + "</strong><small>" +
        (state === "complete" ? "Complete" : state === "current" ? "Current" : "Pending") + (stamp ? " · " + esc(stamp) : "") + "</small></li>";
    }).join("") + "</ol>";

    var summary = order.xray_summary;
    if (summary) {
      var findings = [];
      if (summary.elevation_ft != null) findings.push("Elevation " + summary.elevation_ft.toLocaleString("en-US") + " ft");
      if (summary.fema_zone) findings.push("FEMA zone " + summary.fema_zone);
      if (summary.wetlands_100m != null) findings.push(summary.wetlands_100m ? "Mapped wetlands within 100 m" : "No mapped wetlands within 100 m");
      if (summary.nearest_road_ft != null) findings.push("Nearest mapped road " + summary.nearest_road_ft.toLocaleString("en-US") + " ft");
      if (summary.county_benchmark_per_acre != null) findings.push("County benchmark " + money(summary.county_benchmark_per_acre) + "/acre");
      if (findings.length) html += "<p><strong>Recorded Parcel X-Ray</strong><br>" + esc(findings.join(" · ")) + "</p>";
    }
    if (order.estimated_turnkey_total != null) {
      html += "<div class='fee-ledger order-fees'><div class='fee-line'><span>" + (order.official_price ? "Parcel price in order" : "Target offer / budget") +
        "</span><strong>" + money(order.estimated_base_price) + "</strong></div>" +
        "<div class='fee-line'><span>Land Agent fee on close (10%)</span><strong>" + money(order.concierge_fee_10pct) + "</strong></div>" +
        "<div class='fee-line total'><span>Estimated parcel price plus closing fee</span><strong>" + money(order.estimated_turnkey_total) + "</strong></div></div>";
    }
    if (order.stripe_checkout_url && !returningFromCheckout) html +=
      "<p><a class='button sm' href='" + esc(order.stripe_checkout_url) + "'>Complete $20 Stripe Checkout →</a></p>";
    trackOut.innerHTML = html;
  }

  function checkOrder(code, remaining, revision) {
    trackOut.hidden = false;
    fetch(base + "/api/concierge/?code=" + encodeURIComponent(code))
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (revision !== orderRequest) return;
        if (!data.order) { trackOut.textContent = data.error || "Confirmation code not found."; return; }
        showOrder(data.order);
        if (remaining && data.order.stripe_checkout_url && !data.order.paid_at) {
          setTimeout(function () { if (revision === orderRequest) checkOrder(code, remaining - 1, revision); }, 6000);
        }
      })
      .catch(function () { if (revision === orderRequest) trackOut.textContent = "Could not look up the order right now."; });
  }

  if (trackForm && trackOut) {
    trackForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var code = trackForm.code.value.trim().toUpperCase();
      if (!/^AGT-[A-F0-9]{8}$/.test(code)) {
        ++orderRequest;
        trackOut.hidden = false;
        trackOut.textContent = "Enter the AGT code from your acquisition dossier.";
        return;
      }
      trackOut.textContent = "Checking order " + code + "…";
      checkOrder(code, 0, ++orderRequest);
    });
    var initialCode = (sp.get("code") || (returningFromCheckout ? lastCode : "") || "").trim().toUpperCase();
    if (/^AGT-[A-F0-9]{8}$/.test(initialCode)) {
      trackForm.code.value = initialCode;
      checkOrder(initialCode, returningFromCheckout ? 4 : 0, ++orderRequest);
    }
  }
})();

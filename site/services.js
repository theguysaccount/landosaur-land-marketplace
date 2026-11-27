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
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  var form = document.getElementById("concierge-form");
  var banner = document.getElementById("selected-parcel-banner");
  var feePreview = document.getElementById("fee-breakdown-live");
  var mapWrap = document.getElementById("unlisted-pin-wrap");
  var previewEl = document.getElementById("concierge-xray-preview");
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

  // Drop-a-pin satellite map for Unlisted / Off-Market Land Acquisition
  var pinMapEl = document.getElementById("concierge-pin-map");
  var pinMap = null, pinMarker = null;
  if (pinMapEl && window.L) {
    var aerial = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 20, attribution: "USGS Imagery" });
    var streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxNativeZoom: 19, maxZoom: 20, attribution: "&copy; OpenStreetMap" });
    pinMap = L.map(pinMapEl, { scrollWheelZoom: true, doubleClickZoom: true, touchZoom: true, maxZoom: 20, layers: [aerial] }).setView([38.5, -96.0], 4);
    L.control.layers({ "USGS Satellite": aerial, "Streets": streets }).addTo(pinMap);
    pinMap.on("click", function (ev) { setPin(ev.latlng.lat, ev.latlng.lng, true); });
  }

  function setPin(lat, lon, runX) {
    lat = Math.round(Number(lat) * 100000) / 100000;
    lon = Math.round(Number(lon) * 100000) / 100000;
    if (!isFinite(lat) || !isFinite(lon)) return;
    if (form) {
      form.lat.value = lat;
      form.lon.value = lon;
    }
    if (pinMap) {
      if (pinMarker) pinMap.removeLayer(pinMarker);
      pinMarker = L.circleMarker([lat, lon], { radius: 8, color: "#fff", weight: 2.5, fillColor: "#c8f189", fillOpacity: 1 }).addTo(pinMap);
      pinMap.setView([lat, lon], Math.max(pinMap.getZoom(), 14));
    }
    if (runX && previewEl) {
      previewEl.hidden = false;
      previewEl.innerHTML = "<p class='small'>Running live 9-agency Federal Parcel X-Ray on pinned parcel…</p>";
      fetch(base + "/api/xray/?lat=" + encodeURIComponent(lat) + "&lon=" + encodeURIComponent(lon))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d || d.error) { previewEl.innerHTML = "<p class='small'>Pin placed at " + lat + ", " + lon + ".</p>"; return; }
          if (d.county) {
            if (form && !form.county.value && d.county.county_name) form.county.value = d.county.county_name;
            if (form && !form.state.value && d.county.state_code) form.state.value = d.county.state_code;
          }
          var bits = [];
          if (d.county && d.county.county_name) bits.push("<strong>" + esc(d.county.county_name) + ", " + esc(d.county.state_code) + "</strong>");
          if (d.usgs && d.usgs.elevation_ft != null) bits.push("Elev " + d.usgs.elevation_ft.toLocaleString("en-US") + " ft");
          if (d.fema && d.fema.zone) bits.push("FEMA Zone " + esc(d.fema.zone));
          if (d.roads && d.roads.nearest_road_ft != null) bits.push("Road ~" + d.roads.nearest_road_ft.toLocaleString("en-US") + " ft");
          if (d.county && d.county.benchmark_usd_per_acre) bits.push("County avg " + money(d.county.benchmark_usd_per_acre) + "/ac");
          previewEl.innerHTML = "<p style='margin:0'><strong>Unlisted Parcel X-Ray:</strong> " + bits.join(" · ") + "</p>";
        })
        .catch(function () { previewEl.hidden = true; });
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

  // Post-Stripe Checkout confirmation banner (?paid=1)
  if (sp.get("paid") === "1" && banner) {
    banner.hidden = false;
    var sid = sp.get("session_id") || "";
    var lastCode = "";
    try { lastCode = sessionStorage.getItem("lando_last_agt") || ""; } catch (e) {}
    banner.innerHTML =
      "<div class='eyebrow'>Payment Received · Land Agent Activated</div>" +
      "<h3 style='margin:4px 0 6px'>Your $20 Landosaur Land Agent Initiation Is Confirmed" + (lastCode ? (" · <code>" + esc(lastCode) + "</code>") : "") + "</h3>" +
      "<p style='margin:0'>Our acquisition desk is now reviewing your dossier for county tax/lien/redemption verification, owner or agency outreach, and closing transfer coordination." +
      (sid ? (" Stripe receipt ref: <code>" + esc(sid.slice(0, 28)) + "…</code>.") : "") +
      " Use the order status tracker below with your <code>AGT-</code> code anytime.</p>";
  }

  // Pre-fill from URL parameters (arriving from any of the 25,087 parcel dossiers OR from Land Atlas county!)
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
    setActiveService(pSvc, false);

    if (pId && banner) {
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

  // Order status lookup
  var trackForm = document.getElementById("track-order-form");
  var trackOut = document.getElementById("track-order-out");
  if (trackForm && trackOut) {
    trackForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var code = (trackForm.code.value || "").trim().toUpperCase();
      if (!code) return;
      trackOut.hidden = false;
      trackOut.textContent = "Checking order " + code + "…";
      fetch(base + "/api/concierge/?code=" + encodeURIComponent(code))
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok || !res.d || !res.d.order) {
            trackOut.textContent = (res.d && res.d.error) || "Confirmation code not found.";
            return;
          }
          var o = res.d.order;
          trackOut.innerHTML =
            "<strong>" + esc(o.confirmation_code) + "</strong> · Status: <span class='badge ok'>" + esc(o.status.replace(/_/g, " ")) + "</span><br>" +
            esc(o.parcel_title) + (o.estimated_turnkey_total ? (" · Est. Turnkey: <strong>" + money(o.estimated_turnkey_total) + "</strong>") : "") +
            (o.stripe_checkout_url ? (" · <a href='" + esc(o.stripe_checkout_url) + "' target='_blank' rel='noopener'>Complete $20 Checkout ↗</a>") : "");
        })
        .catch(function () { trackOut.textContent = "Could not look up order right now."; });
    });
  }
})();

/* Landosaur /list/ — 60-Second Drop-a-Pin Owner/Agent Listing Flow + 1-Prompt AI Agent Publishing Hub. */
(function () {
  "use strict";
  var root = document.getElementById("list-app");
  if (!root) return;
  var base = document.body.getAttribute("data-base") || "";

  // Copy AI Agent prompt / curl buttons
  Array.prototype.forEach.call(document.querySelectorAll("[data-copy-target]"), function (btn) {
    btn.addEventListener("click", function () {
      var target = document.getElementById(btn.getAttribute("data-copy-target"));
      if (!target) return;
      var text = target.textContent || target.value || "";
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(function () {
          var prev = btn.textContent;
          btn.textContent = "Copied ✓";
          setTimeout(function () { btn.textContent = prev; }, 2200);
        });
      }
    });
  });

  // Sale mode toggle (Buy It Now vs Auction)
  var form = document.getElementById("direct-list-form");
  var auctionBox = document.getElementById("auction-only-fields");
  var priceLbl = document.getElementById("price-field-label");
  function syncMode() {
    if (!form) return;
    var mode = form.sale_mode.value;
    if (auctionBox) auctionBox.hidden = mode !== "auction";
    if (priceLbl) priceLbl.textContent = mode === "auction" ? "Starting bid ($)" : "Buy It Now price ($)";
  }
  if (form && form.sale_mode) {
    Array.prototype.forEach.call(form.querySelectorAll('input[name="sale_mode"]'), function (r) {
      r.addEventListener("change", syncMode);
    });
    syncMode();
  }

  // Seller type toggle (Owner vs Real Estate Agent)
  var agentFields = document.getElementById("agent-only-fields");
  function syncSeller() {
    if (!form || !agentFields) return;
    agentFields.hidden = form.seller_type.value !== "agent";
  }
  if (form && form.seller_type) {
    Array.prototype.forEach.call(form.querySelectorAll('input[name="seller_type"]'), function (r) {
      r.addEventListener("change", syncSeller);
    });
    syncSeller();
  }

  // Interactive Drop-a-Pin Satellite Map + Instant Auto-Fill from 9-Agency Federal X-Ray
  var mapEl = document.getElementById("list-pin-map");
  var previewEl = document.getElementById("list-xray-preview");
  var pin = null, map = null;
  if (mapEl && window.L) {
    var aerial = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16, attribution: "USGS Imagery" });
    var streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap" });
    map = L.map(mapEl, { layers: [aerial] }).setView([38.5, -96.0], 4);
    L.control.layers({ "USGS Satellite": aerial, "Streets": streets }).addTo(map);
    map.on("click", function (ev) {
      setPin(ev.latlng.lat, ev.latlng.lng, true);
    });
  }

  function setPin(lat, lon, runPreview) {
    lat = Math.round(Number(lat) * 100000) / 100000;
    lon = Math.round(Number(lon) * 100000) / 100000;
    if (!isFinite(lat) || !isFinite(lon)) return;
    if (form) {
      form.lat.value = lat;
      form.lon.value = lon;
    }
    if (map) {
      if (pin) map.removeLayer(pin);
      pin = L.circleMarker([lat, lon], { radius: 8, color: "#fff", weight: 2.5, fillColor: "#c8f189", fillOpacity: 1 }).addTo(map);
      map.setView([lat, lon], Math.max(map.getZoom(), 13));
    }
    if (runPreview && previewEl) {
      previewEl.hidden = false;
      previewEl.innerHTML = "<p class='small'>Running live 9-agency Federal Parcel X-Ray to auto-fill county, flood zone, elevation, soil &amp; road proximity…</p>";
      fetch(base + "/api/xray/?lat=" + encodeURIComponent(lat) + "&lon=" + encodeURIComponent(lon))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d || d.error) { previewEl.innerHTML = "<p class='small'>Pin placed at " + lat + ", " + lon + ".</p>"; return; }
          var bits = [];
          if (d.county && d.county.county_name) bits.push("<strong>" + d.county.county_name + ", " + d.county.state_code + "</strong>");
          if (d.usgs && d.usgs.elevation_ft != null) bits.push("Elev " + d.usgs.elevation_ft.toLocaleString("en-US") + " ft (" + (d.usgs.slope_pct != null ? d.usgs.slope_pct + "% slope" : "") + ")");
          if (d.fema && d.fema.zone) bits.push("FEMA Zone " + d.fema.zone);
          if (d.soil && d.soil.drainage_class) bits.push("Soil: " + d.soil.drainage_class);
          if (d.roads && d.roads.nearest_road_ft != null) bits.push("Nearest road ~" + d.roads.nearest_road_ft.toLocaleString("en-US") + " ft");
          if (d.county && d.county.benchmark_usd_per_acre) bits.push("County avg $" + Math.round(d.county.benchmark_usd_per_acre).toLocaleString("en-US") + "/ac");
          previewEl.innerHTML = "<p style='margin:0'><strong>Auto-detected X-Ray:</strong> " + bits.join(" · ") + "</p>";
        })
        .catch(function () { previewEl.hidden = true; });
    }
  }

  var locBtn = document.getElementById("locate-pin-btn");
  if (locBtn && form) {
    locBtn.addEventListener("click", function () {
      var q = (form.location.value || "").trim();
      if (!q) return;
      if (previewEl) { previewEl.hidden = false; previewEl.innerHTML = "<p class='small'>Locating \"" + q + "\"…</p>"; }
      fetch(base + "/api/xray/?q=" + encodeURIComponent(q))
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok || !res.d || res.d.error) {
            if (previewEl) previewEl.innerHTML = "<p class='small'>" + ((res.d && res.d.error) || "Location not found.") + "</p>";
            return;
          }
          setPin(res.d.lat, res.d.lon, true);
        });
    });
  }

  // Publish direct listing via real POST /api/listings/
  var outBox = document.getElementById("publish-result");
  var submitBtn = document.getElementById("publish-btn");
  if (form) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Enriching with 9 Federal APIs & publishing…"; }
      if (outBox) { outBox.hidden = false; outBox.className = "callout"; outBox.textContent = "Running live 9-agency Federal Parcel X-Ray and publishing your listing…"; }
      var payload = {
        sale_mode: form.sale_mode.value,
        seller_type: form.seller_type.value,
        lat: form.lat.value ? parseFloat(form.lat.value) : undefined,
        lon: form.lon.value ? parseFloat(form.lon.value) : undefined,
        location: form.location.value.trim(),
        title: form.title.value.trim(),
        acres: parseFloat(form.acres.value),
        price: parseFloat(form.price.value),
        starting_bid: form.sale_mode.value === "auction" ? parseFloat(form.price.value) : undefined,
        buy_now_price: form.buy_now_price && form.buy_now_price.value ? parseFloat(form.buy_now_price.value) : undefined,
        auction_end: form.auction_end && form.auction_end.value ? new Date(form.auction_end.value).toISOString() : undefined,
        apn: form.apn.value.trim(),
        zoning: form.zoning.value.trim(),
        road_access: form.road_access.value.trim(),
        utilities: form.utilities.value.trim(),
        financing_offered: !!(form.financing_offered && form.financing_offered.checked),
        contact_name: form.contact_name.value.trim(),
        contact_email: form.contact_email.value.trim(),
        contact_phone: form.contact_phone.value.trim(),
        brokerage: form.brokerage ? form.brokerage.value.trim() : "",
        agent_license: form.agent_license ? form.agent_license.value.trim() : "",
        checkout_url: form.checkout_url ? form.checkout_url.value.trim() : "",
        escrow_notes: form.escrow_notes ? form.escrow_notes.value.trim() : "",
        notes: form.notes.value.trim(),
        website_hp: form.website_hp ? form.website_hp.value : "",
        submitted_by_agent: "landosaur-web",
      };
      fetch(base + "/api/listings/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok || !res.d || !res.d.ok) {
            outBox.innerHTML = "<strong>Could not publish:</strong> " + ((res.d && res.d.error) || "Please check required fields.");
            return;
          }
          var d = res.d;
          var localHref = base + "/direct/?id=" + encodeURIComponent(d.id);
          outBox.innerHTML =
            "<h3>Listing Published Live on Landosaur!</h3>" +
            "<p>Your parcel is now live on the map and searchable nationwide, enriched with 9 live federal GIS signals.</p>" +
            "<p><a class='button' href='" + localHref + "'>View Live Listing &amp; Bidding Page →</a></p>" +
            "<p class='small' style='margin-top:10px'><strong>Save your Seller Edit Token</strong> (needed to mark sold or withdraw via API): <code>" + d.edit_token + "</code></p>";
          form.reset();
          syncMode();
          syncSeller();
        })
        .catch(function () {
          outBox.textContent = "Network error while publishing. Please try again.";
        })
        .finally(function () {
          if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Publish Listing Free →"; }
        });
    });
  }
})();

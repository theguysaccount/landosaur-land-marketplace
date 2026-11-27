/* Landosaur Live Federal Parcel X-Ray — shared renderer (used on /land/<id>/ dossiers and standalone /xray/). */
(function () {
  "use strict";
  var base = document.body.getAttribute("data-base") || "";

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function fmtNum(v, suffix) {
    if (v == null || isNaN(v)) return "Unavailable";
    return Number(v).toLocaleString("en-US") + (suffix || "");
  }

  function tierMeta(tier) {
    if (tier === "favorable") return { cls: "ok", label: "Favorable signals" };
    if (tier === "caution") return { cls: "warn", label: "Caution / extra cost" };
    if (tier === "constraint") return { cls: "risk", label: "Major constraint" };
    return { cls: "off", label: "Field check needed" };
  }

  function skeletonHtml() {
    var cards = "";
    for (var i = 0; i < 6; i++) {
      cards += '<div class="xray-tile skel"><div class="skel-bar sm"></div><div class="skel-bar lg"></div><div class="skel-bar md"></div></div>';
    }
    return '<div class="xray-grid" aria-busy="true" aria-label="Loading live federal GIS data">' + cards + "</div>";
  }

  function tileNode(kicker, headline, sub, badgeCls, badgeText, sourceUrl, sourceName) {
    var card = el("article", "xray-tile");
    var head = el("div", "xray-tile-head");
    head.appendChild(el("span", "xray-kicker", kicker));
    if (badgeText) head.appendChild(el("span", "badge " + (badgeCls || "off"), badgeText));
    card.appendChild(head);
    card.appendChild(el("strong", "xray-val", headline));
    if (sub) card.appendChild(el("p", "xray-sub", sub));
    if (sourceUrl && sourceName) {
      var a = el("a", "xray-src", sourceName + " ↗");
      a.href = sourceUrl;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      card.appendChild(a);
    } else if (sourceName) {
      card.appendChild(el("span", "xray-src", sourceName));
    }
    return card;
  }

  function buildParcelExtraUses(ctx) {
    if (!ctx) return [];
    var extra = [];
    if (ctx.zoning || ctx.buildable || ctx.side_lot || (ctx.acres != null && ctx.acres < 0.5)) {
      var notes = [];
      var tier = "check";
      if (ctx.buildable && /yes/i.test(ctx.buildable)) {
        tier = "favorable";
        notes.push("Agency flags lot as Buildable (" + ctx.buildable + ")");
      } else if (ctx.buildable && /no/i.test(ctx.buildable)) {
        tier = "constraint";
        notes.push("Agency flags lot as Buildable: " + ctx.buildable);
      }
      if (ctx.zoning) notes.push("Zoning: " + ctx.zoning);
      if (ctx.side_lot) notes.push("Side-lot eligible: " + ctx.side_lot);
      if (ctx.acres != null) notes.push(ctx.acres + " acres");
      extra.push({
        id: "infill",
        title: "Infill Build / Neighbor Side-Lot",
        tier: tier,
        summary: notes.join(" · ") || "Confirm minimum lot width, setbacks, and municipal water/sewer tap fees.",
      });
    }
    if (ctx.offering === "auction" || ctx.price_kind === "min_bid") {
      var aNotes = ["Tax-sale / auction minimum bid — not an appraisal or guaranteed final price"];
      if (ctx.price != null && ctx.acres > 0) {
        aNotes.push("Opening floor $" + Math.round(ctx.price / ctx.acres).toLocaleString("en-US") + "/ac");
      }
      aNotes.push("Verify redemption period, quiet-title cost, back liens, and physical occupancy");
      extra.push({
        id: "taxsale",
        title: "Tax-Sale / Auction Investment",
        tier: "caution",
        summary: aNotes.join(" · "),
      });
    }
    return extra;
  }

  function renderXrayInto(container, d, parcelCtx) {
    container.textContent = "";
    var grid = el("div", "xray-grid");

    // 1. USGS Elevation & Slope
    var u = d.usgs || {};
    if (u.status === "ok") {
      var slopeBadge = u.slope_pct == null ? "off" : (u.slope_pct < 8 ? "ok" : (u.slope_pct < 15 ? "warn" : "risk"));
      var subU = (u.slope_pct != null ? "Slope ~" + u.slope_pct + "% (" + u.terrain_class + ")" : "Point elevation") +
        (u.relief_ft != null ? " · " + u.relief_ft + " ft relief across 100m" : "") +
        (u.aspect ? " · Faces " + u.aspect : "");
      grid.appendChild(tileNode("Elevation & Terrain", fmtNum(u.elevation_ft, " ft"), subU, slopeBadge, u.terrain_class || "LiDAR", u.source_url, u.source));
    } else {
      grid.appendChild(tileNode("Elevation & Terrain", "Unavailable", "USGS 3DEP did not return elevation for this point.", "off", "Retry", "https://apps.nationalmap.gov/viewer/", "USGS 3DEP"));
    }

    // 2. FEMA Flood Hazard
    var f = d.fema || {};
    if (f.status === "ok") {
      var fBadge = f.sfha ? "risk" : (/500|Moderate/i.test(f.risk_level || "") ? "warn" : "ok");
      var fTag = f.sfha ? "100-Yr Floodplain" : (f.zone === "X" ? "Minimal Risk" : "Zone " + f.zone);
      var fSub = f.risk_level + (f.bfe_ft != null ? " · BFE " + f.bfe_ft + " ft" : "") + (f.firm_panel ? " · Panel " + f.firm_panel : "");
      grid.appendChild(tileNode("FEMA Flood Zone", "Zone " + f.zone, fSub, fBadge, fTag, f.source_url, f.source));
    } else {
      grid.appendChild(tileNode("FEMA Flood Zone", f.zone || "Not mapped", f.risk_level || "Verify paper/local flood panel on FEMA MSC.", "off", "Check MSC", f.source_url || "https://msc.fema.gov/portal/home", "FEMA NFHL"));
    }

    // 3. USFWS Wetlands
    var w = d.nwi || {};
    if (w.status === "ok") {
      var wHead = w.within_100m ? (w.count + " mapped within 100m") : "None within 100m";
      var wSub = w.within_100m ? ("Types: " + (w.types && w.types.length ? w.types.join(", ") : "Wetland polygon") + " — verify setback & permitting.") : "No USFWS National Wetlands Inventory polygon intersects within 100m of pin.";
      grid.appendChild(tileNode("Wetlands (100m)", wHead, wSub, w.within_100m ? "warn" : "ok", w.within_100m ? "Wetland nearby" : "Clear 100m", w.source_url, w.source));
    } else {
      grid.appendChild(tileNode("Wetlands (100m)", "Unavailable", "USFWS NWI lookup unavailable right now.", "off", "Check map", "https://fwsprimary.wim.usgs.gov/wetlands/apps/wetlands-mapper/", "USFWS NWI"));
    }

    // 4. USDA NRCS Soil & Septic
    var s = d.soil || {};
    if (s.status === "ok") {
      var sMeta = tierMeta(s.septic_level);
      var sBits = [];
      if (s.muname) sBits.push(s.muname);
      if (s.hydgrp) sBits.push("Hydro group " + s.hydgrp);
      if (s.water_table_in != null) sBits.push("Water table ~" + s.water_table_in + " in");
      if (s.bedrock_in != null) sBits.push("Bedrock ~" + s.bedrock_in + " in");
      if (s.farmland_class) sBits.push(s.farmland_class);
      var sSub = sBits.join(" · ") + (s.septic_signal ? " — " + s.septic_signal : "");
      grid.appendChild(tileNode("Soil & Septic Signal", s.drainage_class || "Mapped Soil", sSub, sMeta.cls, s.hydgrp ? "Group " + s.hydgrp : sMeta.label, s.source_url, s.source));
    } else {
      grid.appendChild(tileNode("Soil & Septic Signal", "Not mapped", s.septic_signal || "Urban or unmapped SSURGO unit — verify municipal sewer or perc test.", "off", "Check county", "https://websoilsurvey.nrcs.usda.gov/app/", "USDA SSURGO"));
    }

    // 5. NASA Solar & Climate
    var cl = d.climate || {};
    if (cl.status === "ok") {
      var cHead = cl.annual_sun_hours != null ? (cl.annual_sun_hours + " sun hrs/day") : "Climate mapped";
      var cBits = [];
      if (cl.winter_min_sun_hours != null) cBits.push("Winter min " + cl.winter_min_sun_hours + " hrs/day");
      if (cl.annual_precip_in != null) cBits.push("~" + cl.annual_precip_in + " in/yr rain");
      if (cl.winter_low_f != null && cl.summer_high_f != null) cBits.push("Avg " + cl.winter_low_f + "°F–" + cl.summer_high_f + "°F");
      var cBadge = cl.annual_sun_hours >= 4.5 ? "ok" : (cl.annual_sun_hours >= 3.5 ? "warn" : "off");
      grid.appendChild(tileNode("Solar & Climate", cHead, cBits.join(" · "), cBadge, cl.annual_precip_in != null ? cl.annual_precip_in + " in/yr" : "NASA", cl.source_url, cl.source));
    } else {
      grid.appendChild(tileNode("Solar & Climate", "Unavailable", "NASA POWER climatology did not respond.", "off", "Retry", "https://power.larc.nasa.gov/", "NASA POWER"));
    }

    // 6. County Land Benchmark
    var co = d.county || {};
    if (co.status === "ok") {
      var coHead = co.benchmark_usd_per_acre != null ? ("$" + Math.round(co.benchmark_usd_per_acre).toLocaleString("en-US") + "/acre") : (co.county_name || "County located");
      var coSub = (co.county_name ? co.county_name + ", " + (co.state_code || "") : "") +
        (co.benchmark_label ? " · " + co.benchmark_label + (co.benchmark_year ? " (" + co.benchmark_year + ")" : "") : " · County benchmark context");
      var stUrl = co.state_slug ? (base + "/land-prices/" + co.state_slug + "/") : (base + "/land-prices/");
      var coTile = tileNode("County Benchmark", coHead, coSub, "ok", co.state_code || "US", null, null);
      var link = el("a", "xray-src", "View " + (co.state_name || "state") + " land prices →");
      link.href = stUrl;
      coTile.appendChild(link);
      grid.appendChild(coTile);
    } else {
      grid.appendChild(tileNode("County Benchmark", "Unavailable", "County FIPS lookup unavailable.", "off", "50 States", base + "/land-prices/", "Land Prices"));
    }

    container.appendChild(grid);

    // Land Potential Screening Matrix (4 federal + up to 2 parcel-specific)
    var allUses = (d.uses || []).concat(buildParcelExtraUses(parcelCtx));
    if (allUses.length) {
      var wrap = el("div", "potential-wrap");
      wrap.appendChild(el("h3", "potential-title", "Land Potential & Suitability Screening"));
      var uGrid = el("div", "potential-grid");
      allUses.forEach(function (uItem) {
        var m = tierMeta(uItem.tier);
        var c = el("div", "potential-card tier-" + (uItem.tier || "check"));
        var top = el("div", "potential-head");
        top.appendChild(el("strong", null, uItem.title));
        top.appendChild(el("span", "badge " + m.cls, m.label));
        c.appendChild(top);
        c.appendChild(el("p", null, uItem.summary));
        uGrid.appendChild(c);
      });
      wrap.appendChild(uGrid);
      container.appendChild(wrap);
    }

    // Disclaimer + timestamp
    var foot = el("p", "small xray-disc",
      (d.disclaimer || "Automated federal GIS screening only.") +
      " Coordinates: " + d.lat + ", " + d.lon + " · Checked live via official federal APIs.");
    container.appendChild(foot);
  }

  function loadXray(container, lat, lon, parcelCtx, onDone) {
    if (!container) return;
    container.innerHTML = skeletonHtml();
    var url = base + "/api/xray?lat=" + encodeURIComponent(lat) + "&lon=" + encodeURIComponent(lon);
    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        if (d.error) throw new Error(d.error);
        renderXrayInto(container, d, parcelCtx);
        if (onDone) onDone(d);
      })
      .catch(function () {
        container.textContent = "";
        var box = el("div", "callout");
        box.innerHTML =
          "<strong>Live Federal Parcel X-Ray unavailable from this host right now.</strong> " +
          "When deployed on <code>landosaur.com</code>, this panel queries USGS 3DEP LiDAR, FEMA NFHL, USFWS Wetlands, USDA SSURGO Soil, and NASA Solar live. " +
          "Use the direct FEMA, USDA Web Soil Survey, and USFWS links above in the meantime.";
        container.appendChild(box);
      });
  }

  window.LandosaurXray = { loadXray: loadXray, renderXrayInto: renderXrayInto, skeletonHtml: skeletonHtml };

  // Standalone /xray/ interactive page controller
  var pageRoot = document.getElementById("xray-app");
  if (!pageRoot || !window.L) return;

  var mapEl = document.getElementById("xray-map");
  var outEl = document.getElementById("xray-results");
  var statusEl = document.getElementById("xray-status");
  var form = document.getElementById("xray-search-form");
  var input = document.getElementById("xray-q");
  var actionBar = document.getElementById("xray-actions");

  var aerial = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16, attribution: "USGS Imagery" });
  var streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap" });
  var topo = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16, attribution: "USGS Topo" });
  var fema = L.tileLayer.wms("https://hazards.fema.gov/arcgis/services/public/NFHL/MapServer/WMSServer", {
    layers: "28", format: "image/png", transparent: true, opacity: 0.48, attribution: "FEMA NFHL"
  });
  var map = L.map(mapEl, { layers: [aerial] }).setView([38.5, -96.0], 4);
  L.control.layers({ "USGS Satellite": aerial, "Streets": streets, "USGS Topo": topo }, { "FEMA Flood Zones": fema }).addTo(map);

  var pin = null;
  function updateActions(lat, lon, label, d) {
    if (!actionBar) return;
    actionBar.hidden = false;
    var title = label || ((d && d.county && d.county.county_name) ? (d.county.county_name + ", " + d.county.state_code) : ("Pin " + lat.toFixed(4) + ", " + lon.toFixed(4)));
    var anaUrl = base + "/analyze/?title=" + encodeURIComponent(title);
    var gmaps = "https://www.google.com/maps/@" + lat.toFixed(6) + "," + lon.toFixed(6) + ",17z/data=!3m1!1e3";
    var femaUrl = "https://msc.fema.gov/portal/search?AddressQuery=" + lat.toFixed(6) + "%2C" + lon.toFixed(6);
    actionBar.innerHTML =
      '<a class="button" href="' + anaUrl + '">Open in Deal &amp; Power Analyzer →</a>' +
      '<button type="button" class="button ghost" id="xray-print-btn">Print / Save Field PDF</button>' +
      '<a class="button ghost" href="' + gmaps + '" target="_blank" rel="noopener noreferrer">Google Satellite ↗</a>' +
      '<a class="button ghost" href="' + femaUrl + '" target="_blank" rel="noopener noreferrer">Official FEMA Map ↗</a>' +
      '<button type="button" class="button ghost" id="xray-copy-btn">Copy share link</button>';
    var pBtn = document.getElementById("xray-print-btn");
    if (pBtn) pBtn.addEventListener("click", function () { window.print(); });
    var cBtn = document.getElementById("xray-copy-btn");
    if (cBtn) cBtn.addEventListener("click", function () {
      var shareUrl = location.href.split("#")[0] + "#lat=" + lat.toFixed(5) + "&lon=" + lon.toFixed(5);
      history.replaceState(null, "", shareUrl);
      if (navigator.clipboard) navigator.clipboard.writeText(shareUrl).then(function () { cBtn.textContent = "Link copied ✓"; });
    });
  }

  function runAt(lat, lon, label, zoom) {
    lat = Number(lat); lon = Number(lon);
    if (!isFinite(lat) || !isFinite(lon)) return;
    if (pin) map.removeLayer(pin);
    pin = L.circleMarker([lat, lon], { radius: 8, color: "#fff", weight: 2.5, fillColor: "#c8f189", fillOpacity: 1 }).addTo(map);
    map.setView([lat, lon], zoom || Math.max(map.getZoom(), 14));
    history.replaceState(null, "", location.pathname + "#lat=" + lat.toFixed(5) + "&lon=" + lon.toFixed(5));
    if (statusEl) statusEl.textContent = "Running 6-agency Federal X-Ray for " + (label || (lat.toFixed(5) + ", " + lon.toFixed(5))) + "…";
    loadXray(outEl, lat, lon, null, function (d) {
      var place = label || (d.county && d.county.county_name ? (d.county.county_name + ", " + d.county.state_name) : (lat.toFixed(5) + ", " + lon.toFixed(5)));
      if (statusEl) statusEl.textContent = "Live Federal X-Ray complete: " + place + " (" + lat.toFixed(5) + ", " + lon.toFixed(5) + ")";
      updateActions(lat, lon, place, d);
    });
  }

  function runQuery(q) {
    q = (q || "").trim();
    if (!q) return;
    if (statusEl) statusEl.textContent = "Locating \"" + q + "\" and running 6-agency Federal X-Ray…";
    outEl.innerHTML = skeletonHtml();
    fetch(base + "/api/xray?q=" + encodeURIComponent(q))
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok || res.d.error) {
          outEl.textContent = "";
          if (statusEl) statusEl.textContent = res.d.error || "Location not found in the United States.";
          return;
        }
        var d = res.d;
        var label = (d.geocode && d.geocode.label) || q;
        if (pin) map.removeLayer(pin);
        pin = L.circleMarker([d.lat, d.lon], { radius: 8, color: "#fff", weight: 2.5, fillColor: "#c8f189", fillOpacity: 1 }).addTo(map);
        map.setView([d.lat, d.lon], 14);
        history.replaceState(null, "", location.pathname + "#lat=" + d.lat.toFixed(5) + "&lon=" + d.lon.toFixed(5));
        if (statusEl) statusEl.textContent = "Live Federal X-Ray complete: " + label;
        renderXrayInto(outEl, d, null);
        updateActions(d.lat, d.lon, label, d);
      })
      .catch(function () {
        if (statusEl) statusEl.textContent = "Could not reach /api/xray from this host.";
      });
  }

  map.on("click", function (ev) {
    runAt(ev.latlng.lat, ev.latlng.lng, null, Math.max(map.getZoom(), 14));
  });

  if (form) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      runQuery(input.value);
    });
  }

  Array.prototype.forEach.call(document.querySelectorAll("[data-xray-preset]"), function (btn) {
    btn.addEventListener("click", function () {
      var coords = btn.getAttribute("data-xray-preset").split(",");
      var lbl = btn.getAttribute("data-xray-label") || "";
      if (input) input.value = lbl;
      runAt(parseFloat(coords[0]), parseFloat(coords[1]), lbl, 14);
    });
  });

  // Boot from URL hash #lat=..&lon=.. or ?lat=..&lon=..
  var h = location.hash.slice(1) || location.search.slice(1);
  var mLat = h.match(/(?:^|&)lat=([^&]+)/);
  var mLon = h.match(/(?:^|&)lon=([^&]+)/);
  var mQ = h.match(/(?:^|&)q=([^&]+)/);
  if (mLat && mLon) {
    runAt(parseFloat(mLat[1]), parseFloat(mLon[1]), null, 14);
  } else if (mQ) {
    var qv = decodeURIComponent(mQ[1].replace(/\+/g, " "));
    if (input) input.value = qv;
    runQuery(qv);
  }
})();

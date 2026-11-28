/* Zillow-for-Land split-screen map explorer: Buy It Now vs. Auction vs. Land Bank switcher,
   seamless live merge of Direct Owner/Agent listings (/api/listings/), viewport search, shortlist CSV export, & comparison. */
(function () {
  "use strict";
  var box = document.getElementById("map");
  if (!box || !window.L) return;
  var base = document.body.getAttribute("data-base") || "";
  var form = document.getElementById("filters");
  var countEl = document.getElementById("map-count");
  var results = document.getElementById("results");
  var scope = box.getAttribute("data-scope");
  var KIND = { application: "Program price", asking: "Asking price", cash: "Buy It Now", min_bid: "Auction · Min bid", none: "Offer / app" };
  var STATUS = { availability_unverified: "Sale availability unconfirmed",
    listed: "Buy / Apply", auction_open: "Auction open", auction_terms: "Auction terms",
    proposal_open: "Proposals open", pending: "Sale pending", auction_closed: "Closed"
  };
  var rows = [], byId = Object.create(null), first = true, lastShown = [];
  var area = [], areaMatch = null, drawControl;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function money(v) {
    return v == null ? "" : "$" + (Math.abs(v - Math.round(v)) < 0.005
      ? Math.round(v).toLocaleString("en-US")
      : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  }
  function acres(a) { return a ? (Math.round(a * 100) / 100) + " ac" : ""; }
  function colour(r) {
    if (!r[8]) return "#8b938c";
    if (r[13]) return r[5] === "min_bid" ? "#ea580c" : "#16a34a";
    return r[5] === "min_bid" ? "#b5602f" : (r[5] === "cash" ? "#1d6f42" : "#2f7d6e");
  }
  function parcelHref(r) {
    return r[13] ? (base + "/direct/?id=" + encodeURIComponent(r[0])) : (base + "/land/" + r[0] + "/");
  }

  // Local shortlist & comparison
  function loadList(key) { try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch (e) { return []; } }
  function saveList(key, arr) { try { localStorage.setItem(key, JSON.stringify(arr)); } catch (e) {} }
  var savedIds = loadList("landosaur_saved");
  var compareIds = loadList("landosaur_compare");

  function toggleSaved(id) {
    var i = savedIds.indexOf(id);
    if (i >= 0) savedIds.splice(i, 1); else savedIds.push(id);
    saveList("landosaur_saved", savedIds);
    updateDock();
    renderCards(lastShown);
  }
  function toggleCompare(id) {
    var i = compareIds.indexOf(id);
    if (i >= 0) compareIds.splice(i, 1);
    else if (compareIds.length < 4) compareIds.push(id);
    saveList("landosaur_compare", compareIds);
    updateDock();
    renderCards(lastShown);
  }

  var streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxNativeZoom: 19, maxZoom: 20, attribution: "&copy; OpenStreetMap contributors" });
  var topo = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 20, attribution: "USGS The National Map" });
  var aerial = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 20, attribution: "USGS The National Map: imagery" });
  var fema = L.tileLayer.wms("https://hazards.fema.gov/arcgis/services/public/NFHLWMS/MapServer/WMSServer", {
    layers: "28", format: "image/png", transparent: true, opacity: 0.45, maxZoom: 20, attribution: "FEMA NFHL"
  });
  var shade = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSShadedReliefOnly/MapServer/tile/{z}/{y}/{x}", {
    maxNativeZoom: 16, maxZoom: 20, attribution: "USGS 3DEP and GMTED2010",
  });
  var cover = L.tileLayer.wms("https://www.mrlc.gov/geoserver/mrlc_Land-Cover-Native_conus_year_data/wms", {
    layers: "Land-Cover-Native_conus_year_data", format: "image/png", transparent: true, opacity: 0.60,
    time: "2025-01-01", maxNativeZoom: 15, maxZoom: 20, attribution: "USGS Annual NLCD 2025, contiguous U.S.",
  });
  function arcgisOverlay(service, options) {
    const ExportLayer = L.TileLayer.extend({
      getTileUrl(coords) {
        const size = this.getTileSize();
        const top = this._map.options.crs.transformation.untransform(coords.scaleBy(size), this._map.options.crs.scale(coords.z));
        const bottom = this._map.options.crs.transformation.untransform(coords.add([1, 1]).scaleBy(size), this._map.options.crs.scale(coords.z));
        const query = new URLSearchParams({ f: "image", bbox: [top.x, bottom.y, bottom.x, top.y].join(","),
          bboxSR: "3857", imageSR: "3857", size: size.x + "," + size.y, format: "png32", transparent: "true", layers: "show:0" });
        return service + "/export?" + query;
      },
    });
    return new ExportLayer(service, options);
  }
  var publicLandsOverview = arcgisOverlay("https://edits.nationalmap.gov/arcgis/rest/services/PAD-US/PAD_US_4_1/MapServer", {
    opacity: 0.55, maxNativeZoom: 8, maxZoom: 20,
  });
  var publicLands = L.layerGroup([], { attribution: "USGS PAD-US 4.1 fee-managed lands" });
  var publicLandsBoundaries = L.geoJSON(null, {
    renderer: L.svg(), interactive: false,
    style: { className: "pad-us-boundary", color: "#286c46", weight: 1.5, fillOpacity: 0.25 },
    coordsToLatLng: ([lon, lat]) => L.latLng(lat, lon + 360 * Math.round((map.getCenter().lng - lon) / 360)),
  });
  var publicLandsNotice = L.control({ position: "bottomleft" });
  var publicLandsMessage = el("div", "map-overlay-status");
  publicLandsMessage.setAttribute("role", "status");
  publicLandsMessage.hidden = true;
  publicLandsNotice.onAdd = () => publicLandsMessage;
  var publicLandsRequest;

  function showPublicLandsMessage(message) {
    publicLandsMessage.textContent = message;
    publicLandsMessage.hidden = !message;
  }

  async function loadPublicLands() {
    publicLandsRequest?.abort();
    publicLandsBoundaries.clearLayers();
    if (map.getZoom() < 9) {
      publicLands.addLayer(publicLandsOverview);
      showPublicLandsMessage("Zoom in to inspect individual protected areas.");
      return;
    }
    publicLands.removeLayer(publicLandsOverview).addLayer(publicLandsBoundaries);
    showPublicLandsMessage("");
    const request = new AbortController();
    publicLandsRequest = request;
    const timeout = setTimeout(() => request.abort(), 10000);
    const bounds = map.getBounds();
    const width = bounds.getEast() - bounds.getWest();
    const west = map.wrapLatLng(bounds.getSouthWest()).lng;
    const east = west + width;
    const ranges = east > 180 ? [[west, 180], [-180, east - 360]] : [[west, east]];
    const endpoint = "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Fee_Managers_PADUS/FeatureServer/0/query";
    const limit = 600;
    try {
      const collections = await Promise.all(ranges.map(async ([left, right]) => {
        const query = new URLSearchParams({
          f: "geojson", where: "FeatClass = 'Fee' AND Mang_Type IN ('FED','STAT','LOC','DIST','TERR')",
          geometry: [left, bounds.getSouth(), right, bounds.getNorth()].map(value => value.toFixed(5)).join(","),
          geometryType: "esriGeometryEnvelope", spatialRel: "esriSpatialRelIntersects", inSR: "4326", outSR: "4326",
          outFields: "OBJECTID", returnGeometry: "true", orderByFields: "Shape__Area DESC,OBJECTID ASC",
          maxAllowableOffset: (width / map.getSize().x / 2).toFixed(7), resultRecordCount: String(limit),
        });
        const response = await fetch(endpoint + "?" + query, { signal: request.signal });
        if (!response.ok) throw new Error("PAD-US request failed");
        const collection = await response.json();
        if (collection.type !== "FeatureCollection" || !Array.isArray(collection.features)) {
          throw new Error("Invalid PAD-US feature collection");
        }
        return collection;
      }));
      if (publicLandsRequest !== request || request.signal.aborted) return;
      for (const collection of collections) publicLandsBoundaries.addData(collection);
      if (collections.some(collection => collection.features.length >= limit)) {
        showPublicLandsMessage("Zoom in to see smaller protected areas.");
      }
    } catch {
      if (publicLandsRequest === request && map.hasLayer(publicLands) && map.getZoom() >= 9) {
        showPublicLandsMessage("Public lands data is temporarily unavailable. Move the map to retry.");
      }
    } finally {
      clearTimeout(timeout);
    }
  }
  publicLands.on("add", () => {
    publicLandsNotice.addTo(map);
    map.on("moveend", loadPublicLands);
    loadPublicLands();
  });
  publicLands.on("remove", () => {
    publicLandsRequest?.abort();
    publicLandsRequest = undefined;
    publicLandsNotice.remove();
    map.off("moveend", loadPublicLands);
    publicLands.clearLayers();
  });
  var wetlands = arcgisOverlay("https://fwsprimary.wim.usgs.gov/server/rest/services/Wetlands/MapServer", {
    opacity: 0.58, minZoom: 11, maxNativeZoom: 16, maxZoom: 20, attribution: "USFWS National Wetlands Inventory",
  });
  var map = L.map(box, {
    preferCanvas: true,
    scrollWheelZoom: true,
    doubleClickZoom: true,
    touchZoom: true,
    boxZoom: true,
    minZoom: 3,
    maxZoom: 20,
    wheelPxPerZoomLevel: 80,
    layers: [streets]
  }).setView([38.5, -96], 4);
  L.control.layers({ "Streets": streets, "USGS Aerial": aerial, "USGS Topo": topo, "USGS 3DEP Hillshade": shade }, {
    "FEMA Flood Zones": fema, "NLCD Land Cover (2025, lower 48)": cover, "PAD-US Managed Public Lands": publicLands,
    "USFWS Wetlands (zoom in)": wetlands,
  }).addTo(map);
  var cluster = L.markerClusterGroup({
    chunkedLoading: true,
    showCoverageOnHover: false,
    zoomToBoundsOnClick: true,
    spiderfyOnMaxZoom: true,
    disableClusteringAtZoom: 14,
    maxClusterRadius: 42
  });
  map.addLayer(cluster);
  var lastBounds = [];

  // Custom map toolbar control: Fit Results + Expand Full-Screen Map
  var MapTools = L.Control.extend({
    options: { position: "topleft" },
    onAdd: function () {
      var wrap = L.DomUtil.create("div", "leaflet-bar lando-map-tools");
      L.DomEvent.disableClickPropagation(wrap);
      L.DomEvent.disableScrollPropagation(wrap);
      var fitBtn = L.DomUtil.create("a", "lando-tool-btn", wrap);
      fitBtn.href = "#";
      fitBtn.title = "Zoom to fit matching parcels";
      fitBtn.setAttribute("aria-label", "Zoom to fit matching parcels");
      fitBtn.textContent = "Fit";
      fitBtn.addEventListener("click", function (ev) {
        ev.preventDefault();
        if (lastBounds.length) {
          map.fitBounds(L.latLngBounds(lastBounds), { padding: [26, 26], maxZoom: 16 });
        } else {
          map.setView([38.5, -96], 4);
        }
      });
      var fsBtn = L.DomUtil.create("a", "lando-tool-btn", wrap);
      fsBtn.href = "#";
      fsBtn.title = "Expand map full screen";
      fsBtn.setAttribute("aria-label", "Toggle full-screen map");
      fsBtn.textContent = "⛶";
      var col = box.closest(".explorer-map-col") || box;
      function toggleFs(forceOff) {
        var on = forceOff ? false : !col.classList.contains("map-fullscreen");
        col.classList.toggle("map-fullscreen", on);
        document.body.classList.toggle("map-fs-open", on);
        fsBtn.textContent = on ? "✕" : "⛶";
        fsBtn.title = on ? "Exit full-screen map (Esc)" : "Expand map full screen";
        setTimeout(function () { map.invalidateSize(); }, 80);
      }
      fsBtn.addEventListener("click", function (ev) { ev.preventDefault(); toggleFs(false); });
      document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape" && col.classList.contains("map-fullscreen")) toggleFs(true);
      });
      const drawing = L.DomUtil.create("div", "map-draw-tools", wrap);
      drawing.innerHTML = '<button type="button" data-draw-start>Draw area</button>' +
        '<select data-draw-shape aria-label="Search area shape"><option value="polygon">Polygon</option><option value="rectangle">Rectangle</option></select>' +
        '<button type="button" data-draw-undo>Undo</button><button type="button" data-draw-finish>Finish</button>' +
        '<button type="button" data-draw-clear>Clear area</button><small data-draw-status aria-live="polite"></small>';
      drawControl = LandosaurGeo.drawer(map, drawing, function (geometry, points) {
        area = points;
        areaMatch = geometry ? LandosaurGeo.matcher(points) : null;
        if (!first) apply(false);
      });
      return wrap;
    }
  });
  map.addControl(new MapTools());

  function hashState() {
    return Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
  }
  function readForm() {
    return {
      state: form.state.value,
      kind: form.kind.value,
      max: parseFloat(form.max.value),
      acres: parseFloat(form.acres.value),
      q: form.q.value.trim().toLowerCase(),
      sort: form.sort ? form.sort.value : "default",
      closed: form.closed.checked,
      belowBench: form.belowBench ? form.belowBench.checked : false,
      inview: form.inview ? form.inview.checked : false,
      savedOnly: form.savedOnly ? form.savedOnly.checked : false,
    };
  }
  function writeHash(f) {
    var parts = [];
    if (f.state && f.state !== scope) parts.push("state=" + f.state);
    if (f.kind) parts.push("kind=" + f.kind);
    if (!isNaN(f.max)) parts.push("max=" + f.max);
    if (!isNaN(f.acres)) parts.push("acres=" + f.acres);
    if (f.q) parts.push("q=" + encodeURIComponent(f.q));
    if (f.sort && f.sort !== "default") parts.push("sort=" + f.sort);
    if (f.closed) parts.push("closed=1");
    if (f.belowBench) parts.push("deals=1");
    if (f.inview) parts.push("inview=1");
    if (f.savedOnly) parts.push("saved=1");
    if (area.length) parts.push("area=" + encodeURIComponent(LandosaurGeo.encode(area)));
    history.replaceState(null, "", parts.length ? "#" + parts.join("&") : location.pathname + location.search);
  }
  function popup(r) {
    var d = el("div", "pop");
    var a = el("a", null, r[9]); a.href = parcelHref(r); d.appendChild(a);
    var bits = [r[13] ? (r[5] === "min_bid" ? "Direct Auction" : "Direct Buy It Now") : (STATUS[r[7]] || r[7])];
    if (r[4] != null) bits.push((KIND[r[5]] || "Price") + " " + money(r[4]));
    if (r[6]) bits.push(acres(r[6]));
    if (r[4] != null && r[6] > 0) bits.push(money(r[4] / r[6]) + "/ac");
    if (r[14] != null && r[14] <= -5) bits.push(Math.abs(r[14]) + "% below county avg");
    if (r[12]) bits.push("closes " + r[12]);
    d.appendChild(el("p", null, bits.join(" · ")));
    return d;
  }

  function sortRows(list, mode) {
    list.sort(function (a, b) {
      if (mode === "discount_desc") {
        var da = a[14] == null ? 999999 : a[14], db = b[14] == null ? 999999 : b[14];
        return da - db || (a[4] == null ? 1e15 : a[4]) - (b[4] == null ? 1e15 : b[4]);
      }
      if (mode === "price_asc") {
        var pa = a[4] == null ? 1e15 : a[4], pb = b[4] == null ? 1e15 : b[4];
        return pa - pb || (a[9] < b[9] ? -1 : 1);
      }
      if (mode === "price_desc") {
        var qa = a[4] == null ? -1 : a[4], qb = b[4] == null ? -1 : b[4];
        return qb - qa || (a[9] < b[9] ? -1 : 1);
      }
      if (mode === "acres_desc") {
        return (b[6] || 0) - (a[6] || 0) || (a[9] < b[9] ? -1 : 1);
      }
      if (mode === "ppa_asc") {
        var ra = (a[4] > 0 && a[6] > 0) ? a[4] / a[6] : 1e15;
        var rb = (b[4] > 0 && b[6] > 0) ? b[4] / b[6] : 1e15;
        return ra - rb || (a[9] < b[9] ? -1 : 1);
      }
      if (mode === "deadline") {
        return ((a[12] || "9999") < (b[12] || "9999") ? -1 : (a[12] || "9999") > (b[12] || "9999") ? 1 : 0) || (a[9] < b[9] ? -1 : 1);
      }
      // Default ("Recommended"): direct listings first, then active mapped parcels with published price & stated acreage, then closing soonest
      var sa = (a[13] ? 1000 : 0) + (a[8] ? 100 : 0) + (a[4] != null && a[4] > 0 ? 40 : 0) + (a[6] > 0 ? 30 : 0) + (a[1] != null ? 15 : 0) + (a[5] === "cash" ? 10 : 0);
      var sb = (b[13] ? 1000 : 0) + (b[8] ? 100 : 0) + (b[4] != null && b[4] > 0 ? 40 : 0) + (b[6] > 0 ? 30 : 0) + (b[1] != null ? 15 : 0) + (b[5] === "cash" ? 10 : 0);
      if (sb !== sa) return sb - sa;
      return ((a[12] || "9999") < (b[12] || "9999") ? -1 : (a[12] || "9999") > (b[12] || "9999") ? 1 : 0) ||
        (a[9] < b[9] ? -1 : 1);
    });
  }

  function renderCards(shown) {
    results.textContent = "";
    var ul = el("ul", "cards");
    var cap = 60;
    shown.slice(0, cap).forEach(function (r) {
      var li = el("li", "parcel-card");
      var top = el("div", "card-top");
      var isAuc = r[5] === "min_bid" || r[7] === "auction_open" || r[7] === "auction_terms";
      var badgeCls = !r[8] ? "off" : (isAuc ? "auction" : "ok");
      var badgeText;
      if (r[13]) {
        badgeText = (r[5] === "min_bid" ? "Direct Auction · " : "Direct Buy It Now · ") + money(r[4]);
      } else if (r[4] != null) {
        badgeText = (KIND[r[5]] || "Price") + " " + money(r[4]);
      } else {
        badgeText = isAuc ? "Auction · See terms" : (STATUS[r[7]] || r[7]);
      }
      top.appendChild(el("span", "badge " + badgeCls, badgeText));
      if (r[14] != null && r[14] <= -5) {
        top.appendChild(el("span", "badge ok", Math.abs(r[14]) + "% below county avg"));
      }
      if (r[6]) {
        var metric = acres(r[6]);
        if (r[4] != null && r[6] > 0) metric += " · " + money(r[4] / r[6]) + "/ac";
        top.appendChild(el("span", "card-metric", metric));
      }
      li.appendChild(top);
      var a = el("a", "card-title", r[9]);
      a.href = parcelHref(r);
      li.appendChild(a);
      var meta = [r[10] + ", " + r[3], r[13] ? "Direct Owner / Agent" : (STATUS[r[7]] || r[7])];
      if (r[12]) meta.push("closes " + r[12]);
      li.appendChild(el("span", "sub", meta.join(" · ")));

      var acts = el("div", "card-acts");
      var cta = el("a", "chip-btn chip-link", r[13] ? (r[5] === "min_bid" ? "Bid Now →" : "Buy Now →") : (isAuc ? "Bid Info →" : "Details →"));
      cta.href = parcelHref(r);
      acts.appendChild(cta);
      if (!r[13] && r[8]) {
        var agQ = "?parcel=" + encodeURIComponent(r[0]) + "&title=" + encodeURIComponent(r[9]) +
          (r[4] != null ? "&price=" + r[4] : "") + (r[6] ? "&acres=" + r[6] : "") +
          "&county=" + encodeURIComponent(r[10] || "") + "&state=" + encodeURIComponent(r[3] || "") +
          (r[11] ? "&apn=" + encodeURIComponent(r[11]) : "") +
          (r[1] != null ? "&lat=" + r[1] + "&lon=" + r[2] : "") +
          "&mode=" + (isAuc ? "auction" : (r[5] === "cash" ? "buy_now" : "landbank"));
        var agBtn = el("a", "chip-btn chip-link", "Land Agent ($20)");
        agBtn.href = base + "/services/" + agQ;
        agBtn.setAttribute("data-vital-event", "offer_clicked");
        acts.appendChild(agBtn);
      }
      var isSaved = savedIds.indexOf(r[0]) >= 0;
      var sBtn = el("button", "chip-btn" + (isSaved ? " on" : ""), isSaved ? "Saved ★" : "Save ☆");
      sBtn.type = "button";
      sBtn.addEventListener("click", function () { toggleSaved(r[0]); });
      var isCmp = compareIds.indexOf(r[0]) >= 0;
      var cBtn = el("button", "chip-btn" + (isCmp ? " on" : ""), isCmp ? "Comparing ✓" : "Compare");
      cBtn.type = "button";
      cBtn.addEventListener("click", function () { toggleCompare(r[0]); });
      acts.appendChild(sBtn);
      acts.appendChild(cBtn);
      if (r[1] != null) {
        var zBtn = el("button", "chip-btn", "Zoom");
        zBtn.type = "button";
        zBtn.addEventListener("click", function () {
          map.flyTo([r[1], r[2]], 17, { duration: 0.65 });
          L.popup({ maxWidth: 280 }).setLatLng([r[1], r[2]]).setContent(popup(r)).openOn(map);
        });
        acts.appendChild(zBtn);
        var xLink = el("a", "chip-btn chip-link", "X-Ray");
        xLink.href = base + "/xray/#lat=" + r[1] + "&lon=" + r[2];
        xLink.setAttribute("data-vital-event", "tool_used");
        acts.appendChild(xLink);
      }
      li.appendChild(acts);
      ul.appendChild(li);
    });
    results.appendChild(ul);
    if (shown.length > cap) {
      results.appendChild(el("p", "small", "Showing the first " + cap + " of " + shown.length.toLocaleString("en-US") + ". Narrow filters, sort, or pan the map to explore more."));
    } else if (!shown.length) {
      results.appendChild(el("p", "small", "No parcels match these filters. Clear a filter, zoom out, or list your own land free at /list/."));
    }
  }

  var MODE_LABELS = {
    "": "All Land",
    "cash": "Buy It Now",
    "min_bid": "Auction / Bid",
    "none": "Land Bank / Offer",
    "direct": "Direct Owner / Agent"
  };

  function syncModeTabs(kindVal, counts) {
    Array.prototype.forEach.call(document.querySelectorAll("[data-deal-mode]"), function (btn) {
      var mode = btn.getAttribute("data-deal-mode") || "";
      btn.classList.toggle("active", mode === (kindVal || ""));
      if (counts && MODE_LABELS[mode]) {
        var n = counts[mode] || 0;
        btn.textContent = MODE_LABELS[mode] + " (" + n.toLocaleString("en-US") + ")";
      }
    });
  }

  function apply(skipFit) {
    var f = readForm();
    writeHash(f);
    var mapBounds = (f.inview && !first) ? map.getBounds() : null;
    var shown = [], markers = [], bounds = [];
    var modeCounts = { "": 0, "cash": 0, "min_bid": 0, "none": 0, "direct": 0 };
    var now = Date.now();
    for (var i = 0; i < rows.length; i++) {
      var r = LandosaurAvailability.closeExpired(rows[i], now);
      if (rows[i] !== r) {
        rows[i] = r;
        byId[r[0]] = r;
      }
      if (f.state && r[3] !== f.state) continue;
      if (!f.closed && !r[8]) continue;
      if (!isNaN(f.max) && (r[4] == null || r[4] > f.max)) continue;
      if (!isNaN(f.acres) && (!r[6] || r[6] < f.acres)) continue;
      if (f.belowBench && (r[14] == null || r[14] >= 0)) continue;
      if (f.savedOnly && savedIds.indexOf(r[0]) < 0) continue;
      if (f.q && (r[9] + " " + r[10] + " " + r[11] + " " + r[3]).toLowerCase().indexOf(f.q) < 0) continue;
      if (areaMatch && !areaMatch(r[2], r[1])) continue;
      if (mapBounds) {
        if (r[1] == null || !mapBounds.contains([r[1], r[2]])) continue;
      }
      var isCash = r[5] === "cash";
      var isAuc = r[5] === "min_bid" || r[7] === "auction_open" || r[7] === "auction_terms";
      var isNone = !isCash && !isAuc;
      var isDirect = Boolean(r[13]);
      modeCounts[""]++;
      if (isCash) modeCounts.cash++;
      if (isAuc) modeCounts.min_bid++;
      if (isNone) modeCounts.none++;
      if (isDirect) modeCounts.direct++;

      if (f.kind === "cash" && !isCash) continue;
      else if (f.kind === "min_bid" && !isAuc) continue;
      else if (f.kind === "none" && !isNone) continue;
      else if (f.kind === "direct" && !isDirect) continue;
      shown.push(r);
      if (r[1] != null) {
        var m = L.circleMarker([r[1], r[2]], { radius: r[13] ? 8 : 6, color: "#fff", weight: 2, fillColor: colour(r), fillOpacity: 0.95 });
        m.bindPopup(popup.bind(null, r));
        markers.push(m);
        bounds.push([r[1], r[2]]);
      }
    }
    syncModeTabs(f.kind, modeCounts);
    lastBounds = bounds;
    if (!skipFit) {
      cluster.clearLayers();
      cluster.addLayers(markers);
    }
    if ((first || f.state !== apply.lastState) && !skipFit && !area.length) {
      if (f.state && bounds.length) map.fitBounds(L.latLngBounds(bounds), { padding: [22, 22], maxZoom: 15, animate: false });
      else map.setView([39, -96], 4, { animate: false });
    }
    first = false;
    apply.lastState = f.state;
    sortRows(shown, f.sort);
    lastShown = shown;
    countEl.textContent = shown.length.toLocaleString("en-US") + " listings match (" + markers.length.toLocaleString("en-US") + " mapped).";
    renderCards(shown);
  }

  // Deal-mode segmented switcher (All | Buy It Now | Auction / Bid | Land Bank / Offer | Direct)
  Array.prototype.forEach.call(document.querySelectorAll("[data-deal-mode]"), function (btn) {
    btn.addEventListener("click", function () {
      form.kind.value = btn.getAttribute("data-deal-mode") || "";
      apply(false);
    });
  });

  // Quick preset filter pills
  var presetBtns = Array.prototype.slice.call(document.querySelectorAll("[data-preset]"));
  presetBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var p = btn.getAttribute("data-preset");
      presetBtns.forEach(function (b) { b.classList.toggle("active", b === btn); });
      form.kind.value = "";
      form.max.value = "";
      form.acres.value = "";
      if (form.sort) form.sort.value = "default";
      if (form.belowBench) form.belowBench.checked = false;
      if (form.savedOnly) form.savedOnly.checked = false;
      if (p === "deals") {
        if (form.belowBench) form.belowBench.checked = true;
        if (form.sort) form.sort.value = "discount_desc";
      } else if (p === "cash") form.kind.value = "cash";
      else if (p === "min_bid") form.kind.value = "min_bid";
      else if (p === "direct") form.kind.value = "direct";
      else if (p === "acres5") { form.acres.value = "5"; if (form.sort) form.sort.value = "acres_desc"; }
      else if (p === "under5k") { form.max.value = "5000"; if (form.sort) form.sort.value = "price_asc"; }
      else if (p === "ppa") { if (form.sort) form.sort.value = "ppa_asc"; }
      else if (p === "saved" && form.savedOnly) { form.savedOnly.checked = true; }
      apply(false);
    });
  });

  // Comparison Dock + Shortlist CSV Export + Modal
  var dock = document.getElementById("compare-dock");
  var cmpModal = document.getElementById("compare-modal");
  function updateDock() {
    if (!dock) return;
    if (!savedIds.length && !compareIds.length) { dock.hidden = true; return; }
    dock.hidden = false;
    var sSpan = dock.querySelector("[data-saved-count]");
    var cSpan = dock.querySelector("[data-cmp-count]");
    if (sSpan) sSpan.textContent = savedIds.length;
    if (cSpan) cSpan.textContent = compareIds.length;
    var openBtn = dock.querySelector("[data-open-compare]");
    if (openBtn) openBtn.disabled = compareIds.length < 1;
  }
  function acquisitionHref(r) {
    const isAuction = r[5] === "min_bid" || r[7] === "auction_open" || r[7] === "auction_terms";
    const params = { parcel: r[0], title: r[9], county: r[10], state: r[3], apn: r[11],
      price: r[4], acres: r[6], lat: r[1], lon: r[2], service: r[13] ? "direct_closing" : null,
      mode: r[13] ? "direct" : isAuction ? "auction" : r[5] === "cash" ? "buy_now" : "landbank" };
    return base + "/services/?" + new URLSearchParams(Object.entries(params).filter((entry) => entry[1] != null)) + "#start-land-agent";
  }
  function openCompare() {
    if (!cmpModal) return;
    var items = compareIds.map(function (id) { return byId[id]; }).filter(Boolean);
    var body = cmpModal.querySelector("[data-cmp-body]");
    if (!items.length) { body.innerHTML = "<p>Select up to 4 listings to compare side by side.</p>"; }
    else {
      var cols = items.map(function (r) {
        return '<th><a href="' + escHtml(parcelHref(r)) + '">' + escHtml(r[9]) + '</a></th>';
      }).join("");
      function rowHtml(label, fn) {
        return '<tr><th scope="row">' + label + '</th>' + items.map(function (r) { return '<td>' + fn(r) + '</td>'; }).join("") + '</tr>';
      }
      body.innerHTML =
        '<div class="scroll"><table class="data"><thead><tr><th>Field</th>' + cols + '</tr></thead><tbody>' +
        rowHtml("Location", function (r) { return escHtml(r[10] + ", " + r[3]); }) +
        rowHtml("Deal Mode", function (r) { return r[13] ? (r[5] === "min_bid" ? "Direct Auction" : "Direct Buy It Now") : (STATUS[r[7]] || r[7]); }) +
        rowHtml("Price / Bid", function (r) { return r[4] != null ? (KIND[r[5]] + " " + money(r[4])) : "Not published"; }) +
        rowHtml("Acreage", function (r) { return r[6] ? acres(r[6]) : "Not stated"; }) +
        rowHtml("Implied $/acre", function (r) { return (r[4] > 0 && r[6] > 0) ? money(r[4] / r[6]) + "/ac" : "–"; }) +
        rowHtml("Deadline", function (r) { return escHtml(r[12] || "–"); }) +
        rowHtml("Analyze", function (r) {
          var q = "?id=" + encodeURIComponent(r[0]) + "&title=" + encodeURIComponent(r[9]) +
            (r[4] != null ? "&price=" + r[4] : "") + (r[6] ? "&acres=" + r[6] : "");
          return '<a href="' + base + '/analyze/' + q + '">Open in Analyzer →</a>';
        }) +
        '</tbody></table></div>';
      const available = items.filter((row) => row[8]);
      if (available.length) {
        const actions = document.createElement("div");
        actions.className = "compare-acquisition";
        const choice = document.createElement("select");
        choice.setAttribute("aria-label", "Choose a parcel for Land Agent");
        available.forEach((row, index) => choice.add(new Option(row[9], index)));
        const acquire = el("a", "button sm", "Acquire selected with Land Agent · $20 →");
        function update() { acquire.href = acquisitionHref(available[Number(choice.value)]); }
        choice.addEventListener("change", update);
        update();
        actions.append(choice, acquire);
        body.appendChild(actions);
      }
    }
    cmpModal.hidden = false;
  }
  if (dock) {
    var oBtn = dock.querySelector("[data-open-compare]");
    if (oBtn) oBtn.addEventListener("click", openCompare);
    var expBtn = dock.querySelector("[data-export-saved]");
    if (expBtn) expBtn.addEventListener("click", async function () {
      const format = document.getElementById("watchlist-format").value.toLowerCase();
      const status = dock.querySelector("[data-watchlist-status]");
      const shortlist = [...new Set(savedIds.concat(compareIds))].map((id) => byId[id]).filter(Boolean);
      if (!shortlist.length) { status.textContent = "No saved parcels remain in the inventory."; return; }
      expBtn.disabled = true;
      status.textContent = "Preparing " + shortlist.length + " parcels…";
      try {
        const items = shortlist.map((r) => ({
          id: r[0], title: r[9], state: r[3], county: r[10], status: STATUS[r[7]] || r[7],
          price_kind: r[5], price: r[4], acres: r[6], deadline: r[12], lat: r[1], lon: r[2],
          usd_per_acre: r[4] > 0 && r[6] > 0 ? Number((r[4] / r[6]).toFixed(2)) : null,
          url: new URL(parcelHref(r), location.href).href, rings: null,
        }));
        if (format !== "csv") {
          // Limit concurrent dossier reads. Only agency-supplied boundary arrays are copied.
          for (let i = 0; i < items.length; i += 6) {
            await Promise.all(items.slice(i, i + 6).map(async (item, offset) => {
              if (item.lat == null || shortlist[i + offset][13]) return;
              try {
                const response = await fetch(item.url, { signal: AbortSignal.timeout(6500) });
                if (!response.ok) return;
                const doc = new DOMParser().parseFromString(await response.text(), "text/html");
                const parcel = JSON.parse(doc.getElementById("parcel")?.textContent || "null");
                if (parcel?.slug === item.id) item.rings = parcel.geometry;
              } catch {}
            }));
          }
        }
        LandosaurWatchlist.download(items, format);
        const unmapped = items.filter((item) => item.lat == null && !item.rings?.length).length;
        status.textContent = "Exported " + items.length + " parcels." +
          (unmapped && format !== "csv" ? " " + unmapped + " without mapped coordinates." : "");
      } catch {
        status.textContent = "The watchlist export could not be prepared.";
      } finally {
        expBtn.disabled = false;
      }
    });
    var clrBtn = dock.querySelector("[data-clear-compare]");
    if (clrBtn) clrBtn.addEventListener("click", function () {
      compareIds = []; saveList("landosaur_compare", compareIds); updateDock(); renderCards(lastShown);
    });
  }
  if (cmpModal) {
    var xBtn = cmpModal.querySelector("[data-close-compare]");
    if (xBtn) xBtn.addEventListener("click", function () { cmpModal.hidden = true; });
  }

  // Save Search & Instant Land Alerts modal (POST /api/alerts/)
  var alertBtn = document.getElementById("open-alert-modal");
  var alertModal = document.getElementById("alert-modal");
  var alertForm = document.getElementById("alert-create-form");
  var alertSummary = document.getElementById("alert-filter-summary");
  var alertOut = document.getElementById("alert-modal-result");
  var alertSubmit = document.getElementById("alert-submit-btn");
  function escHtml(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function describeActiveFilter(f) {
    var parts = [];
    parts.push(f.state ? ("State: " + f.state) : "All 50 States");
    if (f.kind && MODE_LABELS[f.kind]) parts.push(MODE_LABELS[f.kind]);
    if (f.belowBench) parts.push("Below county USDA avg");
    if (!isNaN(f.max)) parts.push("Max " + money(f.max));
    if (!isNaN(f.acres)) parts.push(f.acres + "+ acres");
    if (f.q) parts.push('Keyword "' + f.q + '"');
    if (area.length) parts.push("Drawn search area");
    return parts.join(" · ");
  }
  if (alertBtn && alertModal) {
    alertBtn.addEventListener("click", function () {
      var f = readForm();
      if (alertSummary) {
        alertSummary.innerHTML =
          "<strong>Active Filter:</strong> " + escHtml(describeActiveFilter(f)) +
          "<br><span class='small'>Currently matching <strong>" + lastShown.length.toLocaleString("en-US") + "</strong> parcels.</span>";
      }
      if (alertOut) { alertOut.hidden = true; alertOut.textContent = ""; }
      alertModal.hidden = false;
    });
    var closeAlert = alertModal.querySelector("[data-close-alert]");
    if (closeAlert) closeAlert.addEventListener("click", function () { alertModal.hidden = true; });
  }
  if (alertForm && alertOut) {
    alertForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var f = readForm();
      alertSubmit.disabled = true;
      alertSubmit.textContent = "Creating alert & live feed…";
      alertOut.hidden = false;
      alertOut.textContent = "Saving filter to Landosaur Alert Desk…";
      fetch(base + "/api/alerts/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          state: f.state || "",
          mode: f.kind || "",
          max_price: isNaN(f.max) ? null : f.max,
          min_acres: isNaN(f.acres) ? null : f.acres,
          below_benchmark: Boolean(f.belowBench),
          q: f.q || "",
          area: area.length ? LandosaurGeo.encode(area) : undefined,
          label: alertForm.label.value.trim(),
          buyer_email: alertForm.buyer_email.value.trim(),
          website_hp: alertForm.website_hp ? alertForm.website_hp.value : "",
        }),
      })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok || !res.d || !res.d.ok) {
            alertOut.innerHTML = "<strong>Could not create alert:</strong> " + escHtml((res.d && res.d.error) || "Please try again.");
            return;
          }
          var d = res.d;
          alertOut.innerHTML =
            "<h3 style='margin:0 0 6px'>Saved Search Active · <code>" + escHtml(d.alert_id) + "</code></h3>" +
            "<p class='small' style='margin:0 0 10px'>" + escHtml(d.message) + "</p>" +
            "<p style='margin:6px 0'><strong>Live Atom/RSS Feed:</strong><br><a href='" + escHtml(d.atom_feed_url) + "' target='_blank' rel='noopener'><code>" + escHtml(d.atom_feed_url) + "</code></a></p>" +
            "<p style='margin:6px 0'><strong>Live JSON Feed:</strong><br><a href='" + escHtml(d.json_feed_url) + "' target='_blank' rel='noopener'><code>" + escHtml(d.json_feed_url) + "</code></a></p>" +
            "<p style='margin-top:12px'><a class='button sm' href='" + escHtml(d.land_agent_url) + "' data-vital-event='offer_clicked'>Or Hire Land Agent ($20) to Hunt Off-Market Matches →</a></p>";
        })
        .catch(function () {
          alertOut.textContent = "Network error creating saved alert. Please try again.";
        })
        .finally(function () {
          alertSubmit.disabled = false;
          alertSubmit.textContent = "Create Live Alert & Custom Feed →";
        });
    });
  }

  map.on("moveend", function () {
    if (form.inview && form.inview.checked) apply(true);
  });

  var h = hashState();
  if (h.area && drawControl) {
    const points = LandosaurGeo.decode(h.area);
    if (drawControl.set(points)) {
      area = points;
      areaMatch = LandosaurGeo.matcher(points);
      const origin = points[0][0];
      const vertices = points.map(([lon, lat]) => [lat, origin + ((lon - origin + 540) % 360) - 180]);
      map.fitBounds(vertices, { padding: [20, 20], maxZoom: 15, animate: false });
    }
  }
  if (scope && scope !== "all") form.state.value = scope;
  if (h.state) form.state.value = h.state;
  if (h.kind) form.kind.value = h.kind;
  if (h.max) form.max.value = h.max;
  if (h.acres) form.acres.value = h.acres;
  if (h.q) form.q.value = h.q;
  if (h.sort && form.sort) form.sort.value = h.sort;
  if (h.closed) form.closed.checked = true;
  if (h.deals && form.belowBench) form.belowBench.checked = true;
  if (h.inview && form.inview) form.inview.checked = true;
  if (h.saved && form.savedOnly) form.savedOnly.checked = true;

  form.addEventListener("input", function () { clearTimeout(apply.t); apply.t = setTimeout(function () { apply(false); }, 180); });
  form.addEventListener("change", function () { apply(false); });

  countEl.textContent = "Loading listings…";
  var directFetch = fetch(base + "/api/listings/").then(function (r) { return r.ok ? r.json() : { listings: [] }; }).catch(function () { return { listings: [] }; });
  Promise.all([
    fetch(base + "/data/map.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }),
    directFetch,
  ])
    .then(function (pair) {
      var staticRows = pair[0].rows || [];
      var directItems = (pair[1] && pair[1].listings) || [];
      var directRows = directItems.map(function (it) {
        return [
          it.id, it.lat, it.lon, it.state, it.price,
          it.sale_mode === "auction" ? "min_bid" : "cash", it.acres,
          it.sale_mode === "auction" ? "auction_open" : "listed",
          it.status === "active" ? 1 : 0, it.title, it.county || "",
          it.apn || "", (it.deadline || "").slice(0, 10), 1, null,
          it.sale_mode === "auction" ? Date.parse(it.deadline) : null
        ];
      });
      rows = directRows.concat(staticRows);
      for (var i = 0; i < rows.length; i++) byId[rows[i][0]] = rows[i];
      updateDock();
      apply(false);
    })
    .catch(function () { countEl.textContent = "The listings could not be loaded. Use the state pages below."; });
})();

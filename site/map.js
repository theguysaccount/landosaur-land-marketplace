/* Zillow-for-Land split-screen map explorer, sort/viewport filters, local shortlist & parcel comparison. */
(function () {
  "use strict";
  var box = document.getElementById("map");
  if (!box || !window.L) return;
  var base = document.body.getAttribute("data-base") || "";
  var form = document.getElementById("filters");
  var countEl = document.getElementById("map-count");
  var results = document.getElementById("results");
  var scope = box.getAttribute("data-scope");
  var KIND = { cash: "Fixed price", min_bid: "Min bid", none: "Offer / app" };
  var STATUS = {
    listed: "Listed", auction_open: "Bidding open", auction_terms: "Auction terms",
    proposal_open: "Proposals open", pending: "Sale pending", auction_closed: "Closed"
  };
  var rows = [], byId = {}, first = true, lastShown = [];

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
  function acres(a) { return a ? (Math.round(a * 100) / 100) + (a === 1 ? " ac" : " ac") : ""; }
  function colour(r) { return !r[8] ? "#8b938c" : (r[5] === "min_bid" ? "#b5602f" : (r[5] === "cash" ? "#1d6f42" : "#2f7d6e")); }

  // Local shortlist & comparison (no accounts, no cookies)
  function loadList(key) {
    try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch (e) { return []; }
  }
  function saveList(key, arr) {
    try { localStorage.setItem(key, JSON.stringify(arr)); } catch (e) {}
  }
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

  // Base maps + optional FEMA flood overlay
  var streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" });
  var topo = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16, attribution: "USGS The National Map" });
  var aerial = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16, attribution: "USGS The National Map: imagery" });
  var fema = L.tileLayer.wms("https://hazards.fema.gov/arcgis/services/public/NFHL/MapServer/WMSServer", {
    layers: "28", format: "image/png", transparent: true, opacity: 0.45, attribution: "FEMA NFHL"
  });
  var map = L.map(box, { preferCanvas: true, scrollWheelZoom: false, layers: [streets] }).setView([38.5, -96], 4);
  L.control.layers({ "Streets": streets, "USGS Topo": topo, "USGS Aerial": aerial }, { "FEMA Flood Zones": fema }).addTo(map);
  map.on("focus", function () { map.scrollWheelZoom.enable(); });
  var cluster = L.markerClusterGroup({ chunkedLoading: true, showCoverageOnHover: false, maxClusterRadius: 48 });
  map.addLayer(cluster);

  function hashState() {
    var out = {};
    (location.hash.slice(1) || "").split("&").forEach(function (kv) {
      var p = kv.split("=");
      if (p[0]) out[decodeURIComponent(p[0])] = decodeURIComponent(p[1] || "");
    });
    return out;
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
    if (f.inview) parts.push("inview=1");
    if (f.savedOnly) parts.push("saved=1");
    history.replaceState(null, "", parts.length ? "#" + parts.join("&") : location.pathname + location.search);
  }
  function popup(r) {
    var d = el("div", "pop");
    var a = el("a", null, r[9]); a.href = base + "/land/" + r[0] + "/"; d.appendChild(a);
    var bits = [STATUS[r[7]] || r[7]];
    if (r[4] != null) bits.push((KIND[r[5]] || "Price") + " " + money(r[4]));
    if (r[6]) bits.push(acres(r[6]));
    if (r[4] != null && r[6] > 0) bits.push(money(r[4] / r[6]) + "/ac");
    if (r[12]) bits.push("closes " + r[12]);
    d.appendChild(el("p", null, bits.join(" · ")));
    return d;
  }

  function sortRows(list, mode) {
    list.sort(function (a, b) {
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
      // Default: active first, then priced/closing soonest, then alphabetical
      return (b[8] - a[8]) || ((a[12] || "9999") < (b[12] || "9999") ? -1 : (a[12] || "9999") > (b[12] || "9999") ? 1 : 0) ||
        ((a[4] != null ? 0 : 1) - (b[4] != null ? 0 : 1)) || (a[9] < b[9] ? -1 : 1);
    });
  }

  function renderCards(shown) {
    results.textContent = "";
    var ul = el("ul", "cards");
    var cap = 60;
    shown.slice(0, cap).forEach(function (r) {
      var li = el("li", "parcel-card");
      var top = el("div", "card-top");
      var badgeCls = !r[8] ? "off" : (r[5] === "min_bid" ? "auction" : "ok");
      top.appendChild(el("span", "badge " + badgeCls, r[4] != null ? (KIND[r[5]] + " " + money(r[4])) : (STATUS[r[7]] || r[7])));
      if (r[6]) {
        var metric = acres(r[6]);
        if (r[4] != null && r[6] > 0) metric += " · " + money(r[4] / r[6]) + "/ac";
        top.appendChild(el("span", "card-metric", metric));
      }
      li.appendChild(top);
      var a = el("a", "card-title", r[9]);
      a.href = base + "/land/" + r[0] + "/";
      li.appendChild(a);
      var meta = [r[10] + ", " + r[3], STATUS[r[7]] || r[7]];
      if (r[12]) meta.push("closes " + r[12]);
      li.appendChild(el("span", "sub", meta.join(" · ")));

      var acts = el("div", "card-acts");
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
        zBtn.addEventListener("click", function () { map.setView([r[1], r[2]], 15); });
        acts.appendChild(zBtn);
      }
      li.appendChild(acts);
      ul.appendChild(li);
    });
    results.appendChild(ul);
    if (shown.length > cap) {
      results.appendChild(el("p", "small", "Showing the first " + cap + " of " + shown.length.toLocaleString("en-US") + ". Narrow filters, sort, or pan the map to explore more."));
    } else if (!shown.length) {
      results.appendChild(el("p", "small", "No parcels match these filters. Clear a filter or zoom out to see more official offerings."));
    }
  }

  function apply(skipFit) {
    var f = readForm();
    writeHash(f);
    var mapBounds = (f.inview && !first) ? map.getBounds() : null;
    var shown = [], markers = [], bounds = [];
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (f.state && r[3] !== f.state) continue;
      if (!f.closed && !r[8]) continue;
      if (f.kind && r[5] !== f.kind) continue;
      if (!isNaN(f.max) && (r[4] == null || r[4] > f.max)) continue;
      if (!isNaN(f.acres) && (!r[6] || r[6] < f.acres)) continue;
      if (f.savedOnly && savedIds.indexOf(r[0]) < 0) continue;
      if (f.q && (r[9] + " " + r[10] + " " + r[11] + " " + r[3]).toLowerCase().indexOf(f.q) < 0) continue;
      if (mapBounds) {
        if (r[1] == null || !mapBounds.contains([r[1], r[2]])) continue;
      }
      shown.push(r);
      if (r[1] != null) {
        var m = L.circleMarker([r[1], r[2]], { radius: 6, color: "#fff", weight: 2, fillColor: colour(r), fillOpacity: 0.95 });
        m.bindPopup(popup.bind(null, r));
        markers.push(m);
        bounds.push([r[1], r[2]]);
      }
    }
    if (!skipFit) {
      cluster.clearLayers();
      cluster.addLayers(markers);
    }
    if ((first || f.state !== apply.lastState) && !skipFit) {
      if (f.state && bounds.length) map.fitBounds(L.latLngBounds(bounds), { padding: [20, 20], maxZoom: 13, animate: false });
      else map.setView([39, -96], 4, { animate: false });
    }
    first = false;
    apply.lastState = f.state;
    sortRows(shown, f.sort);
    lastShown = shown;
    countEl.textContent = shown.length.toLocaleString("en-US") + " listings match (" + markers.length.toLocaleString("en-US") + " mapped).";
    renderCards(shown);
  }

  // Quick preset filter pills
  Array.prototype.forEach.call(document.querySelectorAll("[data-preset]"), function (btn) {
    btn.addEventListener("click", function () {
      var p = btn.getAttribute("data-preset");
      form.kind.value = "";
      form.max.value = "";
      form.acres.value = "";
      if (form.sort) form.sort.value = "default";
      if (form.savedOnly) form.savedOnly.checked = false;
      if (p === "cash") form.kind.value = "cash";
      else if (p === "min_bid") form.kind.value = "min_bid";
      else if (p === "acres5") { form.acres.value = "5"; if (form.sort) form.sort.value = "acres_desc"; }
      else if (p === "under5k") { form.max.value = "5000"; if (form.sort) form.sort.value = "price_asc"; }
      else if (p === "ppa") { if (form.sort) form.sort.value = "ppa_asc"; }
      else if (p === "saved" && form.savedOnly) { form.savedOnly.checked = true; }
      apply();
    });
  });

  // Comparison Dock + Modal
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
  function openCompare() {
    if (!cmpModal) return;
    var items = compareIds.map(function (id) { return byId[id]; }).filter(Boolean);
    var body = cmpModal.querySelector("[data-cmp-body]");
    if (!items.length) { body.innerHTML = "<p>Select up to 4 listings to compare side by side.</p>"; }
    else {
      var cols = items.map(function (r) {
        return '<th><a href="' + base + '/land/' + r[0] + '/">' + r[9] + '</a></th>';
      }).join("");
      function rowHtml(label, fn) {
        return '<tr><th scope="row">' + label + '</th>' + items.map(function (r) { return '<td>' + fn(r) + '</td>'; }).join("") + '</tr>';
      }
      body.innerHTML =
        '<div class="scroll"><table class="data"><thead><tr><th>Field</th>' + cols + '</tr></thead><tbody>' +
        rowHtml("Location", function (r) { return r[10] + ", " + r[3]; }) +
        rowHtml("Status", function (r) { return STATUS[r[7]] || r[7]; }) +
        rowHtml("Price / Bid", function (r) { return r[4] != null ? (KIND[r[5]] + " " + money(r[4])) : "Not published"; }) +
        rowHtml("Acreage", function (r) { return r[6] ? acres(r[6]) : "Not stated"; }) +
        rowHtml("Implied $/acre", function (r) { return (r[4] > 0 && r[6] > 0) ? money(r[4] / r[6]) + "/ac" : "–"; }) +
        rowHtml("Deadline", function (r) { return r[12] || "–"; }) +
        rowHtml("Analyze", function (r) {
          var q = "?id=" + encodeURIComponent(r[0]) + "&title=" + encodeURIComponent(r[9]) +
            (r[4] != null ? "&price=" + r[4] : "") + (r[6] ? "&acres=" + r[6] : "");
          return '<a href="' + base + '/analyze/' + q + '">Open in Analyzer →</a>';
        }) +
        '</tbody></table></div>';
    }
    cmpModal.hidden = false;
  }
  if (dock) {
    var oBtn = dock.querySelector("[data-open-compare]");
    if (oBtn) oBtn.addEventListener("click", openCompare);
    var clrBtn = dock.querySelector("[data-clear-compare]");
    if (clrBtn) clrBtn.addEventListener("click", function () {
      compareIds = []; saveList("landosaur_compare", compareIds); updateDock(); renderCards(lastShown);
    });
  }
  if (cmpModal) {
    var xBtn = cmpModal.querySelector("[data-close-compare]");
    if (xBtn) xBtn.addEventListener("click", function () { cmpModal.hidden = true; });
  }

  map.on("moveend", function () {
    if (form.inview && form.inview.checked) apply(true);
  });

  var h = hashState();
  if (scope && scope !== "all") form.state.value = scope;
  if (h.state) form.state.value = h.state;
  if (h.kind) form.kind.value = h.kind;
  if (h.max) form.max.value = h.max;
  if (h.acres) form.acres.value = h.acres;
  if (h.q) form.q.value = h.q;
  if (h.sort && form.sort) form.sort.value = h.sort;
  if (h.closed) form.closed.checked = true;
  if (h.inview && form.inview) form.inview.checked = true;
  if (h.saved && form.savedOnly) form.savedOnly.checked = true;

  form.addEventListener("input", function () { clearTimeout(apply.t); apply.t = setTimeout(function () { apply(false); }, 180); });
  form.addEventListener("change", function () { apply(false); });

  countEl.textContent = "Loading listings…";
  fetch(base + "/data/map.json")
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (d) {
      rows = d.rows;
      for (var i = 0; i < rows.length; i++) byId[rows[i][0]] = rows[i];
      updateDock();
      apply(false);
    })
    .catch(function () { countEl.textContent = "The listings could not be loaded. Use the state pages below."; });
})();

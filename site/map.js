/* Map-first browsing: every listing from data/map.json, filtered in the browser. No dependencies beyond Leaflet. */
(function () {
  "use strict";
  var box = document.getElementById("map");
  if (!box || !window.L) return;
  var base = document.body.getAttribute("data-base") || "";
  var form = document.getElementById("filters");
  var countEl = document.getElementById("map-count");
  var results = document.getElementById("results");
  var scope = box.getAttribute("data-scope");
  var KIND = { cash: "Price", min_bid: "Minimum bid", none: "" };
  var STATUS = { listed: "Listed", auction_open: "Bidding open", auction_terms: "Auction terms apply", proposal_open: "Proposals invited",
                 pending: "Sale pending", auction_closed: "Bidding closed" };
  var rows = [], fields = {}, first = true;

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function money(v) { return v == null ? "" : "$" + (Math.abs(v - Math.round(v)) < 0.005 ? Math.round(v).toLocaleString("en-US") : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })); }
  function acres(a) { return a ? (Math.round(a * 100) / 100) + (a === 1 ? " acre" : " acres") : ""; }
  function colour(r) { return !r[8] ? "#8b938c" : (r[5] === "min_bid" ? "#b5602f" : "#236b43"); }

  var streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" });
  var topo = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16, attribution: "USGS The National Map" });
  var aerial = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16, attribution: "USGS The National Map: imagery" });
  var map = L.map(box, { preferCanvas: true, scrollWheelZoom: false, layers: [streets] }).setView([38.5, -96], 4);
  L.control.layers({ "Streets": streets, "Topo (USGS)": topo, "Aerial (USGS)": aerial }).addTo(map);
  map.on("focus", function () { map.scrollWheelZoom.enable(); });
  var cluster = L.markerClusterGroup({ chunkedLoading: true, showCoverageOnHover: false, maxClusterRadius: 50 });
  map.addLayer(cluster);

  function hashState() {
    var out = {};
    (location.hash.slice(1) || "").split("&").forEach(function (kv) { var p = kv.split("="); if (p[0]) out[decodeURIComponent(p[0])] = decodeURIComponent(p[1] || ""); });
    return out;
  }
  function readForm() {
    return { state: form.state.value, kind: form.kind.value, max: parseFloat(form.max.value), acres: parseFloat(form.acres.value),
             q: form.q.value.trim().toLowerCase(), closed: form.closed.checked };
  }
  function writeHash(f) {
    var parts = [];
    if (f.state && f.state !== scope) parts.push("state=" + f.state);
    if (f.kind) parts.push("kind=" + f.kind);
    if (!isNaN(f.max)) parts.push("max=" + f.max);
    if (!isNaN(f.acres)) parts.push("acres=" + f.acres);
    if (f.q) parts.push("q=" + encodeURIComponent(f.q));
    if (f.closed) parts.push("closed=1");
    history.replaceState(null, "", parts.length ? "#" + parts.join("&") : location.pathname + location.search);
  }
  function popup(r) {
    var d = el("div", "pop");
    var a = el("a", null, r[9]); a.href = base + "/land/" + r[0] + "/"; d.appendChild(a);
    var bits = [STATUS[r[7]] || r[7]];
    if (r[4] != null) bits.push((KIND[r[5]] || "Price") + " " + money(r[4]));
    if (r[6]) bits.push(acres(r[6]));
    if (r[12]) bits.push("deadline " + r[12]);
    d.appendChild(el("p", null, bits.join(" · ")));
    return d;
  }
  function apply() {
    var f = readForm();
    writeHash(f);
    var shown = [], markers = [], bounds = [];
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (f.state && r[3] !== f.state) continue;
      if (!f.closed && !r[8]) continue;
      if (f.kind && r[5] !== f.kind) continue;
      if (!isNaN(f.max) && (r[4] == null || r[4] > f.max)) continue;
      if (!isNaN(f.acres) && (!r[6] || r[6] < f.acres)) continue;
      if (f.q && (r[9] + " " + r[10] + " " + r[11]).toLowerCase().indexOf(f.q) < 0) continue;
      shown.push(r);
      if (r[1] != null) {
        var m = L.circleMarker([r[1], r[2]], { radius: 6, color: "#fff", weight: 2, fillColor: colour(r), fillOpacity: 0.95 });
        m.bindPopup(popup.bind(null, r));
        markers.push(m);
        bounds.push([r[1], r[2]]);
      }
    }
    cluster.clearLayers();
    cluster.addLayers(markers);
    if (first || f.state !== apply.lastState) {
      if (f.state && bounds.length) map.fitBounds(L.latLngBounds(bounds), { padding: [20, 20], maxZoom: 14, animate: false });
      else map.setView([39, -98], 4, { animate: false });
    }
    first = false;
    apply.lastState = f.state;
    countEl.textContent = shown.length.toLocaleString("en-US") + " listings match (" + markers.length.toLocaleString("en-US") + " with a map location).";
    shown.sort(function (a, b) { return (b[8] - a[8]) || ((a[12] || "9999") < (b[12] || "9999") ? -1 : (a[12] || "9999") > (b[12] || "9999") ? 1 : 0) || (a[9] < b[9] ? -1 : 1); });
    results.textContent = "";
    var ul = el("ul", "cards");
    shown.slice(0, 60).forEach(function (r) {
      var li = el("li");
      var a = el("a", null, r[9]); a.href = base + "/land/" + r[0] + "/"; li.appendChild(a);
      var meta = [r[10] + ", " + r[3], STATUS[r[7]] || r[7]];
      if (r[4] != null) meta.push((KIND[r[5]] || "Price") + " " + money(r[4]));
      if (r[6]) meta.push(acres(r[6]));
      if (r[12]) meta.push("deadline " + r[12]);
      li.appendChild(el("span", "sub", meta.join(" · ")));
      ul.appendChild(li);
    });
    results.appendChild(ul);
    if (shown.length > 60) results.appendChild(el("p", "small", "Showing the first 60. Narrow the filters or zoom the map to see others."));
  }
  var h = hashState();
  if (scope && scope !== "all") form.state.value = scope;
  if (h.state) form.state.value = h.state;
  if (h.kind) form.kind.value = h.kind;
  if (h.max) form.max.value = h.max;
  if (h.acres) form.acres.value = h.acres;
  if (h.q) form.q.value = h.q;
  if (h.closed) form.closed.checked = true;
  form.addEventListener("input", function () { clearTimeout(apply.t); apply.t = setTimeout(apply, 200); });
  form.addEventListener("change", apply);
  countEl.textContent = "Loading listings…";
  fetch(base + "/data/map.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (d) {
    d.fields.forEach(function (f, i) { fields[f] = i; });
    rows = d.rows;
    apply();
  }).catch(function () { countEl.textContent = "The listings could not be loaded. Use the state pages below."; });
})();

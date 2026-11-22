/* Listing page: parcel map and the all-in cost worksheet. */
(function () {
  "use strict";
  function money(v) { return "$" + Math.round(v).toLocaleString("en-US"); }

  var data = document.getElementById("parcel");
  var box = document.getElementById("parcel-map");
  if (data && box && window.L) {
    var p = JSON.parse(data.textContent);
    var streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" });
    var aerial = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16, attribution: "USGS The National Map: imagery" });
    var map = L.map(box, { scrollWheelZoom: false, layers: [streets] }).setView([p.lat, p.lon], 16);
    L.control.layers({ "Streets": streets, "Aerial (USGS)": aerial }).addTo(map);
    if (p.geometry && p.geometry.length) {
      var shape = L.polygon(p.geometry.map(function (ring) { return ring.map(function (pt) { return [pt[1], pt[0]]; }); }),
        { color: "#236b43", weight: 3, fillColor: "#c5ed8b", fillOpacity: 0.35 }).addTo(map);
      map.fitBounds(shape.getBounds(), { padding: [30, 30], maxZoom: 18 });
    }
    L.circleMarker([p.lat, p.lon], { radius: 6, color: "#fff", weight: 2, fillColor: "#236b43", fillOpacity: 1 }).addTo(map);
  }

  var form = document.getElementById("worksheet");
  if (!form) return;
  var acres = parseFloat(form.getAttribute("data-acres"));
  var out = {};
  Array.prototype.forEach.call(document.querySelectorAll("#totals [data-t]"), function (d) { out[d.getAttribute("data-t")] = d; });
  function val(name) { var v = parseFloat(form.elements[name].value); return isNaN(v) || v < 0 ? 0 : v; }
  function update() {
    var price = val("price");
    var acq = price + price * val("fees") / 100 + val("closing") + val("title") + val("survey") + val("liens");
    var site = val("site") + val("utilities");
    var hold = (val("tax") + val("upkeep")) * val("years");
    var total = acq + site + hold;
    out.acq.textContent = money(acq);
    out.site.textContent = money(site);
    out.hold.textContent = money(hold);
    out.total.textContent = money(total);
    out.per.textContent = acres > 0 ? money(total / acres) + " per acre" : "acreage not published";
  }
  var saved = (location.hash.match(/w=([^&]+)/) || [])[1];
  if (saved) {
    decodeURIComponent(saved).split(",").forEach(function (kv) {
      var p = kv.split(":");
      if (form.elements[p[0]] && !isNaN(parseFloat(p[1]))) form.elements[p[0]].value = p[1];
    });
  }
  form.addEventListener("input", update);
  update();
  var copy = document.getElementById("copy-sheet");
  if (copy) copy.addEventListener("click", function () {
    var parts = [];
    Array.prototype.forEach.call(form.elements, function (e) { if (e.name && e.value !== "") parts.push(e.name + ":" + e.value); });
    var url = location.href.split("#")[0] + "#w=" + encodeURIComponent(parts.join(","));
    history.replaceState(null, "", url);
    if (navigator.clipboard) navigator.clipboard.writeText(url).then(function () { copy.textContent = "Link copied"; });
    else copy.textContent = "Link is in the address bar";
  });
})();

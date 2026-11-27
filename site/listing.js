/* Listing dossier: GIS parcel map (Aerial/Topo/Streets + FEMA overlay + distance measure),
   Live Federal Parcel X-Ray + Land Potential Screening, Print Field Packet, save/compare, and cost worksheet. */
(function () {
  "use strict";
  function money(v) { return "$" + Math.round(v).toLocaleString("en-US"); }

  // Print / Save Field Visit PDF
  var printBtn = document.getElementById("print-dossier");
  if (printBtn) {
    printBtn.addEventListener("click", function () { window.print(); });
  }

  // Local shortlist / compare sync
  function loadList(k) { try { return JSON.parse(localStorage.getItem(k) || "[]"); } catch (e) { return []; } }
  function saveList(k, a) { try { localStorage.setItem(k, JSON.stringify(a)); } catch (e) {} }
  var saveBtn = document.getElementById("save-parcel");
  var cmpBtn = document.getElementById("compare-parcel");
  if (saveBtn) {
    var pid = saveBtn.getAttribute("data-id");
    function syncSave() {
      var on = loadList("landosaur_saved").indexOf(pid) >= 0;
      saveBtn.textContent = on ? "Saved ★" : "Save ☆";
      saveBtn.classList.toggle("on", on);
    }
    saveBtn.addEventListener("click", function () {
      var arr = loadList("landosaur_saved"), i = arr.indexOf(pid);
      if (i >= 0) arr.splice(i, 1); else arr.push(pid);
      saveList("landosaur_saved", arr);
      syncSave();
    });
    syncSave();
  }
  if (cmpBtn) {
    var cid = cmpBtn.getAttribute("data-id");
    function syncCmp() {
      var arr = loadList("landosaur_compare"), on = arr.indexOf(cid) >= 0;
      cmpBtn.textContent = on ? "Comparing ✓" : "Compare";
      cmpBtn.classList.toggle("on", on);
    }
    cmpBtn.addEventListener("click", function () {
      var arr = loadList("landosaur_compare"), i = arr.indexOf(cid);
      if (i >= 0) arr.splice(i, 1); else if (arr.length < 4) arr.push(cid);
      saveList("landosaur_compare", arr);
      syncCmp();
    });
    syncCmp();
  }

  var data = document.getElementById("parcel");
  var box = document.getElementById("parcel-map");
  var parcelObj = data ? JSON.parse(data.textContent) : null;

  if (parcelObj && box && window.L) {
    var p = parcelObj;
    var streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxNativeZoom: 19, maxZoom: 20, attribution: "&copy; OpenStreetMap contributors" });
    var topo = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 20, attribution: "USGS The National Map" });
    var aerial = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 20, attribution: "USGS The National Map: imagery" });
    var fema = L.tileLayer.wms("https://hazards.fema.gov/arcgis/services/public/NFHL/MapServer/WMSServer", {
      layers: "28", format: "image/png", transparent: true, opacity: 0.48, maxZoom: 20, attribution: "FEMA NFHL Flood Zones"
    });
    var hasPoly = p.geometry && p.geometry.length;
    var map = L.map(box, { scrollWheelZoom: true, doubleClickZoom: true, touchZoom: true, maxZoom: 20, layers: [hasPoly ? aerial : streets] }).setView([p.lat, p.lon], 17);
    L.control.layers({ "USGS Aerial": aerial, "Streets": streets, "USGS Topo": topo }, { "FEMA Flood Zones": fema }).addTo(map);
    if (hasPoly) {
      var shape = L.polygon(p.geometry.map(function (ring) { return ring.map(function (pt) { return [pt[1], pt[0]]; }); }),
        { color: "#c8f189", weight: 3, fillColor: "#166534", fillOpacity: 0.25 }).addTo(map);
      map.fitBounds(shape.getBounds(), { padding: [30, 30], maxZoom: 18 });
    }
    L.circleMarker([p.lat, p.lon], { radius: 6, color: "#fff", weight: 2, fillColor: "#166534", fillOpacity: 1 }).addTo(map);

    // Interactive distance ruler (for measuring distance from road or power line)
    var measBtn = document.getElementById("measure-toggle");
    var measOut = document.getElementById("measure-out");
    if (measBtn && measOut) {
      var measuring = false, pts = [], line = null, dots = [];
      function clearMeasure() {
        pts = [];
        if (line) { map.removeLayer(line); line = null; }
        dots.forEach(function (d) { map.removeLayer(d); });
        dots = [];
        measOut.textContent = "";
      }
      measBtn.addEventListener("click", function () {
        measuring = !measuring;
        measBtn.textContent = measuring ? "Stop measuring (clear)" : "Measure distance on map";
        measBtn.classList.toggle("on", measuring);
        box.style.cursor = measuring ? "crosshair" : "";
        if (!measuring) clearMeasure();
        else measOut.textContent = "Click two or more points on the map to measure distance (feet / miles).";
      });
      map.on("click", function (ev) {
        if (!measuring) return;
        pts.push(ev.latlng);
        dots.push(L.circleMarker(ev.latlng, { radius: 4, color: "#102a1d", fillColor: "#c8f189", fillOpacity: 1, weight: 2 }).addTo(map));
        if (line) map.removeLayer(line);
        if (pts.length >= 2) {
          line = L.polyline(pts, { color: "#e59a6e", weight: 3, dashArray: "6 4" }).addTo(map);
          var meters = 0;
          for (var i = 1; i < pts.length; i++) meters += pts[i - 1].distanceTo(pts[i]);
          var feet = meters * 3.28084;
          var miles = feet / 5280;
          measOut.textContent = "Measured path: " + Math.round(feet).toLocaleString("en-US") + " ft (" + miles.toFixed(2) + " mi) — map estimate, not a survey.";
        }
      });
    }
  }

  // Trigger Live Federal Parcel X-Ray when coordinates exist + wire KML/GPX export & Analyzer handoff
  var xrayBox = document.getElementById("parcel-xray-body");
  var kmlBtn = document.getElementById("export-kml");
  var gpxBtn = document.getElementById("export-gpx");
  if (parcelObj && parcelObj.lat != null && parcelObj.lon != null && window.LandosaurXray) {
    if (kmlBtn) kmlBtn.addEventListener("click", function () { window.LandosaurXray.exportKml(parcelObj); });
    if (gpxBtn) gpxBtn.addEventListener("click", function () { window.LandosaurXray.exportGpx(parcelObj); });
    if (xrayBox) {
      window.LandosaurXray.loadXray(xrayBox, parcelObj.lat, parcelObj.lon, parcelObj, function (d) {
        var anaLink = document.getElementById("dossier-analyze-link");
        if (anaLink && d) {
          var u = new URL(anaLink.href, location.origin);
          if (d.roads && d.roads.nearest_road_ft != null) u.searchParams.set("roadFt", String(d.roads.nearest_road_ft));
          if (d.climate && d.climate.winter_min_sun_hours != null) u.searchParams.set("sun", String(d.climate.winter_min_sun_hours));
          window.LandosaurXray.powerContext(u.searchParams, d);
          anaLink.href = u.pathname + u.search;
        }
      });
    }
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
    if (navigator.clipboard) navigator.clipboard.writeText(url).then(function () { copy.textContent = "Link copied ✓"; });
    else copy.textContent = "Link is in the address bar";
  });
})();

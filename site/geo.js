/* Geometry and drawing shared by Parcel X-Ray and the inventory map. */
(function () {
  "use strict";
  const rad = Math.PI / 180;
  const radius = 6371007.1809;
  const limit = 40;

  function wrap(lon) {
    return ((lon + 540) % 360) - 180;
  }

  function normalize(points) {
    if (!Array.isArray(points) || points.length > limit) return [];
    return points.every((p) => Array.isArray(p) && p.length === 2 &&
        Number.isFinite(p[0]) && Number.isFinite(p[1]) && Math.abs(p[0]) <= 180 && Math.abs(p[1]) <= 85)
      ? points.map(([lon, lat]) => [Number(lon.toFixed(6)), Number(lat.toFixed(6))])
      : [];
  }

  function project(points) {
    const start = points[0]?.[0] || 0;
    return points.map(([lon, lat]) => [start + wrap(lon - start), lat]);
  }

  function measure(points) {
    const ring = project(points);
    if (ring.length < 3 || new Set(ring.map((p) => p.join(","))).size !== ring.length) return null;
    let area = 0, perimeter = 0, centroidX = 0, centroidY = 0, crossSum = 0;
    for (let index = 0; index < ring.length; index++) {
      const [lon, lat] = ring[index];
      const [otherLon, otherLat] = ring[(index + 1) % ring.length];
      const dl = (otherLon - lon) * rad;
      const da = (otherLat - lat) * rad;
      const cross = lon * otherLat - otherLon * lat;
      centroidX += (lon + otherLon) * cross;
      centroidY += (lat + otherLat) * cross;
      crossSum += cross;
      area += dl * (Math.sin(lat * rad) + Math.sin(otherLat * rad));
      const h = Math.sin(da / 2) ** 2 + Math.cos(lat * rad) * Math.cos(otherLat * rad) * Math.sin(dl / 2) ** 2;
      perimeter += radius * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
    }
    const squareMeters = Math.abs(area * radius * radius / 2);
    if (squareMeters < 1 || Math.abs(crossSum) < 1e-12) return null;
    for (let a = 0; a < ring.length; a++) {
      const p = ring[a], q = ring[(a + 1) % ring.length];
      for (let b = a + 2; b < ring.length; b++) {
        if (a === 0 && b === ring.length - 1) continue;
        const m = ring[b], n = ring[(b + 1) % ring.length];
        const side = (x, y, z) => (y[0] - x[0]) * (z[1] - x[1]) - (y[1] - x[1]) * (z[0] - x[0]);
        if (side(p, q, m) * side(p, q, n) < 0 && side(m, n, p) * side(m, n, q) < 0) return null;
      }
    }
    return {
      acres: squareMeters / 4046.8564224,
      squareFeet: squareMeters / 0.09290304,
      perimeterFeet: perimeter / 0.3048,
      center: [wrap(centroidX / (3 * crossSum)), centroidY / (3 * crossSum)],
      bounds: [wrap(Math.min(...ring.map((p) => p[0]))), Math.min(...ring.map((p) => p[1])),
        wrap(Math.max(...ring.map((p) => p[0]))), Math.max(...ring.map((p) => p[1]))],
    };
  }

  function contains(points, lon, lat) {
    if (points.length < 3 || !Number.isFinite(lon) || !Number.isFinite(lat)) return false;
    const ring = project(points);
    const x = points[0][0] + wrap(lon - points[0][0]);
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [ax, ay] = ring[i], [bx, by] = ring[j];
      if ((ay > lat) !== (by > lat) && x < (bx - ax) * (lat - ay) / (by - ay) + ax) inside = !inside;
    }
    return inside;
  }

  function encode(points) {
    return points.map((p) => p.join(",")).join(";");
  }

  function decode(value) {
    return typeof value === "string" && /^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?(?:;-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?){2,39}$/.test(value)
      ? normalize(value.split(";").map((p) => p.split(",").map(Number)))
      : [];
  }

  function drawer(map, toolbar, onFinish) {
    let active = false, points = [], layer;
    const toggle = toolbar.querySelector("[data-draw-start]");
    const finish = toolbar.querySelector("[data-draw-finish]");
    const undo = toolbar.querySelector("[data-draw-undo]");
    const clear = toolbar.querySelector("[data-draw-clear]");
    const status = toolbar.querySelector("[data-draw-status]");
    const idleLabel = toggle.textContent;
    function render(message) {
      if (layer) map.removeLayer(layer);
      if (points.length) {
        const vertices = project(points).map(([lon, lat]) => [lat, lon]);
        const styling = { color: "#257950", weight: 3, opacity: 1, fillOpacity: 0.22, interactive: false };
        layer = (vertices.length === 1 ? L.circleMarker(vertices[0], styling) :
          vertices.length === 2 ? L.polyline(vertices, styling) : L.polygon(vertices, styling)).addTo(map);
      }
      toggle.textContent = active ? "Cancel drawing" : idleLabel;
      toggle.setAttribute("aria-pressed", String(active));
      finish.hidden = !active;
      undo.hidden = !active;
      clear.hidden = !points.length || active;
      finish.disabled = points.length < 3;
      undo.disabled = !points.length;
      map.getContainer().classList.toggle("drawing-parcel", active);
      status.textContent = message || (active ? points.length + " vertices. Add points around the boundary, then finish." : "");
    }
    toggle.addEventListener("click", () => {
      active = !active;
      points = [];
      onFinish(null, []);
      render();
    });
    undo.addEventListener("click", () => { points.pop(); render(); });
    clear.addEventListener("click", () => { points = []; render(); onFinish(null, []); });
    finish.addEventListener("click", () => {
      const geometry = measure(points);
      if (!geometry) {
        render("Draw a simple boundary with at least three different vertices. Undo any crossing edges.");
        return;
      }
      active = false;
      render();
      onFinish(geometry, points.slice());
    });
    map.on("click", (event) => {
      if (!active || points.length >= limit) return;
      points = normalize(points.concat([[wrap(event.latlng.lng), event.latlng.lat]]));
      render(points.length === limit ? "Vertex limit reached. Finish the boundary or undo a point." : undefined);
    });
    render();
    return {
      isActive: () => active,
      set(value) {
        points = normalize(value);
        active = false;
        const geometry = measure(points);
        if (!geometry) points = [];
        render();
        return geometry;
      },
    };
  }

  window.LandosaurGeo = { contains, decode, drawer, encode, measure };
})();

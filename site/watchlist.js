/* Field exports use agency boundaries when published and map points when available. */
(function () {
  "use strict";
  const xml = (value) => String(value ?? "").replace(/[<>&"']/g, (ch) => ({
    "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;",
  })[ch]);
  const csv = (value) => {
    let text = String(value ?? "");
    if (typeof value === "string" && /^[\s]*[=+@-]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  };
  const formats = {
    csv: "text/csv;charset=utf-8",
    geojson: "application/geo+json",
    kml: "application/vnd.google-earth.kml+xml",
    gpx: "application/gpx+xml",
  };
  const validPoint = (p) => Array.isArray(p) && p.length === 2 &&
    p.every(Number.isFinite) && Math.abs(p[0]) <= 180 && Math.abs(p[1]) <= 90;
  const ringArea = (ring) => ring.slice(1).reduce((acc, [x, y], i) => acc + ring[i][0] * y - x * ring[i][1], 0);

  function shapes(raw) {
    const rings = (Array.isArray(raw) ? raw : []).filter((ring) => Array.isArray(ring) && ring.length >= 3 && ring.every(validPoint))
      .map((ring) => ring.at(-1).every((n, i) => n === ring[0][i]) ? ring : [...ring, ring[0]])
      .filter((ring) => Math.abs(ringArea(ring)) > 0)
      .sort((a, b) => Math.abs(ringArea(b)) - Math.abs(ringArea(a)));
    const tree = [], polygons = [];
    for (const ring of rings) {
      const point = ring[0];
      const parent = tree.findLast((node) => LandosaurGeo.matcher(node.ring)(point[0], point[1]));
      const hole = Boolean(parent && !parent.hole);
      let polygon = hole ? parent.polygon : [];
      polygon.push((ringArea(ring) > 0) === !hole ? ring : ring.slice().reverse());
      if (!hole) polygons.push(polygon);
      tree.push({ ring, hole, polygon });
    }
    return polygons;
  }

  function geoFeature(item) {
    const { lat, lon, rings, ...properties } = item;
    const polys = shapes(rings);
    const geometry = polys.length === 1 ? { type: "Polygon", coordinates: polys[0] } :
      polys.length > 1 ? { type: "MultiPolygon", coordinates: polys } :
      validPoint([lon, lat]) ? { type: "Point", coordinates: [lon, lat] } : null;
    return { type: "Feature", id: item.id, properties, geometry };
  }

  function serialize(items, format) {
    if (format === "csv") {
      const fields = ["id", "title", "county", "state", "status", "price_kind", "price", "acres", "usd_per_acre", "deadline", "lat", "lon", "url"];
      return [fields.join(","), ...items.map((item) => fields.map((key) => csv(item[key])).join(","))].join("\r\n") + "\r\n";
    }
    const features = items.map(geoFeature);
    if (format === "geojson") return JSON.stringify({ type: "FeatureCollection", features }, null, 2);
    if (format === "kml") {
      const loop = (ring, name) => "<" + name + "BoundaryIs><LinearRing><coordinates>" +
        ring.map(([x, y]) => x + "," + y + ",0").join(" ") + "</coordinates></LinearRing></" + name + "BoundaryIs>";
      const poly = (p) => "<Polygon>" + p.map((ring, i) => loop(ring, i ? "inner" : "outer")).join("") + "</Polygon>";
      const places = features.flatMap(({ properties: p, geometry: g }) => {
        if (!g) return [];
        const shape = g.type === "Point" ? "<Point><coordinates>" + g.coordinates.join(",") + ",0</coordinates></Point>" :
          g.type === "Polygon" ? poly(g.coordinates) : "<MultiGeometry>" + g.coordinates.map(poly).join("") + "</MultiGeometry>";
        return "<Placemark><name>" + xml(p.title) + "</name><description>" + xml(p.url) + "</description>" + shape + "</Placemark>";
      });
      return '<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Landosaur watchlist</name>' +
        places.join("") + "</Document></kml>";
    }
    if (format === "gpx") {
      const xy = ([x, y]) => ' lat="' + y + '" lon="' + x + '"';
      const waypoints = [], tracks = [];
      for (const { properties: p, geometry: g } of features) {
        if (!g) continue;
        const name = "<name>" + xml(p.title) + "</name>";
        if (g.type === "Point") waypoints.push("<wpt" + xy(g.coordinates) + ">" + name + "</wpt>");
        else {
          const polygons = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
          tracks.push("<trk>" + name + polygons.flatMap((p) => p.map((r) => "<trkseg>" +
            r.map((point) => "<trkpt" + xy(point) + "/>").join("") + "</trkseg>")).join("") + "</trk>");
        }
      }
      return '<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="Landosaur" xmlns="http://www.topografix.com/GPX/1/1">' +
        waypoints.join("") + tracks.join("") + "</gpx>";
    }
    throw new Error("Unknown watchlist format.");
  }

  function download(items, format) {
    const href = URL.createObjectURL(new Blob([serialize(items, format)], { type: formats[format] }));
    const link = document.createElement("a");
    link.href = href;
    link.download = "landosaur-watchlist." + format;
    link.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  }
  window.LandosaurWatchlist = { download };
})();

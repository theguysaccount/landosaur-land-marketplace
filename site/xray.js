/* Landosaur Live Federal Parcel X-Ray v2 — 9 live federal signals, SVG terrain cross-section profile,
   KML/GPX field GPS export, Land Potential Screening, and standalone /xray/ controller. */
(function () {
  "use strict";
  var base = document.body.getAttribute("data-base") || "";

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function escXml(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
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

  function hazardBadge(rating) {
    if (!rating || /No Rating|Not Applicable/i.test(rating)) return "off";
    if (/Very High|Relatively High/i.test(rating)) return "risk";
    if (/Moderate/i.test(rating)) return "warn";
    return "ok";
  }

  // Client-side KML & GPX generator (OnX Hunt, Gaia GPS, Google Earth)
  function downloadBlob(filename, mime, content) {
    var blob = new Blob([content], { type: mime });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 400);
  }

  function exportKml(opts) {
    var name = opts.title || ("Landosaur Pin " + opts.lat + ", " + opts.lon);
    var desc = opts.desc || ("Exported from Landosaur (" + opts.lat + ", " + opts.lon + "). Reference GIS data, not a legal survey.");
    var placemarks =
      '  <Placemark><name>' + escXml(name) + '</name><description>' + escXml(desc) + '</description>' +
      '<Point><coordinates>' + opts.lon + ',' + opts.lat + ',0</coordinates></Point></Placemark>\n';
    if (opts.geometry && opts.geometry.length) {
      opts.geometry.forEach(function (ring, idx) {
        var coords = ring.map(function (pt) { return pt[0] + "," + pt[1] + ",0"; }).join(" ");
        placemarks +=
          '  <Placemark><name>' + escXml(name + " (GIS Outline" + (idx ? " " + (idx + 1) : "") + ")") + '</name>' +
          '<Style><LineStyle><color>ff89f1c8</color><width>3</width></LineStyle><PolyStyle><color>40346516</color></PolyStyle></Style>' +
          '<Polygon><outerBoundaryIs><LinearRing><coordinates>' + coords + '</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>\n';
      });
    }
    var kml =
      '<?xml version="1.0" encoding="UTF-8"?>\n' +
      '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>' + escXml(name) + '</name>\n' +
      placemarks + '</Document></kml>\n';
    var slug = (opts.slug || ("landosaur-" + Number(opts.lat).toFixed(4) + "-" + Number(opts.lon).toFixed(4))).replace(/[^a-z0-9._-]+/gi, "-");
    downloadBlob(slug + ".kml", "application/vnd.google-earth.kml+xml", kml);
  }

  function exportGpx(opts) {
    var name = opts.title || ("Landosaur Pin " + opts.lat + ", " + opts.lon);
    var desc = opts.desc || ("Exported from Landosaur. GIS reference only, not a legal survey.");
    var tracks = "";
    if (opts.geometry && opts.geometry.length) {
      opts.geometry.forEach(function (ring, idx) {
        var pts = ring.map(function (pt) { return '      <trkpt lat="' + pt[1] + '" lon="' + pt[0] + '"></trkpt>'; }).join("\n");
        tracks += '  <trk><name>' + escXml(name + " Boundary" + (idx ? " " + (idx + 1) : "")) + '</name><trkseg>\n' + pts + '\n  </trkseg></trk>\n';
      });
    }
    var gpx =
      '<?xml version="1.0" encoding="UTF-8"?>\n' +
      '<gpx version="1.1" creator="Landosaur" xmlns="http://www.topografix.com/GPX/1/1">\n' +
      '  <wpt lat="' + opts.lat + '" lon="' + opts.lon + '"><name>' + escXml(name) + '</name><desc>' + escXml(desc) + '</desc></wpt>\n' +
      tracks + '</gpx>\n';
    var slug = (opts.slug || ("landosaur-" + Number(opts.lat).toFixed(4) + "-" + Number(opts.lon).toFixed(4))).replace(/[^a-z0-9._-]+/gi, "-");
    downloadBlob(slug + ".gpx", "application/gpx+xml", gpx);
  }

  function skeletonHtml() {
    var cards = "";
    for (var i = 0; i < 10; i++) {
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

  function renderTerrainProfileSvg(u) {
    var we = u && u.profile_we;
    var sn = u && u.profile_sn;
    if (!we || we.length < 3) return null;
    var allFt = we.map(function (p) { return p.ft; }).concat((sn || []).map(function (p) { return p.ft; }));
    var minV = Math.min.apply(null, allFt);
    var maxV = Math.max.apply(null, allFt);
    var pad = Math.max(4, (maxV - minV) * 0.22);
    var lo = minV - pad;
    var hi = maxV + pad;
    var span = Math.max(1, hi - lo);
    var W = 640, H = 148, PL = 58, PR = 20, PT = 16, PB = 28;
    var innerW = W - PL - PR, innerH = H - PT - PB;

    function mapX(off) { return PL + ((off + 328) / 656) * innerW; }
    function mapY(ft) { return PT + (1 - (ft - lo) / span) * innerH; }

    var wePts = we.map(function (p) { return mapX(p.offset_ft).toFixed(1) + "," + mapY(p.ft).toFixed(1); });
    var wePath = "M" + wePts.join(" L");
    var weArea = wePath + " L" + mapX(we[we.length - 1].offset_ft).toFixed(1) + "," + (PT + innerH) +
      " L" + mapX(we[0].offset_ft).toFixed(1) + "," + (PT + innerH) + " Z";
    var snPath = "";
    if (sn && sn.length >= 3) {
      snPath = '<path d="M' + sn.map(function (p) { return mapX(p.offset_ft).toFixed(1) + "," + mapY(p.ft).toFixed(1); }).join(" L") +
        '" fill="none" stroke="var(--orange)" stroke-width="2" stroke-dasharray="5 4" opacity="0.9"/>';
    }
    var cx = mapX(0).toFixed(1);
    var cy = mapY(u.elevation_ft).toFixed(1);

    var wrap = el("div", "terrain-profile-card");
    wrap.innerHTML =
      '<div class="terrain-profile-head"><strong>656-ft LiDAR Terrain Cross-Section (USGS 3DEP)</strong>' +
      '<div class="chart-legend" style="margin:0">' +
      '<span class="legend-item"><i style="background:var(--forest)"></i>West → East</span>' +
      '<span class="legend-item"><i style="background:var(--orange)"></i>South → North</span>' +
      '</div></div>' +
      '<svg class="trend-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Terrain elevation cross-section centered on parcel pin">' +
      '<line x1="' + PL + '" y1="' + PT + '" x2="' + (W - PR) + '" y2="' + PT + '" stroke="var(--line)" stroke-dasharray="3 3"/>' +
      '<line x1="' + PL + '" y1="' + (PT + innerH / 2).toFixed(1) + '" x2="' + (W - PR) + '" y2="' + (PT + innerH / 2).toFixed(1) + '" stroke="var(--line)" stroke-dasharray="3 3"/>' +
      '<line x1="' + PL + '" y1="' + (PT + innerH) + '" x2="' + (W - PR) + '" y2="' + (PT + innerH) + '" stroke="var(--line-strong)"/>' +
      '<line x1="' + cx + '" y1="' + PT + '" x2="' + cx + '" y2="' + (PT + innerH) + '" stroke="var(--forest)" stroke-dasharray="2 3" opacity="0.5"/>' +
      '<path d="' + weArea + '" fill="var(--forest)" opacity="0.14"/>' +
      '<path d="' + wePath + '" fill="none" stroke="var(--forest)" stroke-width="2.6" stroke-linejoin="round"/>' +
      snPath +
      '<circle cx="' + cx + '" cy="' + cy + '" r="4.5" fill="var(--forest)" stroke="var(--surface)" stroke-width="2"/>' +
      '<text x="' + (PL - 8) + '" y="' + (PT + 4) + '" text-anchor="end" font-size="11" fill="var(--muted)">' + Math.round(maxV).toLocaleString("en-US") + ' ft</text>' +
      '<text x="' + (PL - 8) + '" y="' + (PT + innerH) + '" text-anchor="end" font-size="11" fill="var(--muted)">' + Math.round(minV).toLocaleString("en-US") + ' ft</text>' +
      '<text x="' + PL + '" y="' + (H - 7) + '" font-size="11" fill="var(--muted)">-328 ft (W/S)</text>' +
      '<text x="' + cx + '" y="' + (H - 7) + '" text-anchor="middle" font-size="11" font-weight="700" fill="var(--ink)">Pin (' + Math.round(u.elevation_ft).toLocaleString("en-US") + ' ft)</text>' +
      '<text x="' + (W - PR) + '" y="' + (H - 7) + '" text-anchor="end" font-size="11" fill="var(--muted)">+328 ft (E/N)</text>' +
      '</svg>';
    return wrap;
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
      var aNotes = ["Tax-sale / auction offering — confirm final auction terms & opening bid"];
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

    // 5. U.S. Census TIGERweb Road & Highway Access
    var rd = d.roads || {};
    if (rd.status === "ok") {
      var rMeta = tierMeta(rd.access_tier);
      var rHead = rd.nearest_road_ft != null ? ("~" + rd.nearest_road_ft.toLocaleString("en-US") + " ft to road") : "None within 0.5 mi";
      var rBits = [];
      if (rd.nearest_road_name) rBits.push(rd.nearest_road_name + (rd.nearest_road_type ? " (" + rd.nearest_road_type + ")" : ""));
      if (rd.nearest_highway_name && rd.nearest_highway_mi != null) rBits.push("Nearest hwy: " + rd.nearest_highway_name + " (" + rd.nearest_highway_mi + " mi)");
      rBits.push(rd.access_signal);
      grid.appendChild(tileNode("Road Proximity", rHead, rBits.join(" · "), rMeta.cls, rd.nearest_road_ft != null && rd.nearest_road_ft <= 150 ? "Near road" : (rd.nearest_road_ft != null ? "Verify easement" : "Check access"), rd.source_url, rd.source));
    } else {
      grid.appendChild(tileNode("Road Proximity", "Unavailable", "Census TIGERweb road lookup unavailable right now.", "off", "Check satellite", "https://www.google.com/maps/@" + d.lat + "," + d.lon + ",16z", "Census TIGERweb"));
    }

    // 6. USGS PAD-US Public Lands Adjacency
    var pl = d.public_land || {};
    if (pl.status === "ok") {
      if (pl.within_1km && pl.units && pl.units.length) {
        var topU = pl.units[0];
        var pBits = pl.units.slice(0, 2).map(function (x) {
          return x.name + (x.agency ? " (" + x.agency + ")" : "") + (x.acres ? " · " + x.acres.toLocaleString("en-US") + " ac" : "");
        });
        grid.appendChild(tileNode("Nearby Public Land (1km)", topU.name, pBits.join("; "), "ok", topU.access || (pl.count + " nearby"), pl.source_url, pl.source));
      } else {
        grid.appendChild(tileNode("Nearby Public Land (1km)", "Private surroundings", "No federal/state protected public land unit mapped within 1 km.", "off", "Private area", pl.source_url, pl.source));
      }
    } else {
      grid.appendChild(tileNode("Nearby Public Land", "Unavailable", "USGS PAD-US lookup unavailable right now.", "off", "Check map", "https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-overview", "USGS PAD-US"));
    }

    // 7. FEMA National Risk Index Hazards
    var hz = d.hazards || {};
    if (hz.status === "ok") {
      var hBits = [];
      if (hz.wildfire && !/No Rating/i.test(hz.wildfire)) hBits.push("Wildfire: " + hz.wildfire);
      if (hz.tornado && !/No Rating/i.test(hz.tornado)) hBits.push("Tornado: " + hz.tornado);
      if (hz.hurricane && !/No Rating/i.test(hz.hurricane)) hBits.push("Hurricane: " + hz.hurricane);
      if (hz.earthquake && !/No Rating/i.test(hz.earthquake)) hBits.push("Earthquake: " + hz.earthquake);
      if (hz.drought && !/No Rating/i.test(hz.drought)) hBits.push("Drought: " + hz.drought);
      var wfHigh = hz.wildfire && /High/i.test(hz.wildfire);
      var badgeH = wfHigh ? "risk" : hazardBadge(hz.overall);
      grid.appendChild(tileNode("Natural Hazard Risk", hz.overall || "County rated", hBits.join(" · "), badgeH, wfHigh ? "Wildfire " + hz.wildfire : (hz.overall || "FEMA NRI"), hz.source_url, hz.source));
    } else {
      grid.appendChild(tileNode("Natural Hazard Risk", "Unavailable", "FEMA National Risk Index county lookup unavailable.", "off", "FEMA NRI", "https://hazards.fema.gov/nri/map", "FEMA NRI"));
    }

    // 8. NASA Solar, Climate & USDA Growing Zone
    var cl = d.climate || {};
    if (cl.status === "ok") {
      var cHead = cl.annual_sun_hours != null ? (cl.annual_sun_hours + " sun hrs/day") : "Climate mapped";
      var cBits = [];
      if (cl.winter_min_sun_hours != null) cBits.push("Winter min " + cl.winter_min_sun_hours + " hrs/day");
      if (cl.annual_precip_in != null) cBits.push("~" + cl.annual_precip_in + " in/yr rain");
      if (cl.winter_low_f != null && cl.summer_high_f != null) cBits.push("Normal " + cl.winter_low_f + "°F–" + cl.summer_high_f + "°F");
      if (cl.hardiness_zone) cBits.push("USDA Zone " + cl.hardiness_zone);
      var cBadge = cl.annual_sun_hours >= 4.5 ? "ok" : (cl.annual_sun_hours >= 3.5 ? "warn" : "off");
      grid.appendChild(tileNode("Solar, Climate & Zone", cHead, cBits.join(" · "), cBadge, cl.hardiness_zone ? ("Zone " + cl.hardiness_zone) : (cl.annual_precip_in + " in/yr"), cl.source_url, cl.source));
    } else {
      grid.appendChild(tileNode("Solar & Climate", "Unavailable", "NASA POWER climatology did not respond.", "off", "Retry", "https://power.larc.nasa.gov/", "NASA POWER"));
    }

    // 9. County Land Benchmark
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

    var utility = d.utility || {};
    var providers = utility.providers || [];
    var utilities = tileNode("Electric utilities", providers.length ? providers.length + " county provider" +
      (providers.length === 1 ? "" : "s") : "No matching report", utility.note || "Confirm service with the local utility.",
      providers.length ? "ok" : "off", utility.year ? "EIA-861 · " + utility.year : "", utility.source, "EIA utility data");
    utilities.setAttribute("data-utility-card", "");
    if (providers.length) {
      var list = el("ul", "utility-list");
      providers.forEach(function (provider) {
        var detail = provider.name + (provider.ownership ? " · " + provider.ownership : "");
        if (provider.residential_usd_per_kwh != null) detail += " · " + (provider.residential_usd_per_kwh * 100).toFixed(2) + "¢/kWh";
        list.appendChild(el("li", null, detail));
      });
      utilities.appendChild(list);
    }
    if (utility.state_commission_url) {
      var stateDirectory = el("a", "xray-src", "Find your state utility commission ↗");
      stateDirectory.href = utility.state_commission_url;
      stateDirectory.rel = "noopener noreferrer";
      stateDirectory.target = "_blank";
      utilities.appendChild(stateDirectory);
    }
    grid.appendChild(utilities);
    container.appendChild(grid);

    // SVG Terrain Cross-Section Profile
    var profileCard = renderTerrainProfileSvg(u);
    if (profileCard) container.appendChild(profileCard);

    // Land Potential Screening Matrix
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

    var foot = el("p", "small xray-disc",
      (d.disclaimer || "Automated federal GIS screening only.") +
      " Coordinates: " + d.lat + ", " + d.lon + " · Sources include bundled EIA data and federal GIS lookups.");
    container.appendChild(foot);
  }

  function powerContext(params, data) {
    var utility = data?.utility || {};
    if (utility.state_average_usd_per_kwh > 0) {
      params.set("kwhRate", String(utility.state_average_usd_per_kwh));
      params.set("eiaYear", String(utility.year));
      if (data.county?.state_code) params.set("eiaState", data.county.state_code);
    }
    return params;
  }

  function loadXray(container, lat, lon, parcelCtx, onDone, current) {
    if (!container) return;
    container.innerHTML = skeletonHtml();
    var url = base + "/api/xray/?lat=" + encodeURIComponent(lat) + "&lon=" + encodeURIComponent(lon);
    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        if (current && !current()) return;
        if (d.error) throw new Error(d.error);
        renderXrayInto(container, d, parcelCtx);
        if (onDone) onDone(d);
      })
      .catch(function () {
        if (current && !current()) return;
        container.textContent = "";
        var box = el("div", "callout");
        box.innerHTML =
          "<strong>Live Federal Parcel X-Ray unavailable from this host right now.</strong> " +
          "When deployed on <code>landosaur.com</code>, this panel queries USGS 3DEP LiDAR, FEMA NFHL, FEMA National Risk Index, USFWS Wetlands, USDA SSURGO Soil, Census TIGER Roads, USGS PAD-US Public Lands, and NASA Solar live. " +
          "Use the direct FEMA, USDA Web Soil Survey, and USFWS links above in the meantime.";
        container.appendChild(box);
      });
  }

  window.LandosaurXray = {
    loadXray: loadXray,
    powerContext: powerContext,
    renderXrayInto: renderXrayInto,
    skeletonHtml: skeletonHtml,
    exportKml: exportKml,
    exportGpx: exportGpx,
  };

  // Standalone /xray/ interactive page controller
  var pageRoot = document.getElementById("xray-app");
  if (!pageRoot || !window.L) return;

  var mapEl = document.getElementById("xray-map");
  var outEl = document.getElementById("xray-results");
  var statusEl = document.getElementById("xray-status");
  var form = document.getElementById("xray-search-form");
  var input = document.getElementById("xray-q");
  var actionBar = document.getElementById("xray-actions");

  var aerial = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 20, attribution: "USGS Imagery" });
  var streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxNativeZoom: 19, maxZoom: 20, attribution: "&copy; OpenStreetMap" });
  var topo = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 20, attribution: "USGS Topo" });
  var fema = L.tileLayer.wms("https://hazards.fema.gov/arcgis/services/public/NFHL/MapServer/WMSServer", {
    layers: "28", format: "image/png", transparent: true, opacity: 0.48, maxZoom: 20, attribution: "FEMA NFHL"
  });
  var map = L.map(mapEl, { scrollWheelZoom: true, doubleClickZoom: true, touchZoom: true, maxZoom: 20, layers: [aerial] }).setView([38.5, -96.0], 4);
  L.control.layers({ "USGS Satellite": aerial, "Streets": streets, "USGS Topo": topo }, { "FEMA Flood Zones": fema }).addTo(map);

  var pin = null, requestId = 0, drawn = null, latest = null;
  var measurements = document.getElementById("xray-measurements");
  var geo = window.LandosaurGeo;
  var draw = geo.drawer(map, document.getElementById("xray-draw"), function (shape, points) {
    drawn = shape ? { shape: shape, points: points } : null;
    if (drawn) runAt(shape.center[1], shape.center[0], "Drawn parcel", map.getZoom());
    else if (latest) {
      writeShare(latest.lat, latest.lon);
      updateActions(latest.lat, latest.lon, latest.label, latest.data);
    } else if (measurements) measurements.hidden = true;
  });

  function writeShare(lat, lon) {
    var fields = new URLSearchParams({ lat: lat.toFixed(5), lon: lon.toFixed(5) });
    if (drawn) fields.set("poly", geo.encode(drawn.points));
    history.replaceState(null, "", location.pathname + location.search + "#" + fields);
    return location.href;
  }

  function showMeasurements(d) {
    measurements.hidden = !drawn;
    measurements.replaceChildren();
    if (!drawn) return;
    var shape = drawn.shape;
    measurements.appendChild(el("h2", null, "Drawn parcel measurements"));
    measurements.appendChild(el("p", null, fmtNum(Number(shape.acres.toFixed(3)), " acres") + " · " +
      fmtNum(Math.round(shape.squareFeet), " sq ft") + " · " + fmtNum(Math.round(shape.perimeterFeet), " ft perimeter")));
    measurements.appendChild(el("p", "small", "Bounds W/S/E/N: " +
      shape.bounds.map(function (v) { return v.toFixed(5); }).join(", ") + ". Map measurements are approximate."));
    var benchmark = d?.county?.benchmark_usd_per_acre;
    if (benchmark > 0) {
      measurements.appendChild(el("p", null, "County benchmark × drawn area: $" +
        fmtNum(Math.round(shape.acres * benchmark)) + ". Benchmark context, not an appraisal."));
    }
  }

  function updateActions(lat, lon, label, d) {
    actionBar.hidden = false;
    var title = label || ("Pin " + lat.toFixed(4) + ", " + lon.toFixed(4));
    var anaParams = powerContext(new URLSearchParams({ title: title }), d);
    if (d?.roads?.nearest_road_ft != null) anaParams.set("roadFt", d.roads.nearest_road_ft);
    if (d?.climate?.winter_min_sun_hours != null) anaParams.set("sun", d.climate.winter_min_sun_hours);
    if (drawn) anaParams.set("acres", drawn.shape.acres.toFixed(4));
    var ana = el("a", "button", "Open Deal & Power Analyzer →");
    ana.href = base + "/analyze/?" + anaParams;
    actionBar.replaceChildren(ana);

    var fields = new URLSearchParams({ service: "unlisted_outreach", lat: lat.toFixed(6), lon: lon.toFixed(6) });
    if (d?.county?.county_name) fields.set("county", d.county.county_name);
    if (d?.county?.state_code) fields.set("state", d.county.state_code);
    if (drawn) {
      fields.set("acres", drawn.shape.acres.toFixed(4));
      fields.set("boundary", geo.encode(drawn.points));
    }
    var acquire = el("a", "button ghost", "Hire Land Agent for this tract · $20 →");
    acquire.href = base + "/services/?" + fields;
    actionBar.appendChild(acquire);

    var boundary = drawn ? [drawn.points.concat([drawn.points[0]])] : null;
    var file = { lat: lat, lon: lon, title: title, geometry: boundary };
    [
      ["xray-kml-btn", "Download KML", function () { exportKml(file); }],
      ["xray-gpx-btn", "Download GPX", function () { exportGpx(file); }],
      ["xray-print-btn", "Print / Save Field PDF", function () { window.print(); }],
      ["xray-copy-btn", "Copy share link", function (button) {
        var link = writeShare(lat, lon);
        if (navigator.clipboard) navigator.clipboard.writeText(link).then(function () {
          button.textContent = "Link copied";
        }, function () { window.prompt("Copy share link", link); });
        else window.prompt("Copy share link", link);
      }]
    ].forEach(function (action) {
      var button = el("button", "button ghost", action[1]);
      button.id = action[0];
      button.type = "button";
      button.addEventListener("click", function () { action[2](button); });
      actionBar.appendChild(button);
    });
    showMeasurements(d);
  }

  function placePin(lat, lon, zoom) {
    if (pin) map.removeLayer(pin);
    pin = L.circleMarker([lat, lon], { radius: 8, color: "#fff", weight: 2.5, fillColor: "#c8f189", fillOpacity: 1 }).addTo(map);
    if (!drawn) map.setView([lat, lon], zoom || Math.max(map.getZoom(), 14));
    writeShare(lat, lon);
  }

  function runAt(lat, lon, label, zoom) {
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    var job = ++requestId;
    placePin(lat, lon, zoom);
    latest = { lat: lat, lon: lon, label: label, data: null };
    updateActions(lat, lon, label, null);
    statusEl.textContent = "Running Parcel X-Ray for " + (label || (lat.toFixed(5) + ", " + lon.toFixed(5))) + "…";
    loadXray(outEl, lat, lon, null, function (d) {
      var place = label || (d.county?.county_name ? (d.county.county_name + ", " + d.county.state_code) :
        (lat.toFixed(5) + ", " + lon.toFixed(5)));
      statusEl.textContent = "Parcel X-Ray complete for " + place + ".";
      latest = { lat: lat, lon: lon, label: place, data: d };
      updateActions(lat, lon, place, d);
    }, function () { return job === requestId; });
  }

  function runQuery(q) {
    q = (q || "").trim();
    if (!q) return;
    var job = ++requestId;
    drawn = null;
    draw.set([]);
    showMeasurements(null);
    actionBar.hidden = true;
    statusEl.textContent = "Looking up " + q + "…";
    outEl.innerHTML = skeletonHtml();
    fetch(base + "/api/xray/?q=" + encodeURIComponent(q))
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (job !== requestId) return;
        if (!res.ok || res.d.error) {
          outEl.textContent = "";
          statusEl.textContent = res.d.error || "Location not found in the United States.";
          return;
        }
        var d = res.d;
        var label = d.geocode?.label || q;
        placePin(d.lat, d.lon, 14);
        statusEl.textContent = "Parcel X-Ray complete for " + label + ".";
        renderXrayInto(outEl, d, null);
        latest = { lat: d.lat, lon: d.lon, label: label, data: d };
        updateActions(d.lat, d.lon, label, d);
      })
      .catch(function () {
        if (job !== requestId) return;
        outEl.textContent = "";
        statusEl.textContent = "The Parcel X-Ray service could not be reached.";
      });
  }

  map.on("click", function (ev) {
    if (draw.isActive()) return;
    if (drawn) {
      drawn = null;
      draw.set([]);
    }
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
      drawn = null;
      draw.set([]);
      runAt(parseFloat(coords[0]), parseFloat(coords[1]), lbl, 14);
    });
  });

  var q = new URLSearchParams(location.hash.slice(1) || location.search.slice(1));
  var points = geo.decode(q.get("poly"));
  var shape = draw.set(points);
  if (shape) {
    drawn = { shape: shape, points: points };
    map.fitBounds(points.map(function (p) { return [p[1], p[0]]; }), { maxZoom: 18, padding: [25, 25] });
    runAt(shape.center[1], shape.center[0], "Drawn parcel", map.getZoom());
  } else if (q.has("lat") && q.has("lon")) {
    runAt(parseFloat(q.get("lat")), parseFloat(q.get("lon")), null, 14);
  } else if (q.get("q")) {
    if (input) input.value = q.get("q");
    runQuery(q.get("q"));
  }
})();

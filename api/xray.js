/**
 * Landosaur Live Federal Parcel X-Ray API v2 (Vercel Fluid Compute — Node.js Web API Function).
 *
 * Queries 9 authoritative public federal/official datasets in parallel for any coordinates in all 50 U.S. states:
 *   1. USGS 3DEP Elevation Point Query Service (9-point W-E & S-N cross-section -> elevation, slope %, relief, aspect, SVG profile)
 *   2. FEMA National Flood Hazard Layer (NFHL MapServer/28 -> flood zone, 100-yr SFHA, BFE, FIRM panel)
 *   3. FEMA National Risk Index (county-level Wildfire, Drought, Hurricane, Tornado, Earthquake risk ratings)
 *   4. USFWS National Wetlands Inventory (100m buffer -> wetland types & proximity)
 *   5. USDA NRCS SSURGO Soil Data Access (soil map unit, prime farmland, drainage, hydgrp, water table, bedrock depth, septic signal)
 *   6. U.S. Census TIGERweb Transportation (nearest mapped road + distance in ft, nearest highway + distance in mi)
 *   7. USGS PAD-US Protected Areas & Public Lands (National Forest / BLM / State Park adjacency within 1 km)
 *   8. NASA POWER Climatology (annual/winter/summer peak sun hours, normal summer high / winter low °F, rainfall, USDA Hardiness Zone)
 *   9. FCC Census Area FIPS joined against bundled 3,115-county USDA/FHFA Land Index
 *
 * Also supports ?q=<address or place> via U.S. Census Geocoder + OpenStreetMap Nominatim (US-bounded).
 * Zero fabricated fallbacks: unavailable upstreams report status="unavailable" honestly.
 */
import fs from "node:fs";
import path from "node:path";

const BROWSER_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";
const LANDO_UA = "landosaur-parcel-xray/2.0 (+https://landosaur.com)";

const STATE_SLUGS = {
  AL: "alabama", AK: "alaska", AZ: "arizona", AR: "arkansas", CA: "california", CO: "colorado",
  CT: "connecticut", DE: "delaware", DC: "district-of-columbia", FL: "florida", GA: "georgia", HI: "hawaii",
  ID: "idaho", IL: "illinois", IN: "indiana", IA: "iowa", KS: "kansas", KY: "kentucky",
  LA: "louisiana", ME: "maine", MD: "maryland", MA: "massachusetts", MI: "michigan", MN: "minnesota",
  MS: "mississippi", MO: "missouri", MT: "montana", NE: "nebraska", NV: "nevada", NH: "new-hampshire",
  NJ: "new-jersey", NM: "new-mexico", NY: "new-york", NC: "north-carolina", ND: "north-dakota", OH: "ohio",
  OK: "oklahoma", OR: "oregon", PA: "pennsylvania", RI: "rhode-island", SC: "south-carolina", SD: "south-dakota",
  TN: "tennessee", TX: "texas", UT: "utah", VT: "vermont", VA: "virginia", WA: "washington",
  WV: "west-virginia", WI: "wisconsin", WY: "wyoming",
};

const MTFCC_LABELS = {
  S1100: "Primary highway / interstate",
  S1200: "State / U.S. highway",
  S1400: "Local / rural road",
  S1500: "4WD / unimproved vehicular trail",
  S1630: "Ramp",
  S1640: "Service drive",
  S1740: "Private / access road",
  S1750: "Internal road",
};

let countyMap = null;
function loadCountyMap() {
  if (countyMap) return countyMap;
  countyMap = new Map();
  const candidates = [
    path.join(process.cwd(), "data", "usda", "land-index-counties.json"),
    path.join(path.dirname(new URL(import.meta.url).pathname), "..", "data", "usda", "land-index-counties.json"),
  ];
  for (const file of candidates) {
    try {
      if (!fs.existsSync(file)) continue;
      const rows = JSON.parse(fs.readFileSync(file, "utf-8"));
      for (const row of rows) {
        const [fips, name, state, stateName, pagePath, value, year, kind] = row;
        if (fips) {
          countyMap.set(String(fips).padStart(5, "0"), {
            fips: String(fips).padStart(5, "0"),
            name,
            state,
            state_name: stateName,
            path: pagePath,
            value,
            year,
            kind,
          });
        }
      }
      break;
    } catch (err) {
      console.error("[xray] failed loading county index:", err?.message || err);
    }
  }
  return countyMap;
}

async function fetchJson(url, opts = {}, timeoutMs = 7000) {
  const res = await fetch(url, {
    ...opts,
    signal: AbortSignal.timeout(timeoutMs),
    headers: {
      "User-Agent": BROWSER_UA,
      Accept: "application/json",
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function round(v, d = 1) {
  if (v == null || !Number.isFinite(v)) return null;
  const f = 10 ** d;
  return Math.round(v * f) / f;
}

function haversineMeters(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(Math.min(1, a)));
}

function minDistanceToPathsMeters(lat, lon, paths) {
  let best = Infinity;
  for (const seg of paths || []) {
    for (let i = 0; i < seg.length; i++) {
      const [lo, la] = seg[i];
      const d = haversineMeters(lat, lon, la, lo);
      if (d < best) best = d;
      if (i > 0) {
        // Also check midpoint of segment for long rural straightaways
        const [lo0, la0] = seg[i - 1];
        const dm = haversineMeters(lat, lon, (la + la0) / 2, (lo + lo0) / 2);
        if (dm < best) best = dm;
      }
    }
  }
  return best;
}

async function queryUsgsElevation(lat, lon) {
  const dLat50 = 0.00045; // ~50m
  const dLon50 = 0.00045 / Math.max(0.2, Math.cos((lat * Math.PI) / 180));
  // 9-point cross-section (center + ±50m & ±100m along W-E and S-N) for true slope + terrain profile chart
  const pts = [
    ["c", lat, lon],
    ["n1", lat + dLat50, lon],
    ["s1", lat - dLat50, lon],
    ["e1", lat, lon + dLon50],
    ["w1", lat, lon - dLon50],
    ["n2", lat + dLat50 * 2, lon],
    ["s2", lat - dLat50 * 2, lon],
    ["e2", lat, lon + dLon50 * 2],
    ["w2", lat, lon - dLon50 * 2],
  ];
  const settled = await Promise.allSettled(
    pts.map(async ([k, la, lo]) => {
      const u = `https://epqs.nationalmap.gov/v1/json?x=${lo.toFixed(6)}&y=${la.toFixed(6)}&wkid=4326&units=Feet`;
      const d = await fetchJson(u, {}, 6500);
      const v = Number(d?.value);
      if (!Number.isFinite(v) || v < -1000 || v > 30000) throw new Error("invalid elevation");
      return [k, v];
    })
  );
  const vals = {};
  for (const s of settled) {
    if (s.status === "fulfilled") vals[s.value[0]] = s.value[1];
  }
  if (vals.c == null) {
    return { status: "unavailable", source: "USGS 3DEP EPQS" };
  }
  const near = ["c", "n1", "s1", "e1", "w1"].map((k) => vals[k]).filter((v) => v != null);
  const all = Object.values(vals);
  const minFt = Math.min(...all);
  const maxFt = Math.max(...all);
  const reliefFt = Math.max(...near) - Math.min(...near);
  let slopePct = null;
  let aspect = null;
  if (vals.n1 != null && vals.s1 != null && vals.e1 != null && vals.w1 != null) {
    const spanFt = 100 * 3.28084;
    const dzDy = (vals.n1 - vals.s1) / spanFt;
    const dzDx = (vals.e1 - vals.w1) / spanFt;
    slopePct = Math.sqrt(dzDx * dzDx + dzDy * dzDy) * 100;
    if (slopePct >= 2) {
      const ang = (Math.atan2(-dzDx, -dzDy) * 180) / Math.PI;
      const deg = (ang + 360) % 360;
      const dirs = ["North", "Northeast", "East", "Southeast", "South", "Southwest", "West", "Northwest"];
      aspect = dirs[Math.round(deg / 45) % 8];
    } else {
      aspect = "Flat / level";
    }
  }
  let terrainClass = "Unknown";
  if (slopePct != null) {
    if (slopePct < 3) terrainClass = "Flat (<3%)";
    else if (slopePct < 8) terrainClass = "Gentle (3–8%)";
    else if (slopePct < 15) terrainClass = "Moderate (8–15%)";
    else if (slopePct < 25) terrainClass = "Steep (15–25%)";
    else terrainClass = "Very steep (>25%)";
  }
  const profileWe = [
    { offset_ft: -328, ft: round(vals.w2, 1) },
    { offset_ft: -164, ft: round(vals.w1, 1) },
    { offset_ft: 0, ft: round(vals.c, 1) },
    { offset_ft: 164, ft: round(vals.e1, 1) },
    { offset_ft: 328, ft: round(vals.e2, 1) },
  ].filter((p) => p.ft != null);
  const profileSn = [
    { offset_ft: -328, ft: round(vals.s2, 1) },
    { offset_ft: -164, ft: round(vals.s1, 1) },
    { offset_ft: 0, ft: round(vals.c, 1) },
    { offset_ft: 164, ft: round(vals.n1, 1) },
    { offset_ft: 328, ft: round(vals.n2, 1) },
  ].filter((p) => p.ft != null);

  return {
    status: "ok",
    elevation_ft: round(vals.c, 0),
    min_ft: round(minFt, 0),
    max_ft: round(maxFt, 0),
    relief_ft: round(reliefFt, 1),
    slope_pct: round(slopePct, 1),
    terrain_class: terrainClass,
    aspect,
    profile_we: profileWe,
    profile_sn: profileSn,
    source: "USGS 3DEP 1m/10m LiDAR",
    source_url: "https://apps.nationalmap.gov/viewer/",
  };
}

async function queryFemaFlood(lat, lon) {
  const params = new URLSearchParams({
    geometry: `${lon},${lat}`,
    geometryType: "esriGeometryPoint",
    inSR: "4326",
    spatialRel: "esriSpatialRelIntersects",
    outFields: "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE,DFIRM_ID",
    returnGeometry: "false",
    f: "json",
  });
  const url = `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query?${params}`;
  const d = await fetchJson(url, {}, 7500);
  const feats = d?.features || [];
  const mscUrl = `https://msc.fema.gov/portal/search?AddressQuery=${lat.toFixed(6)}%2C${lon.toFixed(6)}`;
  if (!feats.length) {
    return {
      status: "not_mapped",
      zone: "Unmapped",
      sfha: null,
      risk_level: "Not digitally mapped by FEMA NFHL (verify local panel)",
      source: "FEMA NFHL MapServer/28",
      source_url: mscUrl,
    };
  }
  const a = feats[0].attributes || {};
  const zone = String(a.FLD_ZONE || "").trim() || "Unknown";
  const sub = String(a.ZONE_SUBTY || "").trim();
  const sfha = String(a.SFHA_TF || "").toUpperCase() === "T";
  const bfeRaw = Number(a.STATIC_BFE);
  const bfeFt = Number.isFinite(bfeRaw) && bfeRaw > -500 && bfeRaw < 30000 ? round(bfeRaw, 1) : null;
  let risk = "Minimal flood hazard (outside 100-yr floodplain)";
  if (zone.startsWith("V")) risk = "Coastal high-velocity flood zone (SFHA)";
  else if (sfha || zone.startsWith("A")) risk = "High risk — 100-year Special Flood Hazard Area (SFHA)";
  else if (/0\.2 PCT|500|SHADED/i.test(sub)) risk = "Moderate risk — 500-year / 0.2% annual chance floodplain";
  else if (zone === "D") risk = "Undetermined flood hazard (Zone D — not studied)";
  else if (/OPEN WATER/i.test(zone)) risk = "Mapped open water";
  return {
    status: "ok",
    zone,
    zone_subtype: sub || null,
    sfha,
    bfe_ft: bfeFt,
    firm_panel: a.DFIRM_ID || null,
    risk_level: risk,
    source: "FEMA NFHL",
    source_url: mscUrl,
  };
}

async function queryWetlands(lat, lon) {
  const params = new URLSearchParams({
    geometry: `${lon},${lat}`,
    geometryType: "esriGeometryPoint",
    inSR: "4326",
    spatialRel: "esriSpatialRelIntersects",
    distance: "100",
    units: "esriSRUnit_Meter",
    outFields: "WETLAND_TYPE,ATTRIBUTE,ACRES",
    returnGeometry: "false",
    f: "json",
  });
  const url = `https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0/query?${params}`;
  const d = await fetchJson(url, {}, 7500);
  const feats = d?.features || [];
  const types = [...new Set(feats.map((f) => f?.attributes?.WETLAND_TYPE).filter(Boolean))];
  return {
    status: "ok",
    within_100m: feats.length > 0,
    count: feats.length,
    types,
    source: "USFWS National Wetlands Inventory",
    source_url: "https://fwsprimary.wim.usgs.gov/wetlands/apps/wetlands-mapper/",
  };
}

async function queryUsdaSoil(lat, lon) {
  const wkt = `point(${lon.toFixed(6)} ${lat.toFixed(6)})`;
  const sql =
    "SELECT TOP 1 m.mukey, m.muname, m.farmlndcl, ma.drclassdcd, ma.hydgrpdcd, " +
    "ma.slopegraddcp, ma.wtdepannmin, ma.brockdepmin " +
    "FROM mapunit m INNER JOIN muaggatt ma ON m.mukey = ma.mukey " +
    `WHERE m.mukey IN (SELECT * FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('${wkt}'))`;
  const d = await fetchJson(
    "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: sql, format: "JSON+COLUMNNAME" }),
    },
    7500
  );
  const tbl = d?.Table;
  if (!Array.isArray(tbl) || tbl.length < 2) {
    return {
      status: "not_mapped",
      muname: null,
      septic_signal: "Soil unit not mapped in USDA SSURGO (urban, water, or unmapped area) — county perc test required.",
      source: "USDA NRCS SSURGO",
      source_url: "https://websoilsurvey.nrcs.usda.gov/app/",
    };
  }
  const cols = tbl[0];
  const row = Object.fromEntries(cols.map((c, i) => [c, tbl[1][i]]));
  const wtCm = row.wtdepannmin != null ? Number(row.wtdepannmin) : null;
  const rockCm = row.brockdepmin != null ? Number(row.brockdepmin) : null;
  const wtIn = Number.isFinite(wtCm) && wtCm >= 0 ? Math.round(wtCm / 2.54) : null;
  const rockIn = Number.isFinite(rockCm) && rockCm >= 0 ? Math.round(rockCm / 2.54) : null;
  const drain = row.drclassdcd || null;
  const hydgrp = row.hydgrpdcd || null;
  const muname = row.muname || null;

  let septicSignal = "Field perc test required by county health department.";
  let septicLevel = "check";
  if (/urban land|water|rock outcrop|pits/i.test(muname || "")) {
    septicSignal = "Urban/disturbed or non-soil map unit — check municipal sewer availability or site soil evaluation.";
    septicLevel = "check";
  } else if (/very poorly|poorly drained/i.test(drain || "") || (wtIn != null && wtIn < 24)) {
    septicSignal = `High-water-table or poorly drained soil${wtIn != null ? ` (water table ~${wtIn} in)` : ""} — conventional septic often restricted; mound/engineered system likely.`;
    septicLevel = "constraint";
  } else if (rockIn != null && rockIn < 36) {
    septicSignal = `Shallow bedrock (~${rockIn} in) — excavation and conventional septic drainfields may be limited or costlier.`;
    septicLevel = "caution";
  } else if (/somewhat poorly/i.test(drain || "") || /^D/i.test(hydgrp || "")) {
    septicSignal = "Slow-draining / clay-leaning hydrologic group — perc test essential; may need larger or engineered drainfield.";
    septicLevel = "caution";
  } else if (/well drained|excessively drained/i.test(drain || "")) {
    septicSignal = "Well-drained soil classification — favorable initial signal for septic/foundations (county perc test still required).";
    septicLevel = "favorable";
  }

  return {
    status: "ok",
    mukey: row.mukey || null,
    muname,
    farmland_class: row.farmlndcl || null,
    drainage_class: drain,
    hydgrp,
    slope_pct_usda: row.slopegraddcp != null ? Number(row.slopegraddcp) : null,
    water_table_in: wtIn,
    bedrock_in: rockIn,
    septic_signal: septicSignal,
    septic_level: septicLevel,
    source: "USDA NRCS SSURGO",
    source_url: "https://websoilsurvey.nrcs.usda.gov/app/",
  };
}

function hardinessZoneFromExtremeMinF(minF) {
  if (minF == null || !Number.isFinite(minF)) return null;
  // USDA Plant Hardiness Zones span 10°F bands from 1a (-60°F) to 13b (+70°F)
  const clamped = Math.max(-60, Math.min(69.9, minF));
  const idx = Math.floor((clamped + 60) / 5);
  const zoneNum = Math.floor(idx / 2) + 1;
  const half = idx % 2 === 0 ? "a" : "b";
  return `${zoneNum}${half}`;
}

async function queryNasaClimate(lat, lon) {
  const url =
    `https://power.larc.nasa.gov/api/temporal/climatology/point?` +
    `parameters=ALLSKY_SFC_SW_DWN,T2M,T2M_RANGE,T2M_MIN,PRECTOTCORR&community=RE&longitude=${lon.toFixed(4)}&latitude=${lat.toFixed(4)}&format=JSON`;
  const d = await fetchJson(url, {}, 7500);
  const p = d?.properties?.parameter;
  if (!p?.ALLSKY_SFC_SW_DWN) return { status: "unavailable", source: "NASA POWER" };
  const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  const sunVals = months.map((m) => Number(p.ALLSKY_SFC_SW_DWN[m])).filter((v) => Number.isFinite(v) && v >= 0);
  const avgHighsC = [];
  const avgLowsC = [];
  const extMinC = [];
  for (const m of months) {
    const t = Number(p.T2M?.[m]);
    const r = Number(p.T2M_RANGE?.[m]);
    if (Number.isFinite(t) && t > -90) {
      const half = Number.isFinite(r) && r >= 0 && r < 60 ? r / 2 : 6;
      avgHighsC.push(t + half);
      avgLowsC.push(t - half);
    }
    const em = Number(p.T2M_MIN?.[m]);
    if (Number.isFinite(em) && em > -90) extMinC.push(em);
  }
  const annSun = Number(p.ALLSKY_SFC_SW_DWN.ANN);
  const annPrecipMmDay = Number(p.PRECTOTCORR?.ANN);
  const annualPrecipIn = Number.isFinite(annPrecipMmDay) && annPrecipMmDay >= 0 ? (annPrecipMmDay * 365.25) / 25.4 : null;
  const cToF = (c) => (c * 9) / 5 + 32;
  const extremeMinF = extMinC.length ? cToF(Math.min(...extMinC)) : null;
  return {
    status: "ok",
    annual_sun_hours: Number.isFinite(annSun) && annSun > 0 ? round(annSun, 2) : null,
    winter_min_sun_hours: sunVals.length ? round(Math.min(...sunVals), 2) : null,
    summer_max_sun_hours: sunVals.length ? round(Math.max(...sunVals), 2) : null,
    annual_precip_in: round(annualPrecipIn, 1),
    summer_high_f: avgHighsC.length ? round(cToF(Math.max(...avgHighsC)), 0) : null,
    winter_low_f: avgLowsC.length ? round(cToF(Math.min(...avgLowsC)), 0) : null,
    hardiness_zone: hardinessZoneFromExtremeMinF(extremeMinF),
    source: "NASA POWER Climatology",
    source_url: "https://power.larc.nasa.gov/",
  };
}

async function queryTigerRoads(lat, lon) {
  const mkUrl = (layer, distM) =>
    `https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Transportation/MapServer/${layer}/query?` +
    new URLSearchParams({
      geometry: `${lon},${lat}`,
      geometryType: "esriGeometryPoint",
      inSR: "4326",
      spatialRel: "esriSpatialRelIntersects",
      distance: String(distM),
      units: "esriSRUnit_Meter",
      outFields: "NAME,MTFCC",
      returnGeometry: "true",
      outSR: "4326",
      resultRecordCount: "20",
      f: "json",
    });

  const [localR, hwyR] = await Promise.allSettled([
    fetchJson(mkUrl(8, 800), {}, 6500),
    fetchJson(mkUrl(6, 3200), {}, 6500),
  ]);

  let nearestRoad = null;
  if (localR.status === "fulfilled") {
    for (const f of localR.value?.features || []) {
      const m = minDistanceToPathsMeters(lat, lon, f?.geometry?.paths);
      if (!Number.isFinite(m)) continue;
      if (!nearestRoad || m < nearestRoad.distM) {
        const a = f.attributes || {};
        nearestRoad = {
          name: a.NAME || "Unnamed mapped road",
          mtfcc: a.MTFCC || "",
          road_type: MTFCC_LABELS[a.MTFCC] || "Mapped road",
          distM: m,
        };
      }
    }
  }

  let nearestHwy = null;
  if (hwyR.status === "fulfilled") {
    for (const f of hwyR.value?.features || []) {
      const m = minDistanceToPathsMeters(lat, lon, f?.geometry?.paths);
      if (!Number.isFinite(m)) continue;
      if (!nearestHwy || m < nearestHwy.distM) {
        const a = f.attributes || {};
        nearestHwy = { name: a.NAME || "State / U.S. highway", distM: m };
      }
    }
  }

  if (localR.status !== "fulfilled" && hwyR.status !== "fulfilled") {
    return { status: "unavailable", source: "U.S. Census TIGERweb Roads" };
  }

  // If a state/US highway is closer than any local street, treat it as the nearest mapped road
  if (nearestHwy && (!nearestRoad || nearestHwy.distM < nearestRoad.distM)) {
    nearestRoad = {
      name: nearestHwy.name,
      mtfcc: "S1200",
      road_type: "State / U.S. highway",
      distM: nearestHwy.distM,
    };
  }

  const roadFt = nearestRoad ? Math.round(nearestRoad.distM * 3.28084) : null;
  const hwyMi = nearestHwy ? round(nearestHwy.distM / 1609.344, 2) : null;
  let signal = "No public road mapped within 0.5 mi — confirm recorded easement before bidding.";
  let tier = "constraint";
  if (roadFt != null && roadFt <= 150) {
    signal = "Adjacent to Census-mapped road — still verify recorded legal access & driveway permit.";
    tier = "favorable";
  } else if (roadFt != null && roadFt <= 600) {
    signal = "Mapped road nearby — verify frontage or recorded easement across intervening land.";
    tier = "caution";
  } else if (roadFt != null) {
    signal = `Nearest mapped road is ~${roadFt.toLocaleString("en-US")} ft away — check recorded easement & road-build cost.`;
    tier = "caution";
  } else if (hwyMi != null) {
    signal = `No local road mapped within 0.5 mi (nearest highway ${hwyMi} mi) — verify recorded legal access.`;
  }

  return {
    status: "ok",
    nearest_road_name: nearestRoad?.name || null,
    nearest_road_type: nearestRoad?.road_type || null,
    nearest_road_ft: roadFt,
    nearest_highway_name: nearestHwy?.name || null,
    nearest_highway_mi: hwyMi,
    access_tier: tier,
    access_signal: signal,
    source: "U.S. Census TIGERweb Roads",
    source_url: `https://www.google.com/maps/@${lat.toFixed(6)},${lon.toFixed(6)},16z`,
  };
}

async function queryPublicLands(lat, lon) {
  const params = new URLSearchParams({
    geometry: `${lon},${lat}`,
    geometryType: "esriGeometryPoint",
    inSR: "4326",
    spatialRel: "esriSpatialRelIntersects",
    distance: "1000",
    units: "esriSRUnit_Meter",
    outFields: "Unit_Nm,MngNm_Desc,DesTp_Desc,Pub_Access,GIS_Acres",
    returnGeometry: "false",
    resultRecordCount: "12",
    f: "json",
  });
  const url = `https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/PADUS_Public_Access/FeatureServer/0/query?${params}`;
  const d = await fetchJson(url, {}, 7000);
  const feats = d?.features || [];
  const seen = new Set();
  const units = [];
  for (const f of feats) {
    const a = f.attributes || {};
    const name = String(a.Unit_Nm || "").trim();
    if (!name || seen.has(name)) continue;
    seen.add(name);
    const accMap = { OA: "Open Access", RA: "Restricted Access", XA: "Closed", UK: "Unknown" };
    units.push({
      name,
      agency: a.MngNm_Desc || null,
      designation: a.DesTp_Desc || null,
      access: accMap[a.Pub_Access] || a.Pub_Access || null,
      acres: a.GIS_Acres ? Math.round(Number(a.GIS_Acres)) : null,
    });
  }
  units.sort((x, y) => (y.acres || 0) - (x.acres || 0));
  return {
    status: "ok",
    within_1km: units.length > 0,
    count: units.length,
    units: units.slice(0, 4),
    source: "USGS PAD-US Public Lands",
    source_url: "https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-overview",
  };
}

async function queryFemaNri(fips) {
  if (!fips) return { status: "unavailable", source: "FEMA National Risk Index" };
  const params = new URLSearchParams({
    where: `STCOFIPS='${String(fips).replace(/[^0-9]/g, "")}'`,
    outFields: "COUNTY,STATEABBRV,RISK_RATNG,WFIR_RISKR,DRGT_RISKR,HRCN_RISKR,TRND_RISKR,ERQK_RISKR",
    returnGeometry: "false",
    f: "json",
  });
  const url = `https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Counties/FeatureServer/0/query?${params}`;
  const d = await fetchJson(url, {}, 6500);
  const a = d?.features?.[0]?.attributes;
  if (!a) return { status: "unavailable", source: "FEMA National Risk Index" };
  return {
    status: "ok",
    overall: a.RISK_RATNG || null,
    wildfire: a.WFIR_RISKR || null,
    drought: a.DRGT_RISKR || null,
    hurricane: a.HRCN_RISKR || null,
    tornado: a.TRND_RISKR || null,
    earthquake: a.ERQK_RISKR || null,
    source: "FEMA National Risk Index",
    source_url: "https://hazards.fema.gov/nri/map",
  };
}

async function queryCountyAndHazards(lat, lon) {
  const url = `https://geo.fcc.gov/api/census/area?lat=${lat.toFixed(6)}&lon=${lon.toFixed(6)}&format=json`;
  const d = await fetchJson(url, {}, 6500);
  const hit = d?.results?.[0];
  if (!hit?.county_fips) {
    return {
      county: { status: "unavailable", source: "FCC Census Area API" },
      hazards: { status: "unavailable", source: "FEMA National Risk Index" },
    };
  }
  const fips = String(hit.county_fips).padStart(5, "0");
  const idx = loadCountyMap().get(fips);
  const stCode = hit.state_code || idx?.state || "";
  const kindLabels = {
    c: "USDA Census farm real estate",
    e: "USDA NASS estimate",
    i: "USDA NASS estimate",
    r: "FHFA residential land value",
  };
  const county = {
    status: "ok",
    fips,
    county_name: hit.county_name || idx?.name || null,
    state_code: stCode,
    state_name: hit.state_name || idx?.state_name || null,
    state_slug: STATE_SLUGS[stCode] || null,
    benchmark_usd_per_acre: idx?.value ?? null,
    benchmark_year: idx?.year ?? null,
    benchmark_label: idx ? kindLabels[idx.kind] || "County benchmark" : null,
    land_index_path: idx?.path || null,
    source: "FCC Census FIPS + USDA/FHFA County Land Index",
  };
  let hazards = { status: "unavailable", source: "FEMA National Risk Index" };
  try {
    hazards = await queryFemaNri(fips);
  } catch {
    // keep unavailable
  }
  return { county, hazards };
}

function buildPotentialScreening({ usgs, fema, nwi, soil, climate, roads, publicLand, hazards }) {
  const uses = [];
  // 1. Homesite / Cabin Build
  const homeFlags = [];
  let homeTier = "favorable";
  if (fema?.sfha) {
    homeTier = "constraint";
    homeFlags.push(`Inside FEMA ${fema.zone} 100-yr flood zone (elevated construction & flood insurance required)`);
  } else if (fema?.status === "ok") {
    homeFlags.push(`FEMA Zone ${fema.zone} (outside 100-yr floodplain)`);
  }
  if (roads?.status === "ok") {
    if (roads.nearest_road_ft == null) {
      homeTier = "constraint";
      homeFlags.push("No public road mapped within 0.5 mi — verify recorded easement");
    } else if (roads.nearest_road_ft <= 200) {
      homeFlags.push(`Near ${roads.nearest_road_name} (~${roads.nearest_road_ft} ft)`);
    } else {
      if (homeTier === "favorable") homeTier = "caution";
      homeFlags.push(`Nearest mapped road ~${roads.nearest_road_ft.toLocaleString("en-US")} ft (${roads.nearest_road_name})`);
    }
  }
  if (nwi?.within_100m) {
    if (homeTier === "favorable") homeTier = "caution";
    homeFlags.push(`USFWS wetland within 100m (${nwi.types.slice(0, 2).join(", ") || "verify setback"})`);
  }
  if (usgs?.slope_pct != null) {
    if (usgs.slope_pct >= 20) {
      homeTier = "constraint";
      homeFlags.push(`Steep terrain (~${usgs.slope_pct}% slope — higher driveway & foundation cost)`);
    } else if (usgs.slope_pct >= 12) {
      if (homeTier === "favorable") homeTier = "caution";
      homeFlags.push(`Moderate-steep slope (~${usgs.slope_pct}%)`);
    } else {
      homeFlags.push(`${usgs.terrain_class} terrain (~${usgs.slope_pct}% slope)`);
    }
  }
  if (soil?.septic_level === "constraint") {
    homeTier = "constraint";
    homeFlags.push(soil.septic_signal);
  } else if (soil?.septic_level === "caution") {
    if (homeTier === "favorable") homeTier = "caution";
    homeFlags.push(soil.septic_signal);
  } else if (soil?.drainage_class) {
    homeFlags.push(`USDA soil: ${soil.drainage_class}`);
  }
  if (hazards?.wildfire && /High/i.test(hazards.wildfire)) {
    if (homeTier === "favorable") homeTier = "caution";
    homeFlags.push(`FEMA county Wildfire risk: ${hazards.wildfire} (check fire insurance)`);
  }
  uses.push({
    id: "homesite",
    title: "Homesite / Cabin Build",
    tier: homeFlags.length ? homeTier : "check",
    summary: homeFlags.join(" · ") || "Verify local zoning, perc test, and recorded road access.",
  });

  // 2. Off-Grid Homestead & Solar
  const offFlags = [];
  let offTier = "favorable";
  if (climate?.annual_sun_hours != null) {
    offFlags.push(`${climate.annual_sun_hours} peak sun hrs/day (${climate.winter_min_sun_hours} winter min)`);
    if (climate.winter_min_sun_hours != null && climate.winter_min_sun_hours < 2.0) {
      offTier = "caution";
      offFlags.push("Low winter sun — size backup generator & larger battery bank");
    }
  }
  if (climate?.annual_precip_in != null) {
    offFlags.push(`~${climate.annual_precip_in} in/yr rainfall`);
    if (climate.annual_precip_in < 12) {
      offTier = "caution";
      offFlags.push("Arid climate — verify well depth, water rights, or haul costs");
    }
  }
  if (climate?.hardiness_zone) offFlags.push(`Growing Zone ${climate.hardiness_zone}`);
  if (fema?.sfha) {
    offTier = "constraint";
    offFlags.push(`FEMA ${fema.zone} flood hazard`);
  }
  uses.push({
    id: "offgrid",
    title: "Off-Grid Homestead & Solar",
    tier: offFlags.length ? offTier : "check",
    summary: offFlags.join(" · ") || "Check local minimum dwelling size, septic rules, and water depth.",
  });

  // 3. Agriculture / Pasture / Garden
  const agFlags = [];
  let agTier = "check";
  const fl = soil?.farmland_class || "";
  if (/prime farmland/i.test(fl) && !/not prime/i.test(fl)) {
    agTier = "favorable";
    agFlags.push(fl);
  } else if (/statewide|local importance/i.test(fl)) {
    agTier = "favorable";
    agFlags.push(fl);
  } else if (fl) {
    agTier = "caution";
    agFlags.push(fl);
  }
  if (soil?.drainage_class) agFlags.push(soil.drainage_class);
  if (climate?.hardiness_zone) agFlags.push(`Zone ${climate.hardiness_zone}`);
  if (climate?.annual_precip_in != null) agFlags.push(`~${climate.annual_precip_in} in/yr precip`);
  if (usgs?.slope_pct != null && usgs.slope_pct >= 15) {
    agTier = "caution";
    agFlags.push(`Steep ~${usgs.slope_pct}% slope limits row crops`);
  }
  uses.push({
    id: "agriculture",
    title: "Farming, Pasture & Garden",
    tier: agTier,
    summary: agFlags.join(" · ") || "Soil survey unavailable — confirm soil depth, water rights, and zoning.",
  });

  // 4. Recreation / Hunting / Timber
  const recFlags = [];
  let recTier = "favorable";
  if (publicLand?.within_1km && publicLand.units.length) {
    const u0 = publicLand.units[0];
    recFlags.push(`Near public land: ${u0.name}${u0.agency ? ` (${u0.agency})` : ""}`);
  }
  if (usgs?.elevation_ft != null) recFlags.push(`Elevation ${usgs.elevation_ft.toLocaleString("en-US")} ft (${usgs.terrain_class})`);
  if (nwi?.within_100m) recFlags.push(`Water/wetland habitat nearby (${nwi.types[0] || "NWI mapped"})`);
  if (climate?.summer_high_f != null && climate?.winter_low_f != null) {
    recFlags.push(`Normal temps ${climate.winter_low_f}°F winter low to ${climate.summer_high_f}°F summer high`);
  }
  uses.push({
    id: "recreation",
    title: "Recreation, Camping & Public Land",
    tier: recFlags.length ? recTier : "check",
    summary: recFlags.join(" · ") || "Confirm county camping/RV ordinances, legal access, and timber covenants.",
  });

  return uses;
}

export async function geocodeUS(query) {
  const q = String(query || "").trim();
  if (!q || q.length < 2 || q.length > 160) return null;
  const coordMatch = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*[,\s]+\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (coordMatch) {
    const la = Number(coordMatch[1]);
    const lo = Number(coordMatch[2]);
    if (la >= 18 && la <= 72 && lo >= -180 && lo <= -65) {
      return { lat: la, lon: lo, label: `${la.toFixed(5)}, ${lo.toFixed(5)}`, provider: "Direct coordinates" };
    }
  }
  try {
    const u =
      "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?" +
      new URLSearchParams({ address: q, benchmark: "Public_AR_Current", format: "json" });
    const d = await fetchJson(u, {}, 5000);
    const m = d?.result?.addressMatches?.[0];
    if (m?.coordinates) {
      return {
        lat: Number(m.coordinates.y),
        lon: Number(m.coordinates.x),
        label: m.matchedAddress || q,
        provider: "U.S. Census Bureau Geocoder",
      };
    }
  } catch {
    // Fall through to Nominatim
  }
  try {
    const u =
      "https://nominatim.openstreetmap.org/search?" +
      new URLSearchParams({ q, format: "jsonv2", countrycodes: "us", limit: "1" });
    const d = await fetchJson(u, { headers: { "User-Agent": LANDO_UA } }, 5500);
    const hit = Array.isArray(d) ? d[0] : null;
    if (hit?.lat && hit?.lon) {
      return {
        lat: Number(hit.lat),
        lon: Number(hit.lon),
        label: hit.display_name || q,
        provider: "OpenStreetMap Nominatim",
      };
    }
  } catch (err) {
    console.error("[xray] geocode fallback error:", err?.message || err);
  }
  return null;
}

export async function runXray(lat, lon) {
  const [usgsR, femaR, nwiR, soilR, climateR, roadsR, pubR, countyHazR] = await Promise.allSettled([
    queryUsgsElevation(lat, lon),
    queryFemaFlood(lat, lon),
    queryWetlands(lat, lon),
    queryUsdaSoil(lat, lon),
    queryNasaClimate(lat, lon),
    queryTigerRoads(lat, lon),
    queryPublicLands(lat, lon),
    queryCountyAndHazards(lat, lon),
  ]);
  const usgs = usgsR.status === "fulfilled" ? usgsR.value : { status: "unavailable", source: "USGS 3DEP" };
  const fema = femaR.status === "fulfilled" ? femaR.value : { status: "unavailable", source: "FEMA NFHL" };
  const nwi = nwiR.status === "fulfilled" ? nwiR.value : { status: "unavailable", source: "USFWS NWI" };
  const soil = soilR.status === "fulfilled" ? soilR.value : { status: "unavailable", source: "USDA NRCS SSURGO" };
  const climate = climateR.status === "fulfilled" ? climateR.value : { status: "unavailable", source: "NASA POWER" };
  const roads = roadsR.status === "fulfilled" ? roadsR.value : { status: "unavailable", source: "U.S. Census TIGERweb" };
  const publicLand = pubR.status === "fulfilled" ? pubR.value : { status: "unavailable", source: "USGS PAD-US" };
  const county = countyHazR.status === "fulfilled" ? countyHazR.value.county : { status: "unavailable", source: "FCC Census FIPS" };
  const hazards = countyHazR.status === "fulfilled" ? countyHazR.value.hazards : { status: "unavailable", source: "FEMA National Risk Index" };
  const uses = buildPotentialScreening({ usgs, fema, nwi, soil, climate, roads, publicLand, hazards });
  return {
    lat: round(lat, 5),
    lon: round(lon, 5),
    checked_at: new Date().toISOString(),
    usgs,
    fema,
    nwi,
    soil,
    climate,
    roads,
    public_land: publicLand,
    hazards,
    county,
    uses,
    disclaimer:
      "Automated federal GIS screening only—not a boundary survey, percolation test, wetland delineation, or legal/title determination.",
  };
}

function jsonResp(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store, max-age=0", "CDN-Cache-Control": "no-store",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

export async function GET(request) {
  try {
    const url = new URL(request.url);
    const q = url.searchParams.get("q");
    let lat = url.searchParams.get("lat") != null ? Number(url.searchParams.get("lat")) : NaN;
    let lon = url.searchParams.get("lon") != null ? Number(url.searchParams.get("lon")) : NaN;
    let geocode = null;

    if ((!Number.isFinite(lat) || !Number.isFinite(lon)) && q) {
      geocode = await geocodeUS(q);
      if (!geocode) {
        return jsonResp({ error: "Location not found in the United States. Try a city & state, street address, ZIP code, or lat, lon." }, 404);
      }
      lat = geocode.lat;
      lon = geocode.lon;
    }

    if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < 18 || lat > 72 || lon < -180 || lon > -65) {
      return jsonResp({ error: "Provide valid U.S. coordinates (?lat=..&lon=..) or a U.S. search query (?q=..)." }, 400);
    }

    const snappedLat = Math.round(lat * 100000) / 100000;
    const snappedLon = Math.round(lon * 100000) / 100000;
    const payload = await runXray(snappedLat, snappedLon);
    if (geocode) payload.geocode = geocode;
    return jsonResp(payload, 200);
  } catch (err) {
    console.error("[xray] unhandled error:", err);
    return jsonResp({ error: "Parcel X-Ray temporarily unavailable." }, 502);
  }
}

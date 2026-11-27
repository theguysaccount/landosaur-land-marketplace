/**
 * Landosaur Live Federal Parcel X-Ray API (Vercel Fluid Compute — Node.js Web API Function).
 *
 * Queries 6 authoritative public federal/official datasets in parallel for any coordinates in the 50 U.S. states:
 *   1. USGS 3DEP Elevation Point Query Service (5-point grid -> elevation, relief, slope %, aspect)
 *   2. FEMA National Flood Hazard Layer (NFHL MapServer/28 -> flood zone, SFHA, BFE, FIRM panel)
 *   3. USFWS National Wetlands Inventory (100m buffer -> wetland types & proximity)
 *   4. USDA NRCS SSURGO Soil Data Access (soil map unit, prime farmland, drainage, hydgrp, water table, bedrock)
 *   5. NASA POWER Climatology (annual/winter/summer peak sun hours, temps, annual precipitation)
 *   6. FCC Census Area FIPS joined against bundled 3,115-county USDA/FHFA Land Index
 *
 * Also supports ?q=<address or place> via U.S. Census Geocoder + OpenStreetMap Nominatim (US-bounded).
 * Zero fabricated fallbacks: unavailable upstreams report status="unavailable" honestly.
 */
import fs from "node:fs";
import path from "node:path";

const BROWSER_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";
const LANDO_UA = "landosaur-parcel-xray/1.0 (+https://landosaur.com)";

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

async function queryUsgsElevation(lat, lon) {
  const dLat = 0.00045; // ~50 meters
  const dLon = 0.00045 / Math.max(0.2, Math.cos((lat * Math.PI) / 180));
  const pts = [
    ["c", lat, lon],
    ["n", lat + dLat, lon],
    ["s", lat - dLat, lon],
    ["e", lat, lon + dLon],
    ["w", lat, lon - dLon],
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
  const all = Object.values(vals);
  const minFt = Math.min(...all);
  const maxFt = Math.max(...all);
  const reliefFt = maxFt - minFt;
  let slopePct = null;
  let aspect = null;
  if (vals.n != null && vals.s != null && vals.e != null && vals.w != null) {
    const spanFt = 100 * 3.28084; // 100m N-S / E-W span in feet
    const dzDy = (vals.n - vals.s) / spanFt;
    const dzDx = (vals.e - vals.w) / spanFt;
    slopePct = Math.sqrt(dzDx * dzDx + dzDy * dzDy) * 100;
    if (slopePct >= 2) {
      // Aspect = direction the slope faces (downhill vector = (-dzDx, -dzDy))
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
  return {
    status: "ok",
    elevation_ft: round(vals.c, 0),
    min_ft: round(minFt, 0),
    max_ft: round(maxFt, 0),
    relief_ft: round(reliefFt, 1),
    slope_pct: round(slopePct, 1),
    terrain_class: terrainClass,
    aspect,
    source: "USGS 3DEP 1m/10m LiDAR",
    source_url: `https://apps.nationalmap.gov/viewer/`,
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

async function queryNasaClimate(lat, lon) {
  const url =
    `https://power.larc.nasa.gov/api/temporal/climatology/point?` +
    `parameters=ALLSKY_SFC_SW_DWN,T2M,T2M_RANGE,PRECTOTCORR&community=RE&longitude=${lon.toFixed(4)}&latitude=${lat.toFixed(4)}&format=JSON`;
  const d = await fetchJson(url, {}, 7500);
  const p = d?.properties?.parameter;
  if (!p?.ALLSKY_SFC_SW_DWN) return { status: "unavailable", source: "NASA POWER" };
  const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  const sunVals = months.map((m) => Number(p.ALLSKY_SFC_SW_DWN[m])).filter((v) => Number.isFinite(v) && v >= 0);
  const avgHighsC = [];
  const avgLowsC = [];
  for (const m of months) {
    const t = Number(p.T2M?.[m]);
    const r = Number(p.T2M_RANGE?.[m]);
    if (Number.isFinite(t) && t > -90) {
      const half = Number.isFinite(r) && r >= 0 && r < 60 ? r / 2 : 6;
      avgHighsC.push(t + half);
      avgLowsC.push(t - half);
    }
  }
  const annSun = Number(p.ALLSKY_SFC_SW_DWN.ANN);
  const annPrecipMmDay = Number(p.PRECTOTCORR?.ANN);
  const annualPrecipIn = Number.isFinite(annPrecipMmDay) && annPrecipMmDay >= 0 ? (annPrecipMmDay * 365.25) / 25.4 : null;
  const cToF = (c) => (c * 9) / 5 + 32;
  return {
    status: "ok",
    annual_sun_hours: Number.isFinite(annSun) && annSun > 0 ? round(annSun, 2) : null,
    winter_min_sun_hours: sunVals.length ? round(Math.min(...sunVals), 2) : null,
    summer_max_sun_hours: sunVals.length ? round(Math.max(...sunVals), 2) : null,
    annual_precip_in: round(annualPrecipIn, 1),
    summer_high_f: avgHighsC.length ? round(cToF(Math.max(...avgHighsC)), 0) : null,
    winter_low_f: avgLowsC.length ? round(cToF(Math.min(...avgLowsC)), 0) : null,
    source: "NASA POWER Climatology",
    source_url: "https://power.larc.nasa.gov/",
  };
}

async function queryCountyBenchmark(lat, lon) {
  const url = `https://geo.fcc.gov/api/census/area?lat=${lat.toFixed(6)}&lon=${lon.toFixed(6)}&format=json`;
  const d = await fetchJson(url, {}, 6500);
  const hit = d?.results?.[0];
  if (!hit?.county_fips) return { status: "unavailable", source: "FCC Census Area API" };
  const fips = String(hit.county_fips).padStart(5, "0");
  const idx = loadCountyMap().get(fips);
  const stCode = hit.state_code || idx?.state || "";
  const kindLabels = {
    c: "USDA Census farm real estate",
    e: "USDA NASS estimate",
    i: "USDA NASS estimate",
    r: "FHFA residential land value",
  };
  return {
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
}

function buildPotentialScreening({ usgs, fema, nwi, soil, climate }) {
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
  if (nwi?.within_100m) {
    if (homeTier === "favorable") homeTier = "caution";
    homeFlags.push(`USFWS mapped wetland within 100m (${nwi.types.slice(0, 2).join(", ") || "verify setback"})`);
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
    offFlags.push(`${climate.annual_sun_hours} peak sun hrs/day avg (${climate.winter_min_sun_hours} winter min)`);
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
  if (usgs?.elevation_ft != null) recFlags.push(`Elevation ${usgs.elevation_ft.toLocaleString("en-US")} ft (${usgs.terrain_class})`);
  if (nwi?.within_100m) recFlags.push(`Water/wetland habitat nearby (${nwi.types[0] || "NWI mapped"})`);
  if (climate?.summer_high_f != null && climate?.winter_low_f != null) {
    recFlags.push(`Temps ${climate.winter_low_f}°F winter low to ${climate.summer_high_f}°F summer high`);
  }
  uses.push({
    id: "recreation",
    title: "Recreation, Camping & Timber",
    tier: recFlags.length ? recTier : "check",
    summary: recFlags.join(" · ") || "Confirm county camping/RV ordinances, legal access, and timber covenants.",
  });

  return uses;
}

async function geocodeUS(query) {
  const q = String(query || "").trim();
  if (!q || q.length < 2 || q.length > 160) return null;
  // Direct "lat, lon" shortcut
  const coordMatch = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*[,\s]+\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (coordMatch) {
    const la = Number(coordMatch[1]);
    const lo = Number(coordMatch[2]);
    if (la >= 18 && la <= 72 && lo >= -180 && lo <= -65) {
      return { lat: la, lon: lo, label: `${la.toFixed(5)}, ${lo.toFixed(5)}`, provider: "Direct coordinates" };
    }
  }
  // 1. Official U.S. Census Geocoder (best for street addresses)
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
    // Fall through to Nominatim for towns, counties, ZIPs, landmarks
  }
  // 2. OpenStreetMap Nominatim (US only)
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
  const [usgsR, femaR, nwiR, soilR, climateR, countyR] = await Promise.allSettled([
    queryUsgsElevation(lat, lon),
    queryFemaFlood(lat, lon),
    queryWetlands(lat, lon),
    queryUsdaSoil(lat, lon),
    queryNasaClimate(lat, lon),
    queryCountyBenchmark(lat, lon),
  ]);
  const usgs = usgsR.status === "fulfilled" ? usgsR.value : { status: "unavailable", source: "USGS 3DEP" };
  const fema = femaR.status === "fulfilled" ? femaR.value : { status: "unavailable", source: "FEMA NFHL" };
  const nwi = nwiR.status === "fulfilled" ? nwiR.value : { status: "unavailable", source: "USFWS NWI" };
  const soil = soilR.status === "fulfilled" ? soilR.value : { status: "unavailable", source: "USDA NRCS SSURGO" };
  const climate = climateR.status === "fulfilled" ? climateR.value : { status: "unavailable", source: "NASA POWER" };
  const county = countyR.status === "fulfilled" ? countyR.value : { status: "unavailable", source: "FCC Census FIPS" };
  const uses = buildPotentialScreening({ usgs, fema, nwi, soil, climate });
  return {
    lat: round(lat, 5),
    lon: round(lon, 5),
    checked_at: new Date().toISOString(),
    usgs,
    fema,
    nwi,
    soil,
    climate,
    county,
    uses,
    disclaimer:
      "Automated federal GIS screening only—not a boundary survey, percolation test, wetland delineation, or legal/title determination.",
  };
}

function jsonResp(body, status = 200, cacheControl = "no-store") {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": cacheControl,
      "CDN-Cache-Control": cacheControl,
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

    // Snap coordinates slightly for high CDN cache hit rate (~1.1m precision)
    const snappedLat = Math.round(lat * 100000) / 100000;
    const snappedLon = Math.round(lon * 100000) / 100000;
    const payload = await runXray(snappedLat, snappedLon);
    if (geocode) payload.geocode = geocode;
    return jsonResp(payload, 200, "public, s-maxage=86400, stale-while-revalidate=604800");
  } catch (err) {
    console.error("[xray] unhandled error:", err);
    return jsonResp({ error: "Parcel X-Ray temporarily unavailable." }, 502);
  }
}

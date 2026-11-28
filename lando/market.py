"""50-state USDA/FHFA Land Price Observatory and deterministic market analytics.

Every figure is read directly from:
  - data/market/usda-land-values.json (USDA NASS 2010-2026 annual state & U.S. agricultural values)
  - data/usda/land-index-counties.json (USDA/FHFA per-acre benchmarks by county and equivalent)
  - live Landosaur official agency catalog (never mixed with USDA estimates)
"""
import html
import json
import os
import statistics

from . import adapters, config
from .model import STATE_NAMES, slugify


def esc(t):
    return html.escape("" if t is None else str(t), quote=True)


def usd(v, decimals=0, dash="Not reported"):
    if v is None:
        return dash
    if decimals == 0:
        return "$" + "{:,}".format(int(round(v)))
    return ("${:,.%df}" % decimals).format(v)


def pct(v, dash="Not reported"):
    if v is None:
        return dash
    sign = "+" if v > 0 else ""
    return "%s%.1f%%" % (sign, v)


def load_usda(data_dir=None):
    path = os.path.join(data_dir or config.DATA, "market", "usda-land-values.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_counties_by_state(data_dir=None):
    path = os.path.join(data_dir or config.DATA, "usda", "land-index-counties.json")
    by_state = {}
    if not os.path.exists(path):
        return by_state
    with open(path, encoding="utf-8") as fh:
        for row in json.load(fh):
            fips, name, st, st_name, page, value, year, kind = row[:8]
            yr_str = str(year) if year is not None else ""
            by_state.setdefault(st, []).append({
                "fips": fips,
                "name": name,
                "state": st,
                "state_name": st_name,
                "path": page,
                "value": value,
                "year": year,
                "kind": kind,
                "kind_label": {
                    "c": ("USDA %s Census" % yr_str).strip(),
                    "e": ("USDA %s Estimate" % yr_str).strip(),
                    "i": ("USDA %s Estimate" % yr_str).strip(),
                    "r": ("FHFA %s Residential Land" % yr_str).strip(),
                }.get(kind, yr_str or "Benchmark unavailable") if value is not None else "Not reported",
            })
    for st in by_state:
        by_state[st].sort(key=lambda c: (c["value"] is None, c["value"] or 0, c["name"]))
    return by_state


class MarketData(object):
    def __init__(self, catalog, data_dir=None):
        self.cat = catalog
        self.data_dir = data_dir or catalog.data_dir
        self.usda = load_usda(self.data_dir)
        self.counties_by_state = load_counties_by_state(self.data_dir)
        self._obs_index = {}
        self._geo_by_code = {}
        self._sources_by_id = {}
        if self.usda:
            for g in self.usda.get("geographies", []):
                self._geo_by_code[g["code"]] = g
            for s in self.usda.get("sources", []):
                self._sources_by_id[s["id"]] = s
            for o in self.usda.get("observations", []):
                self._obs_index.setdefault((o["geographyCode"], o["metric"]), []).append(o)
            for k in self._obs_index:
                self._obs_index[k].sort(key=lambda x: x["year"])
        self.latest_year = self.usda["latestYear"] if self.usda else 2026
        self.first_year = self.usda["firstYear"] if self.usda else 2010
        self.metrics = self.usda["metrics"] if self.usda else []

    def series(self, code, metric):
        return self._obs_index.get((code, metric), [])

    def latest_values(self, code):
        out = {}
        for m in self.metrics:
            mid = m["id"]
            obs = self.series(code, mid)
            latest = next((o for o in reversed(obs) if o["year"] == self.latest_year), None)
            out[mid] = latest["valueUsdPerAcre"] if latest else None
        return out

    def span_change(self, code, metric="farm_real_estate"):
        pts = [o for o in self.series(code, metric) if o.get("valueUsdPerAcre") is not None]
        if len(pts) < 2 or not pts[0]["valueUsdPerAcre"]:
            return None, None, None
        first, last = pts[0], pts[-1]
        chg = (last["valueUsdPerAcre"] / float(first["valueUsdPerAcre"]) - 1.0) * 100.0
        return round(chg, 1), first["year"], last["year"]

    def all_states(self):
        """All 50 US states with USDA values (where published), county ranges, and live catalog counts."""
        rows = []
        us_vals = self.latest_values("US")
        for code, name in sorted(STATE_NAMES.items(), key=lambda kv: kv[1]):
            if code == "DC":
                continue
            geo = self._geo_by_code.get(code, {"code": code, "name": name, "published": False})
            vals = self.latest_values(code) if geo.get("published") else {m["id"]: None for m in self.metrics}
            chg, y0, y1 = self.span_change(code, "farm_real_estate") if geo.get("published") else (None, None, None)
            counties = self.counties_by_state.get(code, [])
            priced_counties = [c for c in counties if c.get("value")]
            st_cat = self.cat.states.get(code)
            active_listings = [r for r in st_cat["listings"] if r["available"]] if st_cat else []
            priced_listings = [r for r in active_listings if r.get("price") and r.get("acres")]
            rows.append({
                "code": code,
                "name": name,
                "slug": slugify(name),
                "path": "/land-prices/%s/" % slugify(name),
                "browse_path": "/land-for-sale/%s/" % slugify(name) if st_cat else None,
                "published": bool(geo.get("published")),
                "note": geo.get("note", ""),
                "values": vals,
                "us_values": us_vals,
                "change_pct": chg,
                "change_start": y0,
                "change_end": y1,
                "counties": counties,
                "county_count": len(counties),
                "county_min": priced_counties[0] if priced_counties else None,
                "county_max": priced_counties[-1] if priced_counties else None,
                "county_median": round(statistics.median([c["value"] for c in priced_counties])) if priced_counties else None,
                "active_count": len(active_listings),
                "active_listings": active_listings,
                "priced_count": len(priced_listings),
                "min_ppa": min((r["price"] / r["acres"] for r in priced_listings), default=None),
                "median_ppa": round(statistics.median([r["price"] / r["acres"] for r in priced_listings]), 2) if priced_listings else None,
            })
        # Compute deterministic rank (1 = lowest published farm real estate value; ties share rank)
        ranked = sorted(
            [r for r in rows if r["values"].get("farm_real_estate") is not None],
            key=lambda r: r["values"]["farm_real_estate"],
        )
        rank_map = {}
        for i, r in enumerate(ranked):
            v = r["values"]["farm_real_estate"]
            if i > 0 and ranked[i - 1]["values"]["farm_real_estate"] == v:
                rank_map[r["code"]] = rank_map[ranked[i - 1]["code"]]
            else:
                rank_map[r["code"]] = i + 1
        for r in rows:
            r["rank"] = rank_map.get(r["code"])
            r["ranked_total"] = len(ranked)
        return rows

    def cheapest_listings(self, limit=150):
        """Active offerings publishing both positive price/min-bid and positive acreage, ranked by $/acre."""
        cur = [r for r in self.cat.current() if r.get("price") and r["price"] > 0 and r.get("acres") and r["acres"] > 0]
        cur.sort(key=lambda r: (r["price"] / r["acres"], r["price"], r["id"]))
        return cur[:limit]

    def acreage_bands(self):
        bands = (
            ("Under 0.25 acres", lambda a: a < 0.25),
            ("0.25 – 0.99 acres", lambda a: 0.25 <= a < 1.0),
            ("1 – 4.99 acres", lambda a: 1.0 <= a < 5.0),
            ("5 – 19.99 acres", lambda a: 5.0 <= a < 20.0),
            ("20 – 49.99 acres", lambda a: 20.0 <= a < 50.0),
            ("50+ acres", lambda a: a >= 50.0),
        )
        cur = self.cat.current()
        out = []
        for label, pred in bands:
            all_in = [r for r in cur if r.get("acres") and pred(r["acres"])]
            priced = [r for r in all_in if r.get("price") and r["price"] > 0]
            cash = [r for r in priced if r.get("price_kind") == "cash"]
            bids = [r for r in priced if r.get("price_kind") == "min_bid"]
            out.append({
                "label": label,
                "count": len(all_in),
                "priced_count": len(priced),
                "cash_count": len(cash),
                "bid_count": len(bids),
                "total_acres": round(sum(r["acres"] for r in all_in), 2),
                "median_price": round(statistics.median([r["price"] for r in priced]), 2) if priced else None,
                "median_ppa": round(statistics.median([r["price"] / r["acres"] for r in priced]), 2) if priced else None,
                "min_ppa": round(min(r["price"] / r["acres"] for r in priced), 2) if priced else None,
            })
        return out

    def state_faqs(self, st):
        """Truthful, deterministic FAQs matching visible copy & FAQPage JSON-LD verbatim."""
        y = self.latest_year
        name = st["name"]
        vals = st["values"]
        us = st["us_values"]
        faqs = []
        if st["published"] and vals.get("farm_real_estate") is not None:
            fre = vals["farm_real_estate"]
            crop = vals.get("cropland")
            past = vals.get("pasture")
            extra = []
            if crop is not None:
                extra.append("cropland averages %s/acre" % usd(crop))
            if past is not None:
                extra.append("pasture averages %s/acre" % usd(past))
            extra_txt = (" By category, %s." % " and ".join(extra)) if extra else ""
            rank_txt = " That ranks #%d lowest among %d USDA-reported states" % (st["rank"], st["ranked_total"]) if st["rank"] else ""
            us_txt = " (versus %s/acre nationally)." % usd(us.get("farm_real_estate")) if us.get("farm_real_estate") else "."
            faqs.append((
                "What is the average price per acre of land in %s in %d?" % (name, y),
                "According to USDA NASS (%d), %s farm real estate averages %s per acre (including agricultural land and buildings).%s%s%s Agricultural averages are a regional reference, not an appraisal of residential or recreational lots." % (
                    y, name, usd(fre), extra_txt, rank_txt, us_txt),
            ))
            faqs.append((
                "How much does 20 acres of rural land cost in %s?" % name,
                "At the %d USDA %s farm real estate benchmark of %s per acre, 20 agricultural acres equate to roughly %s as a benchmark reference (%s for 10 acres, %s for 40 acres). Actual parcel prices vary widely by county, road access, utilities, water, and zoning—always check county benchmarks and closed local comps." % (
                    y, name, usd(fre), usd(fre * 20), usd(fre * 10), usd(fre * 40)),
            ))
        else:
            faqs.append((
                "Why are USDA annual state averages not shown for %s?" % name,
                "USDA NASS excludes %s from its annual contiguous-48 agricultural land value series. Landosaur never fabricates missing USDA averages; instead, use the county benchmarks and active official agency listings below where available." % name,
            ))
        if st["county_min"] and st["county_max"]:
            cmin, cmax = st["county_min"], st["county_max"]
            faqs.append((
                "Which counties have the lowest and highest land values in %s?" % name,
                "Across %d %s counties in the US County Land Index, %s has the lowest benchmark at %s per acre (%s), while %s has the highest at %s per acre (%s); the statewide county median is %s per acre." % (
                    st["county_count"], name, cmin["name"], usd(cmin["value"]), cmin["kind_label"],
                    cmax["name"], usd(cmax["value"]), cmax["kind_label"], usd(st["county_median"])),
            ))
        if st["change_pct"] is not None:
            faqs.append((
                "How have %s land prices changed since %d?" % (name, st["change_start"]),
                "From %d to %d, USDA %s farm real estate changed %s in nominal dollars per acre. Because USDA series measure agricultural real estate broadly, individual buildable or recreational tracts can move differently." % (
                    st["change_start"], st["change_end"], name, pct(st["change_pct"])),
            ))
        if st["active_count"] > 0:
            faqs.append((
                "Does Landosaur track official government or auction land for sale in %s?" % name,
                "Yes. Landosaur currently indexes %s active public-agency land offerings in %s, read daily from official agency feeds with every listing linked directly to its government source." % (
                    "{:,}".format(st["active_count"]), name),
            ))
        else:
            faqs.append((
                "How can I find government or tax-sale land for sale in %s?" % name,
                "Landosaur does not yet crawl an active state agency inventory in %s, so we show zero live listings honestly rather than scraping unverified ads. Use the %s county value benchmarks below, our interactive land analyzer (/analyze/), and our tax-sale & due-diligence guides while we expand official state connectors." % (
                    name, name),
            ))
        return faqs

    def svg_trend_chart(self, code, title):
        """Render a clean, responsive inline SVG multi-series line chart (2010-2026) with zero JS needed."""
        palette = [
            ("farm_real_estate", "Farm real estate", "#236b43"),
            ("cropland", "Cropland", "#b5602f"),
            ("pasture", "Pasture", "#5f8c3d"),
        ]
        years = list(range(self.first_year, self.latest_year + 1))
        series_data = []
        all_vals = []
        for mid, label, color in palette:
            by_y = {o["year"]: o["valueUsdPerAcre"] for o in self.series(code, mid)}
            pts = [(y, by_y.get(y)) for y in years]
            vals = [v for _, v in pts if v is not None]
            if vals:
                all_vals.extend(vals)
                series_data.append((label, color, pts))
        if not series_data or not all_vals:
            return ""
        w, h = 760, 290
        pl, pr, pt, pb = 68, 22, 18, 36
        pw, ph = w - pl - pr, h - pt - pb
        ymax = max(all_vals) * 1.12
        ymin = 0.0  # honest zero baseline so slopes are never distorted
        if ymax <= 0:
            return ""

        def sx(y):
            return pl + pw * ((y - years[0]) / float(max(1, years[-1] - years[0])))

        def sy(v):
            return pt + ph * (1.0 - (v - ymin) / (ymax - ymin))

        grid = []
        for i in range(5):
            val = ymin + (ymax - ymin) * i / 4.0
            yy = sy(val)
            grid.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="var(--line)" stroke-width="1"/>' % (pl, yy, w - pr, yy))
            grid.append('<text x="%d" y="%.1f" text-anchor="end" font-size="11" fill="var(--muted)">%s</text>' % (pl - 8, yy + 4, esc(usd(val))))
        xlabels = []
        step = 2 if len(years) > 10 else 1
        for y in years[::step] + ([years[-1]] if years[-1] not in years[::step] else []):
            xx = sx(y)
            xlabels.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="11" fill="var(--muted)">%d</text>' % (xx, h - 10, y))

        paths = []
        legend = []
        for label, color, pts in series_data:
            # Split segments cleanly across missing/null years (never bridge missing data)
            segs, cur_seg = [], []
            for y, v in pts:
                if v is None:
                    if cur_seg:
                        segs.append(cur_seg)
                        cur_seg = []
                else:
                    cur_seg.append((sx(y), sy(v), y, v))
            if cur_seg:
                segs.append(cur_seg)
            for seg in segs:
                if len(seg) >= 2:
                    d = "M " + " L ".join("%.1f %.1f" % (x, y) for x, y, _, _ in seg)
                    paths.append('<path d="%s" fill="none" stroke="%s" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>' % (d, color))
                for x, y, yr, val in seg:
                    paths.append('<circle cx="%.1f" cy="%.1f" r="3" fill="%s"><title>%s %d: %s/acre</title></circle>' % (
                        x, y, color, esc(label), yr, esc(usd(val))))
            last_pt = next((p for p in reversed(pts) if p[1] is not None), None)
            last_txt = " (%s)" % usd(last_pt[1]) if last_pt else ""
            legend.append('<span class="legend-item"><i style="background:%s"></i>%s%s</span>' % (color, esc(label), esc(last_txt)))

        svg = ('<svg viewBox="0 0 %d %d" class="trend-svg" role="img" aria-label="%s">'
               '%s%s%s</svg>') % (w, h, esc(title), "".join(grid), "".join(xlabels), "".join(paths))
        return ('<figure class="chart-card"><div class="chart-legend">%s</div>%s'
                '<figcaption class="small">USDA NASS annual values (%d–%d), nominal USD/acre, zero baseline. Gaps mark withheld or unavailable years.</figcaption></figure>' % (
                    "".join(legend), svg, self.first_year, self.latest_year))

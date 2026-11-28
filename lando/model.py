"""Load the stored listings and work out what the site shows: current inventory, states, counties, new and closing."""
import datetime
from functools import cached_property, lru_cache
import json
import os
import re
import unicodedata
from zoneinfo import ZoneInfo

from . import adapters, config, store

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
PAGE_SIZE = 250


@lru_cache(maxsize=4096)
def slugify(text):
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()
    t = t.replace("'", "").replace(".", "")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "unknown"


def parse_time(text):
    if not text:
        return None
    try:
        return datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


@lru_cache(maxsize=8192)
def county_key(state, county):
    c = (county or "").lower().replace("saint ", "st. ").replace("st ", "st. ")
    c = re.sub(r"\s+(county|parish|borough|census area|municipality|city and borough)$", "", c).strip()
    return "%s|%s" % (state, c)


class Catalog(object):
    def __init__(self, data_dir=None, now=None):
        self.data_dir = data_dir or config.DATA
        self.now = now or datetime.datetime.now(datetime.timezone.utc)
        self.status = store.load_status(self.data_dir)
        self.sources = {s["id"]: s for s in adapters.SOURCES}
        self.listings = []
        for src in adapters.SOURCES:
            sale_zone = ZoneInfo(src["timezone"]) if src.get("timezone") else None
            st = self.status.get("sources", {}).get(src["id"], {})
            last = parse_time(st.get("last_success"))
            fresh = bool(last and (self.now - last).days < config.CURRENT_DAYS)
            checked = last.strftime("%Y-%m-%d") if last else ""
            for r in store.load_listings(src["id"], self.data_dir):
                if r.get("missing"):
                    continue          # not seen by the latest complete read: waiting for a second confirmation
                r["checked"] = checked
                r["fresh"] = fresh
                if src.get("historical_only"):
                    r["status"] = "availability_unverified"
                    r["price"], r["price_kind"], r["deadline"] = None, "none", None
                    r["facts"] = [f for f in r["facts"] if f["topic"] not in (
                        "availability", "price", "minimum_bid", "sale_program", "auction_item",
                        "deadline", "bid_deadline", "auction_start",
                    )]
                label, available = adapters.STATUS.get(r["status"], (r["status"], False))
                if r["status"] in ("auction_open", "auction_terms", "proposal_open") and r.get("deadline"):
                    dl = parse_time(r["deadline"])
                    if dl and dl < self.now:      # the deadline passed since the last read
                        r["status"], (label, available) = "auction_closed", adapters.STATUS["auction_closed"]
                if available and sale_zone and r.get("offer_close_date"):
                    if self.now.astimezone(sale_zone).date().isoformat() > r["offer_close_date"]:
                        r["status"], (label, available) = "auction_closed", adapters.STATUS["auction_closed"]
                r["status_label"], r["available"] = label, available and fresh
                self.listings.append(r)
        seen = {}
        for r in self.listings:
            seen[r["title"]] = seen.get(r["title"], 0) + 1
        for r in self.listings:   # two lots at one street address: name each by its parcel number too
            if seen[r["title"]] > 1:
                r["title"] = "%s, parcel %s" % (r["title"], r.get("apn") or r["id"])
        self.by_id = {}
        for r in self.listings:
            r["slug"] = r["id"]
            r["state_name"] = STATE_NAMES.get(r["state"], r["state"])
            r["county_label"] = self.county_label(r)
            self.by_id[r["id"]] = r
        self.states = {}
        for r in self.listings:
            st = self.states.setdefault(r["state"], {"code": r["state"], "name": r["state_name"], "slug": slugify(r["state_name"]),
                                                     "counties": {}, "listings": []})
            st["listings"].append(r)
            key = slugify(r["county_label"])
            c = st["counties"].setdefault(key, {"name": r["county_label"], "slug": key, "listings": []})
            c["listings"].append(r)
        for st in self.states.values():
            for c in st["counties"].values():
                c["listings"].sort(key=sort_key)
                c["groups"] = self.group(c)
        self.land_index = self.load_land_index()

    def county_label(self, r):
        if r["county"]:
            c = r["county"]
            if r["state"] == "MO" and c.lower() == "st. louis city":
                return "St. Louis City"
            if r["state"] == "LA" and not c.lower().endswith("parish"):
                return c + " Parish"
            return c if re.search(r"(County|City|Borough|Parish|Planning Region)$", c) else c + " County"
        if r["state"]:
            return "%s (statewide programs)" % STATE_NAMES.get(r["state"], r["state"])
        return "County not stated"

    def group(self, county):
        """Split a very large county (St. Louis City) into neighbourhood pages; otherwise numbered pages."""
        ls = county["listings"]
        if len(ls) <= PAGE_SIZE:
            return []
        groups = {}
        for r in ls:
            hood = next((f["value"] for f in r["facts"] if f["topic"] == "neighborhood"), "")
            groups.setdefault(hood or "Other", []).append(r)
        if len(groups) > 1 and max(len(v) for v in groups.values()) <= PAGE_SIZE * 2:
            return [{"name": k, "slug": slugify(k), "listings": v} for k, v in sorted(groups.items())]
        return [{"name": "Page %d" % (i // PAGE_SIZE + 1), "slug": "page-%d" % (i // PAGE_SIZE + 1), "listings": ls[i:i + PAGE_SIZE]}
                for i in range(0, len(ls), PAGE_SIZE)]

    def load_land_index(self):
        path = os.path.join(self.data_dir, "usda", "land-index-counties.json")
        out = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for row in json.load(fh):
                    fips, name, state, state_name, page, value, year, kind = row[:8]
                    out[county_key(state, name)] = {"fips": fips, "name": name, "path": page, "value": value, "year": year, "kind": kind}
        return out

    def county_value(self, r):
        return self.land_index.get(county_key(r["state"], r["county_label"]))

    # ------------------------------------------------------------------ selections
    def current(self):
        return [r for r in self.listings if r["available"]]

    @cached_property
    def active_by_source(self):
        counts = {}
        for r in self.current():
            source = r["source"]
            counts[source] = counts.get(source, 0) + 1
        return counts

    def new(self):
        cutoff = (self.now - datetime.timedelta(days=config.NEW_DAYS)).strftime("%Y-%m-%d")
        return sorted([r for r in self.listings if r["available"] and r.get("first_seen") and r["first_seen"] >= cutoff],
                      key=lambda r: (r["first_seen"], r["id"]), reverse=True)

    def closing(self):
        return list(self._closing)

    @cached_property
    def _closing(self):
        out = []
        horizon = self.now + datetime.timedelta(days=config.CLOSING_DAYS)
        for r in self.listings:
            dl = parse_time(r.get("deadline"))
            if r["available"] and dl and self.now <= dl <= horizon:
                out.append((dl, r))
        return [r for _, r in sorted(out, key=lambda x: (x[0], x[1]["id"]))]

    def state_path(self, st):
        return "/land-for-sale/%s/" % st["slug"]

    def county_path(self, st, c):
        return "/land-for-sale/%s/%s/" % (st["slug"], c["slug"])

    def listing_path(self, r):
        return "/land/%s/" % r["slug"]


def sort_key(r):
    return (0 if r["available"] else 1, r.get("deadline") or "9999", r["title"])

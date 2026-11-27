"""Daily crawl of every official source. Safe to re-run at any time.

    python3 -m lando.refresh [--only st-louis-lra,arkansas-cosl] [--land-index]

Each source runs on its own: on failure it is retried inside the run, then left on its last good data, and the
failure is recorded in data/sources.json (the run still passes, with a warning). Prints `changed=true|false`
(also to $GITHUB_OUTPUT).
"""
import argparse
import datetime
import json
import os
import sys
import time

from . import adapters, config, store
from .net import Fetcher


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def run(data_dir=None, only=None, now=None, log=print, sources=None, fetcher=None):
    now = now or utcnow()
    today = now.strftime("%Y-%m-%d")
    status = store.load_status(data_dir)
    status.setdefault("sources", {})
    changed, warnings = [], []
    fetch = fetcher or Fetcher(log=log)
    for src in sources or adapters.SOURCES:
        if src.get("historical_only") or (only and src["id"] not in only):
            continue
        entry = status["sources"].setdefault(src["id"], {})
        entry.update({"name": src["name"], "agency": src["agency"], "url": src["url"], "state": src["state"],
                      "about": src["about"], "last_attempt": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
        notes = []
        t0 = time.time()
        rows = info = None
        error = None
        for attempt in range(2):
            try:
                rows, info = src["run"](fetch, now, notes.append)
                break
            except Exception as exc:  # network, structure or parser surprise: keep the last good data
                error = "%s: %s" % (type(exc).__name__, str(exc)[:300])
                log("%s attempt %d failed: %s" % (src["id"], attempt + 1, error))
        if rows is None:
            entry["ok"] = False
            entry["failures"] = int(entry.get("failures") or 0) + 1
            entry["message"] = error
            warnings.append("%s kept its last good data (%s)" % (src["name"], error))
            continue
        old = store.load_listings(src["id"], data_dir)
        if src.get("requires_sale_match") and info.get("complete"):
            for prior in old:
                prior["status"] = "availability_unverified"
        merged, merge_notes = store.merge(old, rows, today, bool(info.get("complete")))
        notes += merge_notes
        if store.save_listings(src["id"], merged, data_dir):
            changed.append(src["id"])
        entry.update({"ok": True, "failures": 0, "message": "", "last_success": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "count": sum(1 for r in merged if not r.get("missing")), "read": len(rows),
                      "complete": bool(info.get("complete")), "upstream_total": info.get("upstream_total"),
                      "notes": notes[:10], "seconds": round(time.time() - t0)})
        log("%s: %d listings read, %d stored%s" % (src["id"], len(rows), len(merged), ("; " + "; ".join(notes)) if notes else ""))
    status["checked"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    store.save_status(status, data_dir)
    return changed, warnings


def refresh_land_index(data_dir=None, log=print):
    """Cache the sister site's county land values (USDA/FHFA) used for price context. Keeps the old copy on failure."""
    path = os.path.join(data_dir or config.DATA, "usda", "land-index-counties.json")
    try:
        rows = Fetcher(log=log).json(config.LAND_INDEX_URL + "/api/counties.json")
        if not isinstance(rows, list) or len(rows) < 1000:
            raise ValueError("unexpected county list")
    except Exception as exc:
        log("land index county values kept on the cached copy (%s)" % exc)
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(rows, separators=(",", ":"), ensure_ascii=False)
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
    if old != text:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return True
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", default="", help="comma-separated source ids")
    ap.add_argument("--land-index", action="store_true", help="also refresh the cached county land values")
    args = ap.parse_args(argv)
    only = set(s for s in args.only.split(",") if s) or None
    changed, warnings = run(only=only)
    if args.land_index and refresh_land_index():
        changed.append("land-index")
    for w in warnings:
        print("::warning title=Source kept on last good data::%s" % w)
    lines = ["changed=%s" % ("true" if changed else "false"), "warnings=%d" % len(warnings)]
    print("\n".join(lines))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write("\n".join(lines) + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write("## Crawl\n\n- changed: %s\n" % (", ".join(changed) or "none"))
            for w in warnings:
                fh.write("- warning: %s\n" % w)
    return 0


if __name__ == "__main__":
    sys.exit(main())

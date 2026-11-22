"""Listings on disk: one JSON Lines file per source (sorted, one listing per line, so git stores small diffs),
parcel outlines in a separate file per source (they rarely change), and data/sources.json for source status.

Withdrawal rule (from the original application): a listing leaves the current inventory only after two complete,
non-empty, successful reads of its source in a row have not seen it. A failed, partial or suspiciously small read
never withdraws anything. Disappearance is never read as a sale.
"""
import json
import os

from . import config

GEOMETRY_KEYS = ("geometry",)


def _path(data_dir, *parts):
    return os.path.join(data_dir or config.DATA, *parts)


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path, rows, key="id"):
    """Write rows sorted by key; returns True when the file changed."""
    text = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
                   for r in sorted(rows, key=lambda r: r[key]))
    old = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            old = fh.read()
    if old == text:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return True


def load_listings(source_id, data_dir=None):
    rows = read_jsonl(_path(data_dir, "listings", source_id + ".jsonl"))
    geo = {g["id"]: g["geometry"] for g in read_jsonl(_path(data_dir, "geometry", source_id + ".jsonl"))}
    for r in rows:
        r["geometry"] = geo.get(r["id"])
    return rows


def save_listings(source_id, rows, data_dir=None):
    plain, geo = [], []
    for r in rows:
        r2 = {k: v for k, v in r.items() if k not in GEOMETRY_KEYS}
        plain.append(r2)
        if r.get("geometry"):
            geo.append({"id": r["id"], "geometry": r["geometry"]})
    a = write_jsonl(_path(data_dir, "listings", source_id + ".jsonl"), plain)
    b = write_jsonl(_path(data_dir, "geometry", source_id + ".jsonl"), geo)
    return a or b


def load_status(data_dir=None):
    path = _path(data_dir, "sources.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {"sources": {}}


def save_status(status, data_dir=None):
    path = _path(data_dir, "sources.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(status, fh, indent=1, sort_keys=True)
        fh.write("\n")


def _days(a, b):
    import datetime
    try:
        return (datetime.date.fromisoformat(b[:10]) - datetime.date.fromisoformat(a[:10])).days
    except ValueError:
        return 999


def merge(old, new, today, complete):
    """Merge a successful read into the stored inventory. Returns (rows, notes)."""
    notes = []
    old_by = {r["id"]: r for r in old}
    out = []
    for r in new:
        prev = old_by.get(r["id"])
        if prev:
            r["first_seen"] = prev.get("first_seen", "")
        else:
            # A listing appearing in an inventory read before is new today. On a source's first read nothing is
            # "new": the date stays unknown unless the source states when the parcel was added.
            r["first_seen"] = r.get("listed_date") or (today if old else "")
        r["missing"] = 0
        if r.pop("rotating_url", False):
            # Some sources (Arkansas COSL) issue a new link token on every read while old tokens keep working.
            # Keep a listing's link for up to a week so the stored data does not churn daily.
            if prev and prev.get("url_date") and _days(prev["url_date"], today) < 7:
                r["url"], r["url_date"] = prev["url"], prev["url_date"]
            else:
                r["url_date"] = today
        if not r.get("geometry") and prev and prev.get("geometry"):
            r["geometry"] = prev["geometry"]      # an outline lookup failed this time: keep the last good one
            if prev.get("lat") is not None and r.get("lat") is None:
                r["lat"], r["lon"] = prev["lat"], prev["lon"]
        out.append(r)
    seen = {r["id"] for r in new}
    gone = [r for r in old if r["id"] not in seen]
    trusted = complete and new and len(new) >= 0.5 * len(old)
    if gone and not trusted:
        notes.append("kept %d listings this read did not include (read was partial or much smaller than before)" % len(gone))
    withdrawn = 0
    for r in gone:
        if trusted:
            r["missing"] = int(r.get("missing") or 0) + 1
            if r["missing"] >= 2:
                withdrawn += 1
                continue
        out.append(r)
    if withdrawn:
        notes.append("%d listings left the inventory after two complete reads without them" % withdrawn)
    return out, notes

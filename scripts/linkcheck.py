"""Weekly link check: the site's own pages, every source's catalogue page, and a sample of listings' official links.

    python3 scripts/linkcheck.py [base_url | dist]

Internal failures fail the run. Official links are fetched politely (one at a time, robots respected, a pause
between requests); a failure there is a warning, because agencies move pages and the daily crawl is the real test.
"""
import json
import os
import random
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lando import adapters, config  # noqa: E402
from lando.net import FetchError, Fetcher  # noqa: E402


def main(base):
    base = base.rstrip("/")
    lines, failed = ["## Link check: %s" % base, ""], False
    req = urllib.request.Request(base + "/data/map.json", headers={"User-Agent": config.USER_AGENT})
    rows = json.loads(urllib.request.urlopen(req, timeout=60).read())["rows"]
    sample = random.Random(int(time.time() // 86400)).sample(rows, min(40, len(rows)))
    bad = []
    for r in sample:
        try:
            with urllib.request.urlopen(urllib.request.Request(base + "/land/%s/" % r[0], method="HEAD",
                                                               headers={"User-Agent": config.USER_AGENT}), timeout=40) as resp:
                if resp.status != 200:
                    bad.append(r[0])
        except Exception:
            bad.append(r[0])
    failed |= bool(bad)
    lines.append("- %s %d sampled listing pages%s" % ("FAIL" if bad else "ok  ", len(sample), (": " + ", ".join(bad)) if bad else ""))
    fetch = Fetcher(pause=2.0, tries=2, max_bytes=30000000, log=lambda *a: None)
    warn = []
    for src in adapters.SOURCES:
        try:
            fetch.text(src["url"])
        except FetchError as exc:
            warn.append("%s: %s" % (src["name"], exc))
    lines.append("- %s %d source catalogue pages%s" % ("warn" if warn else "ok  ", len(adapters.SOURCES), (": " + "; ".join(warn)) if warn else ""))
    for w in warn:
        print("::warning title=Source page::%s" % w)
    text = "\n".join(lines)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(text + "\n")
    return 1 if failed else 0


def local_links(dist):
    """Verify all internal URLs in the release's buyer hubs and state guides."""
    from check_dist import HREF, archive_files, archive_listing_paths, resolve
    from pathlib import Path
    root = Path(dist)
    archived = archive_listing_paths(archive_files(dist))
    inputs = [root / path / "index.html" for path in ("land-under-5000", "land-under-10000", "acreage-for-sale")]
    inputs.extend(sorted((root / "research").glob("buying-land-in-*/index.html")))
    bad, checked = [], set()
    for page in inputs:
        if not page.is_file():
            bad.append("Missing page %s" % page.relative_to(root))
            continue
        for raw in HREF.findall(page.read_text(encoding="utf-8")):
            target = resolve(config.base_path(), raw)
            if target and target not in checked:
                checked.add(target)
                if target not in archived and not (root / target).is_file():
                    bad.append("%s → %s" % (page.relative_to(root), raw))
    for error in bad:
        print(error)
    print("Checked %d local buyer pages and %d distinct internal links: %d problems" % (len(inputs), len(checked), len(bad)))
    return bool(bad)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else config.BASE_URL
    sys.exit(local_links(target) if os.path.isdir(target) else main(target))

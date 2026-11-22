"""Weekly self-test of the live site and the staleness check that keeps the daily crawl from silently stopping.

    python3 scripts/health.py [base_url]

Fails (exit 1) when key pages or files do not answer, when sampled listing pages do not answer or lack their
official link, when a source has failed 3 reads in a row or has not been read successfully for 7 days, or when the
live indexing state is inconsistent (SITE_INDEXABLE: duplicates always noindex). When the newest crawl is more than 2 days old it
dispatches the crawl (GitHub sometimes skips scheduled runs). Writes a report to $GITHUB_STEP_SUMMARY.
"""
import datetime
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lando import config  # noqa: E402

KEY = ["/", "/new/", "/closing-soon/", "/sources/", "/about/", "/data/", "/sitemap.xml", "/robots.txt", "/data/map.json",
       "/data/listings.csv", "/data/sources.json", "/feeds/new.xml", "/assets/map.js", "/assets/vendor/leaflet.js", "/og/default.png"]


def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url + ("&" if "?" in url else "?") + "selftest=%d" % int(time.time()), headers={"User-Agent": config.USER_AGENT})
            with urllib.request.urlopen(req, timeout=40) as resp:
                return resp.status, resp.read()
        except Exception as exc:
            last = exc
            time.sleep(3 * (i + 1))
    return str(last), b""


def main(base):
    base = base.rstrip("/")
    lines, failed = ["## Live site: %s" % base, ""], []
    now = datetime.datetime.now(datetime.timezone.utc)

    def report(ok, text, fatal=True):
        lines.append("- %s %s" % ("ok  " if ok else ("FAIL" if fatal else "warn"), text))
        if not ok and fatal:
            failed.append(text)
        if not ok and not fatal:
            print("::warning title=Self-test::%s" % text)

    with open(os.path.join(ROOT, "site", "indexnow-key.txt")) as fh:
        key = fh.read().strip()
    for p in KEY + ["/%s.txt" % key]:
        st, body = get(base + p)
        report(st == 200 and len(body) > 20, "%s answers %s" % (p, st))

    st, body = get(base + "/data/sources.json")
    status = json.loads(body) if st == 200 else {}
    newest = None
    for sid, s in sorted(status.get("sources", {}).items()):
        last = s.get("last_success")
        age = (now - datetime.datetime.strptime(last[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)).days if last else None
        if last and (newest is None or last > newest):
            newest = last
        report(int(s.get("failures") or 0) < 3, "%s: %s failed reads in a row%s" % (s.get("name", sid), s.get("failures", 0),
                                                                                    (" (" + s.get("message", "") + ")") if s.get("message") else ""))
        report(age is not None and age < config.CURRENT_DAYS, "%s last read successfully %s days ago" % (s.get("name", sid), age))
    site = status.get("site", {})
    live_indexable = bool(site.get("indexable"))
    lines.append("- info SITE_INDEXABLE on the live build: %s" % ("true" if live_indexable else "unset (whole copy noindex)"))
    st, page = get(base + "/land-for-sale/missouri/")
    report(st == 200 and b'content="noindex' in page, "pages that duplicate the original carry noindex")
    st, page = get(base + "/new/")
    want = b'content="index' if live_indexable else b'content="noindex'
    report(st == 200 and want in page, "/new/ indexing matches SITE_INDEXABLE")
    st, robots = get(base + "/robots.txt")
    report((b"Sitemap:" in robots) == live_indexable, "robots.txt matches SITE_INDEXABLE")

    st, body = get(base + "/data/map.json")
    try:
        rows = [r for r in json.loads(body)["rows"] if r[8]]
        sample = random.Random(now.toordinal()).sample(rows, min(20, len(rows)))
        bad = []
        for r in sample:
            s2, html_ = get(base + "/land/%s/" % r[0], tries=2)
            if s2 != 200 or not re.search(rb'<a class="button" href="https://', html_):
                bad.append("%s (%s)" % (r[0], s2))
        report(not bad, "%d sampled listing pages answer with an official link%s" % (len(sample), (": " + ", ".join(bad)) if bad else ""))
    except Exception as exc:
        report(False, "listing sample: %s" % exc)

    if newest and os.environ.get("GH_TOKEN") and os.environ.get("GITHUB_REPOSITORY"):
        age_h = (now - datetime.datetime.strptime(newest[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)).total_seconds() / 3600
        if age_h > 48:
            report(False, "newest crawl is %.0f hours old: dispatching the crawl" % age_h, fatal=False)
            subprocess.run(["gh", "workflow", "run", "crawl.yml", "-R", os.environ["GITHUB_REPOSITORY"]], check=False)
        else:
            report(True, "newest crawl %.0f hours old" % age_h)
    text = "\n".join(lines)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(text + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else config.BASE_URL))

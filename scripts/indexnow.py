"""Tell IndexNow (Bing, Yandex, Seznam, Naver...) about pages that changed in this deploy.

    python3 scripts/indexnow.py diff dist [base_url] > changed.txt   # before deploying: compare with the live site
    python3 scripts/indexnow.py submit changed.txt [base_url]         # after deploying

`diff` compares dist/manifest.json (a hash per page) with the live site's manifest.json and prints the URLs of new
or changed pages; when the live manifest is missing (first deploy) every page counts as changed.
`submit` never fails the caller: a search ping must not fail a deploy. It is skipped when LANDO_INDEXNOW=off.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lando import config  # noqa: E402

LIMIT = 10000


def live_manifest(base):
    req = urllib.request.Request(base + "/manifest.json?nocache=1", headers={"User-Agent": config.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8")).get("pages", {})
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        raise


def diff(dist, base):
    """Only indexable pages are submitted: pages that duplicate the live original carry noindex."""
    with open(os.path.join(dist, "manifest.json")) as fh:
        manifest = json.load(fh)
    new = {p: h for p, h in manifest["pages"].items() if p in set(manifest.get("indexable", []))}
    try:
        old = live_manifest(base)
    except Exception as exc:  # cannot tell what changed: submit only the main pages
        sys.stderr.write("live manifest unavailable (%s); listing the main pages only\n" % exc)
        old = None
    if old is None:
        paths = list(new)
    else:
        paths = [p for p, h in new.items() if old.get(p) != h]
    paths.sort(key=lambda p: (p.count("/"), p))
    for p in paths:
        print(base + p)
    sys.stderr.write("%d of %d pages new or changed\n" % (len(paths), len(new)))
    return 0


def submit(listing, base):
    if os.environ.get("LANDO_INDEXNOW", "").lower() == "off":
        print("IndexNow: off (LANDO_INDEXNOW=off)")
        return 0
    urls = [u.strip() for u in open(listing) if u.strip().startswith(base + "/")][:LIMIT]
    if not urls:
        print("IndexNow: nothing changed")
        return 0
    with open(os.path.join(ROOT, "site", "indexnow-key.txt")) as fh:
        key = fh.read().strip()
    body = {"host": urllib.parse.urlparse(base).netloc, "key": key, "keyLocation": "%s/%s.txt" % (base, key),
            "urlList": urls}
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": config.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            print("IndexNow: HTTP %s for %d URLs" % (resp.status, len(urls)))
    except urllib.error.HTTPError as exc:
        print("IndexNow: HTTP %s (%s)" % (exc.code, exc.read()[:200]))
    except Exception as exc:
        print("IndexNow: failed (%s)" % exc)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("diff", "submit"):
        print(__doc__)
        sys.exit(2)
    target = (sys.argv[3] if len(sys.argv) > 3 else config.BASE_URL).rstrip("/")
    sys.exit(diff(sys.argv[2], target) if sys.argv[1] == "diff" else submit(sys.argv[2], target))

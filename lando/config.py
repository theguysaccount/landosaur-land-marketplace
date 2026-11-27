"""Settings. Everything a deploy might change comes from the environment, so the base URL is one setting."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SITE_SRC = os.path.join(ROOT, "site")

SITE_NAME = "Landosaur"
TAGLINE = "Official government, auction & rural land for sale on one map, with 50-state land prices, GIS parcel dossiers, and valuation tools"

REPO = os.environ.get("LANDO_REPO", "theguysaccount/landosaur-land-marketplace")
REPO_URL = "https://github.com/" + REPO

# Public canonical address. Defaults to https://landosaur.com for Vercel production.
BASE_URL = (os.environ.get("SITE_URL") or os.environ.get("LANDO_BASE_URL")
            or "https://landosaur.com").rstrip("/")

# Primary Landosaur site configuration (replaces retired landosaur.fly.dev).
# Set SITE_INDEXABLE=false explicitly to suppress search indexing.
ORIGINAL_URL = (os.environ.get("LANDO_ORIGINAL_URL") or "https://landosaur.com").rstrip("/")
_RAW_INDEXABLE = os.environ.get("SITE_INDEXABLE")
if _RAW_INDEXABLE is None or _RAW_INDEXABLE.strip() == "":
    INDEXABLE = "github.io" not in BASE_URL
else:
    INDEXABLE = _RAW_INDEXABLE.strip().lower() in ("1", "true", "yes")

# Sister site with county land values per acre (USDA and FHFA). Read at build time; a cached copy is committed.
LAND_INDEX_URL = (os.environ.get("LANDO_LAND_INDEX_URL") or "https://index.grounded.to").rstrip("/")

# Optional keys (see OPERATIONS.md). Empty means the feature stays off.
SUPPORT_URL = os.environ.get("LANDO_SUPPORT_URL", "").strip()
REPORT_URL = os.environ.get("LANDO_REPORT_URL", "").strip()   # a paid parcel report hosted off GitHub Pages
GOATCOUNTER = os.environ.get("LANDO_GOATCOUNTER", "").strip()

# Identifies this project to the agencies it reads. The repository is the contact address.
USER_AGENT = "landosaur-land-marketplace/1.0 (+%s)" % REPO_URL
ROBOTS_AGENT = "landosaur-land-marketplace"

CURRENT_DAYS = 7      # a listing is current when its source was read successfully within this many days
NEW_DAYS = 14         # "new" = first seen within this many days
CLOSING_DAYS = 30     # "closing soon" = a deadline within this many days


def base_path():
    rest = BASE_URL.split("://", 1)[-1]
    return ("/" + rest.split("/", 1)[1]).rstrip("/") if "/" in rest else ""

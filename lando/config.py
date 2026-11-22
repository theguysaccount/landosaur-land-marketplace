"""Settings. Everything a deploy might change comes from the environment, so the base URL is one setting."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SITE_SRC = os.path.join(ROOT, "site")

SITE_NAME = "Landosaur"
TAGLINE = "Government and auction land for sale, on one map, with every listing linked to its official source"

REPO = os.environ.get("LANDO_REPO", "theguysaccount/landosaur-land-marketplace")
REPO_URL = "https://github.com/" + REPO
# The public address: one setting. Fleet convention (see ~/code/DOMAIN_ROLLOUT.md): repository variable SITE_URL.
BASE_URL = (os.environ.get("SITE_URL") or os.environ.get("LANDO_BASE_URL")
            or "https://theguysaccount.github.io/landosaur-land-marketplace").rstrip("/")

# The original Landosaur application stays live and is never replaced. Fleet convention for staged copies:
# SITE_INDEXABLE unset -> the whole copy is noindex (robots.txt Disallow, no sitemap, no IndexNow);
# SITE_INDEXABLE=true -> only pages the original does not serve are indexed (/new/, /closing-soon/). Pages that
# duplicate the original (map, listings, state and county pages, sources, about, data) stay noindex either way.
ORIGINAL_URL = (os.environ.get("LANDO_ORIGINAL_URL") or "https://landosaur.fly.dev").rstrip("/")
INDEXABLE = (os.environ.get("SITE_INDEXABLE") or "").strip().lower() in ("1", "true", "yes")

# Sister site with county land values per acre (USDA and FHFA). Read at build time; a cached copy is committed.
LAND_INDEX_URL = (os.environ.get("LANDO_LAND_INDEX_URL") or "https://theguysaccount.github.io/land-index-fund").rstrip("/")

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

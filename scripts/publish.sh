#!/usr/bin/env bash
# Landosaur self-hosted $0-GitHub-Actions refresh, build, verify, and Vercel production deploy script.
#
# Usage:
#   ./scripts/publish.sh                       # Test, build, guard, E2E, push, deploy to landosaur.com
#   ./scripts/publish.sh --refresh             # Live-crawl all 28 official agencies first, then verify & deploy
#   ./scripts/publish.sh --refresh-only a,b    # Crawl only specific agency IDs, then verify & deploy
#   ./scripts/publish.sh --skip-e2e            # Skip headless Chrome E2E (still runs unit tests + check_dist)
#   ./scripts/publish.sh --no-deploy           # Build and verify locally without pushing or deploying
set -euo pipefail

export PATH="/Users/jack/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGING="/Users/jack/.gemini/antigravity/scratch/landosaur-vercel-staging"
BASE_URL="${SITE_URL:-https://landosaur.com}"
REFRESH=0
REFRESH_ONLY=""
SKIP_E2E=0
NO_DEPLOY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --refresh) REFRESH=1 ;;
    --refresh-only) REFRESH=1; shift; REFRESH_ONLY="${1:-}" ;;
    --skip-e2e) SKIP_E2E=1 ;;
    --no-deploy) NO_DEPLOY=1 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

cd "$ROOT"

echo "==> 1/7 Syntax & unit tests"
for f in api/xray.js api/listings.js api/offers.js site/theme.js site/map.js site/listing.js site/xray.js site/list.js site/direct.js site/tables.js site/analyze.js scripts/e2e.mjs; do
  node --check "$f"
done
python3 -m unittest discover -s tests -t .

if [ "$REFRESH" -eq 1 ]; then
  echo "==> 2/7 Refreshing official agency feeds locally (robots-compliant)"
  if [ -n "$REFRESH_ONLY" ]; then
    python3 -m lando.refresh --only "$REFRESH_ONLY"
  else
    python3 -m lando.refresh --land-index
  fi
else
  echo "==> 2/7 Skipping live crawl (pass --refresh to crawl all 28 agencies)"
fi

echo "==> 3/7 Building static site into dist/"
python3 -m lando.build dist

echo "==> 4/7 Running dist guard (scripts/check_dist.py)"
python3 scripts/check_dist.py dist

if [ "$SKIP_E2E" -eq 0 ]; then
  echo "==> 5/7 Running headless Chrome E2E against local dist/"
  CHROME_BIN="$(command -v google-chrome || echo "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")"
  python3 -m http.server 4651 --bind 127.0.0.1 --directory "$ROOT/dist" >/dev/null 2>&1 &
  SRV_PID=$!
  trap 'kill "$SRV_PID" 2>/dev/null || true' EXIT
  sleep 1
  CHROME="$CHROME_BIN" node scripts/e2e.mjs "http://127.0.0.1:4651"
  kill "$SRV_PID" 2>/dev/null || true
  trap - EXIT
else
  echo "==> 5/7 Skipping local E2E (--skip-e2e)"
fi

if [ "$NO_DEPLOY" -eq 1 ]; then
  echo "==> Done (--no-deploy)."
  exit 0
fi

echo "==> 6/7 Syncing to Vercel production staging mirror & deploying to $BASE_URL"
rsync -a --delete \
  --exclude '.git' --exclude '.vercel' --exclude '.env.local' \
  --exclude 'dist' --exclude 'original' --exclude '__pycache__' --exclude 'node_modules' \
  "$ROOT/" "$STAGING/"

(cd "$STAGING" && npx --no-install vercel --prod --yes --scope persist-always)

echo "==> 7/7 Post-deploy live check (IndexNow diff + live API smoke check)"
curl -fsS "$BASE_URL/api/xray/?lat=35.42&lon=-92.45" | head -c 260 && echo ""
python3 scripts/indexnow.py diff "$ROOT/dist" "$BASE_URL" > /tmp/lando-changed.txt || true
if [ -s /tmp/lando-changed.txt ]; then
  echo "Changed indexable URLs: $(wc -l < /tmp/lando-changed.txt)"
  python3 scripts/indexnow.py submit /tmp/lando-changed.txt "$BASE_URL" || true
fi
echo "==> Landosaur published cleanly to $BASE_URL at \$0 GitHub Actions cost."

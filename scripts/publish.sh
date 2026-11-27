#!/usr/bin/env bash
# Landosaur's local refresh, build, verification, and production release. GitHub Actions stay manual.
#
#   ./scripts/publish.sh                       # Verify, push, and deploy the current main commit
#   ./scripts/publish.sh --refresh             # Refresh 64+ official agencies across 50 states and verify
#   ./scripts/publish.sh --refresh-only a,b    # Refresh specific agency IDs and verify
#   ./scripts/publish.sh --no-deploy           # Build and verify locally
#   ./scripts/publish.sh --skip-e2e            # Local build only, without browser verification
set -euo pipefail

export PATH="/Users/jack/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGING="/Users/jack/.gemini/antigravity/scratch/landosaur-vercel-staging"
BASE_URL="${SITE_URL:-https://landosaur.com}"
BASE_URL="${BASE_URL%/}"
REFRESH=0
REFRESH_ONLY=""
SKIP_E2E=0
NO_DEPLOY=0
SRV_PID=""
CHANGED=""

cleanup() {
  if [ -n "$SRV_PID" ]; then
    kill "$SRV_PID" 2>/dev/null || true
    wait "$SRV_PID" 2>/dev/null || true
  fi
  if [ -n "$CHANGED" ]; then rm -f "$CHANGED"; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

while [ $# -gt 0 ]; do
  case "$1" in
    --refresh) REFRESH=1 ;;
    --refresh-only)
      if [ $# -lt 2 ] || [[ "$2" == -* ]]; then
        echo "--refresh-only needs a comma-separated list of agency IDs" >&2
        exit 2
      fi
      REFRESH=1
      shift
      REFRESH_ONLY="$1"
      ;;
    --skip-e2e) SKIP_E2E=1 ;;
    --no-deploy) NO_DEPLOY=1 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

cd "$ROOT"

echo "==> 1/7 Syntax, API imports, and unit tests"
while IFS= read -r -d '' file; do
  node --check "$file"
done < <(git ls-files -z --cached --others --exclude-standard -- '*.js' '*.mjs')
node --input-type=module <<'JS'
import { readdir } from "node:fs/promises";
for (const file of await readdir("api")) {
  if (!file.endsWith(".js")) continue;
  await import("./api/" + file);
  console.log("Imported api/" + file);
}
JS
python3 -m unittest discover -s tests -t .

if [ "$REFRESH" -eq 1 ]; then
  echo "==> 2/7 Refreshing official agency feeds locally"
  if [ -n "$REFRESH_ONLY" ]; then
    python3 -m lando.refresh --only "$REFRESH_ONLY"
  else
    python3 -m lando.refresh --land-index
  fi
else
  echo "==> 2/7 Using the committed inventory snapshot"
fi

echo "==> 3/7 Building static site into dist/"
python3 -m lando.build dist

echo "==> 4/7 Validating the production output"
python3 scripts/check_dist.py dist

if [ "$SKIP_E2E" -eq 0 ]; then
  echo "==> 5/7 Running headless Chrome E2E against local dist/"
  local_url="http://127.0.0.1:${LANDO_TEST_PORT:-4651}"
  node scripts/serve-dist.mjs "${LANDO_TEST_PORT:-4651}" &
  SRV_PID=$!
  ready=0
  for attempt in {1..30}; do
    if curl -fsS "$local_url/data/sources.json" -o /dev/null 2>/dev/null; then ready=1; break; fi
    kill -0 "$SRV_PID"
    sleep 0.1
  done
  if [ "$ready" -eq 0 ]; then echo "Local release server did not start" >&2; exit 1; fi
  node scripts/e2e.mjs "$local_url"
  cleanup
  SRV_PID=""
else
  echo "==> 5/7 Skipping local E2E (--skip-e2e)"
fi

if [ "$NO_DEPLOY" -eq 1 ]; then
  echo "==> Done (--no-deploy)."
  exit 0
fi
if [ "$SKIP_E2E" -eq 1 ]; then
  echo "Production deployment requires local E2E" >&2
  exit 2
fi
if [ "$(git branch --show-current)" != main ] || [ -n "$(git status --porcelain)" ]; then
  echo "Commit the verified release to main before publishing" >&2
  exit 1
fi

if [ -n "${VERCEL_BIN:-}" ]; then
  vercel_cli=("$VERCEL_BIN")
elif command -v vercel >/dev/null; then
  vercel_cli=(vercel)
else
  vercel_cli=(npx --yes vercel)
fi

CHANGED="$(mktemp "${TMPDIR:-/tmp}/lando-indexnow.XXXXXX")"
python3 scripts/indexnow.py diff "$ROOT/dist" "$BASE_URL" > "$CHANGED"

echo "==> 6/7 Pushing main and deploying the staging mirror to $BASE_URL"
git push origin main
rsync -a --delete \
  --exclude '.git' --exclude '.vercel' --exclude '.env' --exclude '.env.*' \
  --exclude 'dist' --exclude 'original' --exclude '__pycache__' --exclude 'node_modules' \
  "$ROOT/" "$STAGING/"
(cd "$STAGING" && "${vercel_cli[@]}" --prod --yes --scope persist-always)

echo "==> 7/7 Verifying production, then submitting changed pages to IndexNow"
node scripts/e2e.mjs "$BASE_URL"
node scripts/live-api.mjs "$BASE_URL"

python3 scripts/indexnow.py submit "$CHANGED" "$BASE_URL"
if [ -n "${LANDO_SCREEN_DIR:-}" ]; then
  node scripts/screens.mjs "$BASE_URL" "$LANDO_SCREEN_DIR"
fi
echo "==> Landosaur published to $BASE_URL at \$0 GitHub Actions cost."

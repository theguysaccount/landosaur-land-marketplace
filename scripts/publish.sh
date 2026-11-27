#!/usr/bin/env bash
# Landosaur's local refresh, build, verification, and production release. GitHub Actions stay manual.
#
#   ./scripts/publish.sh                       # Verify, push, and deploy the current main commit
#   ./scripts/publish.sh --refresh             # Refresh 64+ official agencies across 50 states and verify
#   ./scripts/publish.sh --refresh-only a,b    # Refresh specific agency IDs and verify
#   ./scripts/publish.sh --refresh-only a,b --crawl-only  # Refresh data for review
#   ./scripts/publish.sh --refresh-intelligence --crawl-only  # Refresh EIA-861 and CPI-U
#   ./scripts/publish.sh --no-deploy           # Build and verify locally
#   ./scripts/publish.sh --no-deploy --regen-og # Re-render the committed share cards
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
CRAWL_ONLY=0
REFRESH_INTELLIGENCE=0
REGEN_OG=0
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
    --refresh-intelligence) REFRESH_INTELLIGENCE=1 ;;
    --crawl-only) CRAWL_ONLY=1 ;;
    --skip-e2e) SKIP_E2E=1 ;;
    --no-deploy) NO_DEPLOY=1 ;;
    --regen-og) REGEN_OG=1 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

cd "$ROOT"
if [ "$REGEN_OG" -eq 1 ] && [ "$NO_DEPLOY" -ne 1 ]; then
  echo "Use --regen-og with --no-deploy and commit the updated share cards before releasing" >&2
  exit 2
fi

refresh_data() {
  local -a python_run=(python3)
  if ! python3 -c 'import pypdf, openpyxl' 2>/dev/null && command -v uv >/dev/null; then
    export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT/work/uv-cache}"
    python_run=(uv run --with-requirements "$ROOT/requirements-refresh.txt" python)
  fi
  if [ "$REFRESH" -eq 1 ]; then
    if [ -n "$REFRESH_ONLY" ]; then
      "${python_run[@]}" -m lando.refresh --only "$REFRESH_ONLY"
    else
      "${python_run[@]}" -m lando.refresh --land-index
    fi
  fi
  if [ "$REFRESH_INTELLIGENCE" -eq 1 ]; then
    "${python_run[@]}" -m lando.intelligence_data
  fi
}
if [ "$CRAWL_ONLY" -eq 1 ]; then
  if [ "$REFRESH" -ne 1 ] && [ "$REFRESH_INTELLIGENCE" -ne 1 ]; then
    echo "--crawl-only requires an inventory or intelligence refresh flag" >&2
    exit 2
  fi
  refresh_data
  exit
fi

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
node --test tests/*.test.mjs

if [ "$REFRESH" -eq 1 ] || [ "$REFRESH_INTELLIGENCE" -eq 1 ]; then
  echo "==> 2/7 Refreshing requested official data locally"
  refresh_data
else
  echo "==> 2/7 Using the committed inventory snapshot"
fi

echo "==> 3/7 Building static site into dist/"
python3 -m lando.build dist
if [ "$REGEN_OG" -eq 1 ]; then
  python3 scripts/og.py dist site/og
fi

echo "==> 4/7 Validating the production output"
python3 scripts/check_dist.py dist
python3 scripts/linkcheck.py dist

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
  --exclude 'dist' --exclude 'original' --exclude 'work' --exclude '.venv' --exclude '__pycache__' --exclude 'node_modules' \
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

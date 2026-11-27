"""Render the built 1200×630 share cards with headless Chrome.

    python3 scripts/og.py [dist] [output]

Use site/og as the output to update the committed cards used by Vercel.
"""
from pathlib import Path
import subprocess
import sys


def main(dist, output):
    source = Path(dist).resolve() / "_og"
    script = Path(__file__).with_name("og.mjs").resolve()
    return subprocess.run(["node", str(script), str(source), str(Path(output).resolve())]).returncode


if __name__ == "__main__":
    build = sys.argv[1] if len(sys.argv) > 1 else "dist"
    out = sys.argv[2] if len(sys.argv) > 2 else str(Path(build) / "og")
    sys.exit(main(build, out))

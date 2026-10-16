#!/usr/bin/env python3
"""Re-record the Music Assistant responses the contract tests replay.

Runs every scenario in test/ma_scenarios.py through the resolver against a
live server and writes one pruned recording per scenario to
test/fixtures/ma/. Reads MA_URL and MA_TOKEN from the environment and never
prints either.

    MA_URL=http://server:8095 MA_TOKEN=... uv run python scripts/record_ma_fixtures.py [scenario ...]
"""

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from skill_musicassistant.resolve import resolve  # noqa: E402
from test.ma_recording import RecordingClient  # noqa: E402
from test.ma_scenarios import SCENARIOS  # noqa: E402


def main(names) -> int:
    url, token = os.environ.get("MA_URL"), os.environ.get("MA_TOKEN")
    if not url or not token:
        print("MA_URL and MA_TOKEN must be set", file=sys.stderr)
        return 2
    client = RecordingClient(url, token)
    for name in names or SCENARIOS:
        resolution = resolve(client, SCENARIOS[name])
        path = client.save(name)
        item = resolution.item
        found = f"{item.media_type} {item.name!r} by {item.artist!r}" if item else f"{len(resolution.uris)} uris"
        extra = f" alternatives={resolution.alternatives}" if resolution.alternatives else ""
        extra += " different-artist" if resolution.different_artist else ""
        print(f"{name:28} {resolution.kind.value:15} {found}{extra}  -> {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

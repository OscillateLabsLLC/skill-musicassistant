"""Record Music Assistant responses once, replay them in contract tests.

A recording is one JSON file per scenario under ``test/fixtures/ma``. Each
entry holds the command, its arguments, and the pruned response (or the error
the server raised). ``ReplayClient`` fails loudly on a call that was not
recorded, so a new code path forces a new recording instead of silently
passing against a guess.
"""

import datetime
import json
from pathlib import Path
from typing import Any, Dict, List

from ma_http_client import SimpleHTTPMusicAssistantClient
from music_assistant_models.errors import MusicAssistantError


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ma"
# Response keys the catalog never reads; dropping them keeps a search under a few kilobytes
PRUNED_KEYS = frozenset(
    {
        "metadata",
        "provider_mappings",
        "external_ids",
        "date_added",
        "sort_name",
        "position",
        "favorite",
        "is_playable",
        "is_dynamic",
        "version",
        "album_type",
        "year",
        "duration",
        "timestamp_added",
        "timestamp_modified",
    }
)
# Browse listings are long (hundreds of folders, a thousand stations); only these keys are read
BROWSE_KEYS = frozenset({"name", "path", "uri", "media_type", "item_id", "provider"})
MAX_RECORDED_STATIONS = 50
SERVER_PLACEHOLDER = "http://music-assistant.invalid"


class UnrecordedCall(BaseException):
    """The code under test made a server call the recording does not hold.

    Derives from BaseException so the resolver's "any server error means try
    the next fallback" wrappers cannot swallow it; a missing recording must
    fail the test, not quietly shape its result.
    """


def prune(value: Any) -> Any:
    """Drop the keys in PRUNED_KEYS from every dict in a response."""
    if isinstance(value, dict):
        return {k: prune(v) for k, v in value.items() if k not in PRUNED_KEYS}
    if isinstance(value, list):
        return [prune(v) for v in value]
    return value


def prune_browse(listing: Any) -> Any:
    """Keep the browse keys the catalog reads; cap a station listing, folder lists stay whole."""
    if not isinstance(listing, list):
        return listing
    slim = [
        {k: v for k, v in item.items() if k in BROWSE_KEYS} if isinstance(item, dict) else item for item in listing
    ]
    if any(isinstance(i, dict) and i.get("media_type") == "radio" for i in slim):
        return slim[:MAX_RECORDED_STATIONS]
    return slim


def redact(value: Any, server_url: str) -> Any:
    """Replace the real server address wherever it appears, for example in image urls."""
    if isinstance(value, dict):
        return {k: redact(v, server_url) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, server_url) for v in value]
    if isinstance(value, str) and server_url:
        return value.replace(server_url, SERVER_PLACEHOLDER)
    return value


def _call_key(command: str, args: Dict[str, Any]) -> str:
    return json.dumps({"command": command, "args": args}, sort_keys=True, default=str)


class RecordingClient(SimpleHTTPMusicAssistantClient):
    """A real client that remembers every exchange so it can be saved."""

    def __init__(self, server_url: str, token: str):
        super().__init__(server_url, token)
        self.calls: List[Dict[str, Any]] = []

    def send_command(self, command: str, **args) -> Any:
        """Send to the real server and remember the exchange, including an error."""
        entry: Dict[str, Any] = {"command": command, "args": redact(args, self.server_url)}
        try:
            response = super().send_command(command, **args)
        except MusicAssistantError as e:
            entry["error"] = redact(str(e), self.server_url)
            self.calls.append(entry)
            raise
        pruned = prune_browse(response) if command == "music/browse" else prune(response)
        entry["response"] = redact(pruned, self.server_url)
        self.calls.append(entry)
        return response

    def save(self, name: str, directory: Path = FIXTURE_DIR) -> Path:
        """Write the exchanges so far to <directory>/<name>.json and start a new recording."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.json"
        recorded = {"recorded": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
        path.write_text(json.dumps({**recorded, "calls": self.calls}, indent=1, ensure_ascii=False) + "\n")
        self.calls = []
        return path


class ReplayClient(SimpleHTTPMusicAssistantClient):
    """Serves recorded responses; a repeated identical call gets the next recorded answer, then the last."""

    def __init__(self, calls: List[Dict[str, Any]]):
        super().__init__(SERVER_PLACEHOLDER)
        self._queues: Dict[str, List[Dict[str, Any]]] = {}
        for call in calls:
            self._queues.setdefault(_call_key(call["command"], call["args"]), []).append(call)

    @classmethod
    def load(cls, name: str, directory: Path = FIXTURE_DIR) -> "ReplayClient":
        """A replay client for the recording named <name>."""
        return cls(json.loads((directory / f"{name}.json").read_text())["calls"])

    def send_command(self, command: str, **args) -> Any:
        """Answer from the recording; an unrecorded call is a test failure."""
        queue = self._queues.get(_call_key(command, args))
        if not queue:
            raise UnrecordedCall(f"{command} {json.dumps(args, sort_keys=True, default=str)}")
        entry = queue.pop(0) if len(queue) > 1 else queue[0]
        if "error" in entry:
            raise MusicAssistantError(entry["error"])
        return entry["response"]

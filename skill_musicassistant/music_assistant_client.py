import uuid
from typing import Any, Dict, List, Optional

import requests
from ovos_utils.log import LOG


class SimpleHTTPMusicAssistantClient:
    """Simple HTTP-based Music Assistant client that avoids WebSocket issues."""

    def __init__(self, server_url: str, session: requests.Session | None = None):
        self.server_url = server_url.rstrip("/")
        self.api_url = f"{self.server_url}/api"
        self.session = session or requests.Session()
        self.log = LOG(self.__class__.__name__)

    def send_command(self, command: str, **args) -> Any:
        """Send a command to Music Assistant via HTTP API."""
        payload = {"command": command, "message_id": uuid.uuid4().hex, "args": args}

        response = self.session.post(self.api_url, json=payload)
        if response.status_code == 200:
            return response.json()
        raise Exception(f"HTTP {response.status_code}: {response.text}")

    def get_players(self) -> List[Any]:
        """Get all available players."""
        result = self.send_command("players/all")
        return [player_data for player_data in result]

    def search_media(self, query: str, media_types: Optional[List[str]] = None, limit: int = 5) -> Dict[str, Any]:
        """Search for media."""
        args = {"search_query": query, "limit": limit}
        if media_types:
            args["media_types"] = media_types
        return self.send_command("music/search", **args)

    def play_media(self, queue_id: str, media: str, option: str = "play", radio_mode: bool = False):
        """Play media on a player queue."""
        self.log.info(
            f"🎵 Sending play_media: queue_id={queue_id}, media={media}, option={option}, radio_mode={radio_mode}"
        )
        return self.send_command(
            command="player_queues/play_media",
            queue_id=queue_id,
            media=media,
            option=option,
            radio_mode=radio_mode,
        )

    def queue_command_play(self, queue_id: str):
        """Send PLAY command to given queue."""
        return self.send_command("player_queues/play", queue_id=queue_id)

    def queue_command_pause(self, queue_id: str):
        """Pause playback."""
        return self.send_command("player_queues/pause", queue_id=queue_id)

    def queue_command_next(self, queue_id: str):
        """Skip to next track."""
        return self.send_command("player_queues/next", queue_id=queue_id)

    def queue_command_previous(self, queue_id: str):
        """Go to previous track."""
        return self.send_command("player_queues/previous", queue_id=queue_id)

    def player_command_power_on(self, player_id: str):
        """Power on a player."""
        return self.send_command("players/player_command_power_on", player_id=player_id)

    def player_command_power_off(self, player_id: str):
        """Power off a player."""
        return self.send_command("players/player_command_power_off", player_id=player_id)

    # Volume control commands
    def player_command_volume_set(self, player_id: str, volume: int):
        """Set player volume (0-100)."""
        return self.send_command("players/cmd/volume_set", player_id=player_id, volume_level=volume)

    def player_command_volume_up(self, player_id: str, step: int = 5):
        """Increase player volume."""
        return self.send_command("players/cmd/volume_up", player_id=player_id, step=step)

    def player_command_volume_down(self, player_id: str, step: int = 5):
        """Decrease player volume."""
        return self.send_command("players/cmd/volume_down", player_id=player_id, step=step)

    def player_command_volume_mute(self, player_id: str, muted: bool = True):
        """Mute/unmute player."""
        return self.send_command("players/cmd/volume_mute", player_id=player_id, muted=muted)

    # State checking methods
    def get_player_queue_items(self, queue_id: str, limit: int = 10, offset: int = 0):
        """Get current queue items for a player."""
        return self.send_command("player_queues/items", queue_id=queue_id, limit=limit, offset=offset)

    def get_active_queue(self, player_id: str):
        """Get the current active queue for a player."""
        return self.send_command("player_queues/get_active_queue", player_id=player_id)

    def _find_player_by_id(self, player_id: str) -> Optional[Any]:
        """Find a player by ID."""
        players = self.get_players()
        for player in players:
            if hasattr(player, "player_id") and player.player_id == player_id:
                return player
            if "player_id" in player and player["player_id"] == player_id:
                return player
        return None

    def _extract_playback_state(self, player: Any) -> str:
        """Extract playback state from player object."""
        if not hasattr(player, "playback_state"):
            return "unknown"

        state = player.playback_state
        return state.value if hasattr(state, "value") else str(state)

    def _extract_track_from_media(self, player: Any) -> Optional[str]:
        """Extract track name from player's current_media."""
        if not (hasattr(player, "current_media") and player.current_media):
            return None

        media = player.current_media
        if not (hasattr(media, "title") and media.title):
            return None

        track_name = media.title
        if hasattr(media, "artist") and media.artist:
            return f"{media.artist} - {track_name}"
        return track_name

    def _extract_track_from_queue(self, player: Any) -> Optional[str]:
        """Extract track name from player's queue items."""
        if not (hasattr(player, "current_item_id") and player.current_item_id):
            return None

        try:
            queue_items = self.get_player_queue_items(player.player_id, limit=1)
            if not (queue_items and len(queue_items) > 0):
                return None

            item = queue_items[0]
            if hasattr(item, "name") and item.name:
                return item.name
            if hasattr(item, "media_item") and item.media_item:
                return getattr(item.media_item, "name", None)
        except:
            self.log.exception("Error extracting track from queue, returning None")
        return None

    def _extract_current_track(self, player: Any) -> str:
        """Extract current track name with artist info."""
        track_name = self._extract_track_from_media(player)
        if track_name:
            return track_name

        track_name = self._extract_track_from_queue(player)
        if track_name:
            return track_name

        return "No track"

    def get_player_state(self, player_id: str):
        """Get current player state (playing, paused, etc.)."""
        player = self._find_player_by_id(player_id)
        if not player:
            return None

        return {
            "state": self._extract_playback_state(player),
            "powered": getattr(player, "powered", True),
            "volume_level": getattr(player, "volume_level", None),
            "volume_muted": getattr(player, "volume_muted", False),
            "current_track": self._extract_current_track(player),
            "player_name": getattr(player, "name", "Unknown"),
        }

    def _format_status_emoji(self, state: str) -> str:
        """Map player state to appropriate emoji."""
        emoji_map = {"playing": "▶️", "paused": "⏸️", "stopped": "⏹️", "idle": "💤"}
        return emoji_map.get(state.lower(), "❓")

    def _format_power_display(self, powered: bool) -> str:
        """Format power status display."""
        return "🔌" if powered else "🔌❌"

    def _format_volume_display(self, volume_level: Optional[int], volume_muted: bool) -> str:
        """Format volume display with mute status."""
        volume_emoji = "🔇" if volume_muted else "🔊"
        if volume_level is not None:
            return f"{volume_emoji} {volume_level}%"
        return f"{volume_emoji} ?"

    def show_current_state(self, player_id: str, action: str = ""):
        """Display current player state and track info."""
        try:
            state = self.get_player_state(player_id)
            if not state:
                self.log.warning(f"   🔍 {action} - Could not get player state")
                return

            status_emoji = self._format_status_emoji(state["state"])
            power_display = self._format_power_display(state["powered"])
            volume_display = self._format_volume_display(state["volume_level"], state.get("volume_muted", False))

            self.log.info(
                f"   🔍 {action} - {status_emoji} {state['state'].title()} | {power_display} | {volume_display}"
            )
            self.log.info(f"   🎵 Current: {state.get('current_track', 'No track')}")

        except Exception as e:
            self.log.exception(f"   🔍 {action} - Error getting state: {e}")

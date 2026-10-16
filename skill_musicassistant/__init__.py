import json
import os
from typing import Dict, List, Optional

import requests
from ma_http_client import SimpleHTTPMusicAssistantClient, debug_method
from music_assistant_models.enums import MediaType, QueueOption, RepeatMode
from music_assistant_models.errors import MusicAssistantError
from music_assistant_models.player import Player
from ovos_bus_client import Message
from ovos_bus_client.session import SessionManager
from ovos_number_parser import extract_number
from ovos_utils.process_utils import RuntimeRequirements
from ovos_workshop.decorators import intent_handler
from ovos_workshop.skills import OVOSSkill
from rapidfuzz import fuzz, process, utils as fuzz_utils


try:
    from ovos_workshop.decorators import fallback_handler
    from ovos_workshop.skills.fallback import FallbackSkill as _SkillBase

    FALLBACK_SUPPORTED = True
except ImportError:  # very old ovos-workshop: load as a plain skill without generic play
    _SkillBase = OVOSSkill
    FALLBACK_SUPPORTED = False

    def fallback_handler(priority: int = 50):
        def decorator(func):
            return func

        return decorator


from skill_musicassistant import catalog
from skill_musicassistant.catalog import ResolvedItem
from skill_musicassistant.request import (
    same_artist,
    split_trailing_location,
    spoken_station_name,
    strip_filler,
    strip_leading_verb,
)
from skill_musicassistant.version import __version__


__all__ = [
    "__version__",
    "MusicAssistantSkill",
    "SimpleHTTPMusicAssistantClient",
]

# Minimum rapidfuzz WRatio score for a spoken name to count as a player match
PLAYER_MATCH_CONFIDENCE = 70
# Session ID used by the local device (i.e. not a HiveMind/Neon Node client)
DEFAULT_SESSION_ID = "default"
# Fallback tier for bare "play X" requests: after every real intent (the medium
# fallback range starts at 5) but before the LLM fallback skills, which sit at 85+.
GENERIC_PLAY_FALLBACK_PRIORITY = 50
# How many tracks a genre or random request queues; shuffle makes the sample feel endless enough
GENRE_TRACK_LIMIT = 50
RANDOM_TRACK_LIMIT = 50
# A genre slot shorter than this is STT noise ("play in music"), so it means random
MIN_GENRE_LENGTH = 3
# Which dialog announces a resolved item of each Music Assistant media type
PLAYING_DIALOG_BY_TYPE = {
    "artist": "playing",
    "track": "playing",
    "album": "playing_album",
    "playlist": "playing_playlist",
    "radio": "playing_radio",
}


class MusicAssistantSkill(_SkillBase):
    """OVOS/Neon skill for music assistant functionality."""

    def __init__(self, *args, bus=None, skill_id="", **kwargs):
        # defaults first, so stop() and shutdown() work even if initialize() fails
        self.session: Optional[requests.Session] = None
        self.mass_client: Optional[SimpleHTTPMusicAssistantClient] = None
        self.players: List[Player] = []
        self.cache_refreshed: bool = False
        self.last_player: Dict[str, Player] = {}  # keyed by session ID for Neon Nodes/HiveMind clients
        self.session_default_players: Dict[str, str] = {}  # session ID -> default player name, in-memory only
        self._last_used_player: Optional[Player] = None
        super().__init__(*args, bus=bus, skill_id=skill_id, **kwargs)

    def initialize(self):
        """Initialize the skill and set up Music Assistant client"""
        # TODO: Validate that OCP is not enabled, log a warning if it is
        if not FALLBACK_SUPPORTED:
            self.log.warning("ovos-workshop has no fallback API; generic 'play X' requests are disabled")
        self.session = requests.Session()
        self.mass_client = SimpleHTTPMusicAssistantClient(
            server_url=self.music_assistant_url, token=self.music_assistant_token, session=self.session
        )
        if not self.configured:
            self.log.error("music_assistant_url is not set in the skill settings; playback requests will say so")
        try:
            self.players = self.mass_client.get_players()
        except Exception as e:
            # the server may be down or not configured yet; players are fetched again on the first request
            self.log.warning("Music Assistant at %s is not reachable yet: %s", self.music_assistant_url, e)
            self.players = []

    @property
    def music_assistant_url(self):
        """Get the Music Assistant server URL from the skill settings"""
        # Use base HTTP URL - client will automatically add /ws for WebSocket connection
        return self.settings.get("music_assistant_url", "http://localhost:8095")

    @property
    def music_assistant_token(self):
        """Get the Music Assistant token from the skill settings"""
        return self.settings.get("music_assistant_token")

    @property
    def default_player(self):
        """Get the global default player from the skill settings"""
        return self.settings.get("default_player")

    @property
    def configured(self) -> bool:
        """Whether the skill settings name a Music Assistant server."""
        return bool(self.settings.get("music_assistant_url"))

    def _persist_setting(self, key: str, value) -> None:
        """Write one setting without the race that can empty settings.json.

        ovos-workshop reloads settings on every file change and JsonStorage
        clears the dict before parsing, so a plain settings.store() that gets
        reloaded mid-write can persist {} and lose the server url and token
        (seen live on a Neon Hub). Merge with what is on disk and replace the
        file atomically instead.
        """
        self.settings[key] = value
        path = getattr(self.settings, "path", None)
        if not path:
            return
        on_disk: Dict[str, object] = {}
        try:
            with open(path, encoding="utf-8") as fh:
                on_disk = json.load(fh) or {}
        except (OSError, ValueError):
            pass
        merged = {**on_disk, **dict(self.settings), key: value}
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, indent=4, ensure_ascii=False)
        os.replace(tmp_path, path)

    @property
    def generic_play_fallback(self) -> bool:
        """Whether bare "play X" utterances that no intent claimed are resolved by name."""
        return bool(self.settings.get("generic_play_fallback", True))

    @property
    def network_requirements(self):
        """Declare the runtime requirements for the skill.

        This will affect when the skill is loaded by core. If the requirements
        are not met, the skill will not be loaded until they are met.
        """
        return RuntimeRequirements(
            internet_before_load=True,
            network_before_load=True,
            gui_before_load=False,
            requires_internet=True,
            requires_network=True,
            requires_gui=False,
            no_internet_fallback=False,
            no_network_fallback=False,
            no_gui_fallback=True,
        )

    def _match_player(self, name: Optional[str]) -> Optional[Player]:
        """Fuzzy-match a spoken name against the cached players, tolerating STT noise."""
        if not name or not self.players:
            return None
        candidates = process.extract(
            name,
            [player.name for player in self.players],
            scorer=fuzz.WRatio,
            processor=fuzz_utils.default_process,
            score_cutoff=PLAYER_MATCH_CONFIDENCE,
            limit=None,
        )
        if not candidates:
            self.log.debug("No player matched %s with confidence >= %s", name, PLAYER_MATCH_CONFIDENCE)
            return None
        matched_name, score, index = max(candidates, key=lambda c: self._match_rank(name, c))
        self.log.debug("Matched player %s to %s (score %s)", name, matched_name, score)
        return self.players[index]

    @staticmethod
    def _match_rank(spoken: str, candidate) -> tuple:
        """Highest score wins; on a tie, "Office speaker" beats "Office speaker+" for "office speaker".

        rapidfuzz strips punctuation before scoring, so sibling players that differ
        only by a suffix tie. Prefer the one whose raw name equals the spoken name,
        then the shorter name.
        """
        matched_name, score, _ = candidate
        exact = matched_name.strip().lower() == spoken.strip().lower()
        return (score, exact, -len(matched_name))

    def _session_default_player(self, message: Optional[Message] = None) -> Optional[str]:
        """Get this session's default player override, if one was set by voice."""
        session = SessionManager.get(message)
        return self.session_default_players.get(session.session_id)

    def _get_player_id(self, location=None, message: Optional[Message] = None):
        """
        Resolve player ID with fallback logic:
        1. Explicit location from utterance (fuzzy matched)
        2. This session's default player, if one was set by voice
        3. Default player from settings
        """
        self.log.debug("Getting player ID for location: %s", location)
        for candidate in (location, self._session_default_player(message), self.default_player):
            player = self._match_player(candidate)
            if player:
                self.cache_refreshed = False
                self.last_player[SessionManager.get(message).session_id] = player
                self._last_used_player = player
                return player.player_id
        if not self.mass_client:
            self.log.warning("Music Assistant client not initialized, cannot get player ID")
            return ""

        try:
            # Get all available players using our HTTP client
            if self.cache_refreshed:
                self.log.error("Cache already refreshed, player ID cannot be found")
                self.cache_refreshed = False
                return None
            self.log.info("Could not find %s in cache, getting players from Music Assistant", location)
            players: list[Player] = self.mass_client.get_players()
            self.log.info("Got %s players", len(players))
            self.players = players
            self.cache_refreshed = True
            return self._get_player_id(location, message)

        except Exception as e:
            self.log.error("Error getting players: %s", e)
            import traceback

            self.log.error("Full traceback: %s", traceback.format_exc())

        return None

    def _search_media(self, query, media_type=None, artist=None, album=None):
        """Search for media using the Music Assistant HTTP client"""
        # TODO: Allow generic search
        try:
            if not self.mass_client:
                self.log.error("Mass client not initialized")
                return None

            search_results = self.mass_client.search_media(
                query=query, media_types=[media_type] if media_type else None, limit=5
            )

            # Filter results by media type and additional criteria
            if media_type == MediaType.TRACK and "tracks" in search_results:
                from music_assistant_models.media_items import Track

                tracks = [Track.from_dict(t) for t in search_results["tracks"]]
                if artist:
                    # Safe attribute access for track artist
                    tracks = [
                        t
                        for t in tracks
                        if hasattr(t, "artist")
                        and t.artist
                        and hasattr(t.artist, "name")
                        and artist.lower() in t.artist.name.lower()
                    ]
                if album:
                    # Safe attribute access for track album
                    tracks = [
                        t
                        for t in tracks
                        if hasattr(t, "album")
                        and t.album
                        and hasattr(t.album, "name")
                        and album.lower() in t.album.name.lower()
                    ]
                return tracks[0] if tracks else None

            elif media_type == MediaType.ARTIST and "artists" in search_results:
                from music_assistant_models.media_items import Artist

                artists = [Artist.from_dict(a) for a in search_results["artists"]]
                return artists[0] if artists else None

            elif media_type == MediaType.ALBUM and "albums" in search_results:
                from music_assistant_models.media_items import Album

                albums = [Album.from_dict(a) for a in search_results["albums"]]
                if artist:
                    # Safe attribute access for album artist
                    albums = [
                        a
                        for a in albums
                        if hasattr(a, "artist")
                        and a.artist
                        and hasattr(a.artist, "name")
                        and artist.lower() in a.artist.name.lower()
                    ]
                return albums[0] if albums else None

            elif media_type == MediaType.PLAYLIST and "playlists" in search_results:
                from music_assistant_models.media_items import Playlist

                playlists = [Playlist.from_dict(p) for p in search_results["playlists"]]
                return playlists[0] if playlists else None

            elif media_type == MediaType.RADIO and "radio" in search_results:
                from music_assistant_models.media_items import Radio

                radios = [Radio.from_dict(r) for r in search_results["radio"]]
                return radios[0] if radios else None

        except Exception as e:
            self.log.error("Search error: %s", e)

        return None

    def _play_media_item(
        self, media_item, player_id, radio_mode=False, enqueue=QueueOption.PLAY, shuffle: Optional[bool] = None
    ) -> bool:
        """Play a media item using the Music Assistant HTTP client"""
        try:
            if self.mass_client is None:
                self.log.error("Failed to create Music Assistant client")
                return False

            kwargs = {"queue_id": player_id, "media": media_item.uri, "option": enqueue, "radio_mode": radio_mode}
            if shuffle is not None:
                kwargs["shuffle"] = shuffle
            self.mass_client.play_media(**kwargs)
            return True
        except Exception as e:
            self.log.error("Play media error: %s", e)
            return False

    def _resolve(self, resolver, *args) -> Optional[ResolvedItem]:
        """Run a server-side by-name lookup; None on any failure so callers fall back to search."""
        try:
            return resolver(self.mass_client, *args)
        except Exception as e:
            self.log.warning("By-name lookup failed, falling back to search: %s", e)
            return None

    @staticmethod
    def _as_resolved(model_item, media_type: str) -> ResolvedItem:
        """Adapt a music_assistant_models item from the search path to a ResolvedItem."""
        artists = getattr(model_item, "artists", None) or []
        artist = artists[0].name if artists else None
        return ResolvedItem(name=model_item.name, uri=model_item.uri, media_type=media_type, artist=artist)

    def _album_from_search(self, album_name: str, artist_name: Optional[str]) -> Optional[ResolvedItem]:
        """Free-text album search; says how many matched when the name is ambiguous."""
        try:
            albums = catalog.search_albums(self.mass_client, album_name)
        except Exception as e:
            self.log.error("Album search error: %s", e)
            return None
        if artist_name:
            albums = [a for a in albums if same_artist(artist_name, a.artist)] or albums
        if not albums:
            return None
        if len(albums) > 1 and not artist_name:
            self.speak_dialog("found_several_albums", {"count": len(albums), "album": album_name})
        return albums[0]

    def _speak_if_different_artist(self, requested: Optional[str], item: ResolvedItem):
        if requested and not same_artist(requested, item.artist):
            self.speak_dialog("playing_different_artist", {"requested": requested, "actual": item.artist or ""})

    def _speak_playing(self, item: ResolvedItem):
        """Announce a resolved item with the dialog its media type already uses."""
        artist = item.artist or "Unknown Artist"
        dialog = PLAYING_DIALOG_BY_TYPE.get(item.media_type)
        if dialog == "playing":
            track_name = item.name if item.media_type == "track" else "music"
            self.speak_dialog(dialog, {"track_name": track_name, "artist_name": artist})
        elif dialog == "playing_album":
            self.speak_dialog(dialog, {"album": item.name, "artist": artist})
        elif dialog == "playing_playlist":
            self.speak_dialog(dialog, {"playlist": item.name})
        elif dialog == "playing_radio":
            self.speak_dialog(dialog, {"radio": spoken_station_name(item.name)})
        else:
            self.speak_dialog("playing_generic", {"name": item.name})

    def _get_player(self, location=None, message: Optional[Message] = None) -> str:
        """Get the player ID for the given location"""
        if not self.configured:
            self.speak_dialog("not_configured")
            return ""
        player_id = self._get_player_id(location, message)
        if not player_id:
            self.speak_dialog("could_not_find_player")
            self.gui.show_text(f"Could not find a player for {location}.")
            return ""
        player = self._last_used_player
        if player is not None and getattr(player, "available", True) is False:
            self.speak_dialog("player_unavailable", {"player": player.name})
            return ""
        return player_id

    def _handle_exception(self, e: Exception, log_message: str, dialog: str, dialog_data: Optional[dict] = None):
        self.log.exception(log_message, e)
        self.gui.show_text(f"{log_message}. Check the logs for more details.")
        self.speak_dialog(dialog, dialog_data or {})

    def _load_volume_aliases(self):
        """Load locale-specific volume aliases."""
        cache_key = f"{self.lang}:volume_levels.value"
        if cache_key not in self.resources.static:
            aliases = {}
            try:
                values = self.resources.load_named_value_file("volume_levels").items()
            except FileNotFoundError:
                values = []
            for name, value in values:
                key = name.lower().strip()
                raw = str(value).strip().lower()
                try:
                    aliases[key] = int(raw)
                except ValueError:
                    aliases[key] = raw
            self.resources.static[cache_key] = aliases
        return self.resources.static[cache_key]

    def _load_cached_list(self, name: str):
        """Load and cache a locale list resource."""
        cache_key = f"{self.lang}:{name}.list"
        if cache_key not in self.resources.static:
            try:
                values = self.resources.load_list_file(name) or []
            except FileNotFoundError:
                values = []
            self.resources.static[cache_key] = values
        return self.resources.static[cache_key]

    def _get_volume_action(self, message: Message):
        """Extract mute actions from the localized utterance."""
        utterance = message.data.get("utterance", "")
        if not utterance:
            return None
        if self.voc_match(utterance, "unmute", lang=self.lang):
            return "unmute"
        if self.voc_match(utterance, "mute", lang=self.lang):
            return "mute"
        return None

    @intent_handler("play_artist.intent")
    def handle_play_artist(self, message: Message):
        """Handle playing an artist"""
        artist_name = message.data.get("artist")
        location = message.data.get("location")

        try:
            # Get player
            player_id = self._get_player(location, message)
            if not player_id:
                return

            # Search for artist
            artist = self._search_media(artist_name, MediaType.ARTIST)
            if not artist:
                self.speak_dialog("could_not_find_artist", {"artist": artist_name})
                self.gui.show_text(f"Could not find the artist {artist_name}.")
                return
            # Play artist
            success: bool = self._play_media_item(artist, player_id, shuffle=True)
            self.log.info("Play artist success: %s", success)
            self.gui.show_text(f"Playing {artist.name}.")

            if success:
                self.speak_dialog(
                    "playing",
                    {
                        "track_name": "music",
                        "artist_name": artist.name,
                    },
                )
            else:
                self.speak_dialog("could_not_play_artist", {"artist": artist_name})

        except MusicAssistantError as e:
            self._handle_exception(e, "Music Assistant error: %s", "could_not_play_artist", {"artist": artist_name})
        except Exception as e:
            self._handle_exception(
                e,
                "Unexpected error while trying to play an artist: %s",
                "could_not_play_artist",
                {"artist": artist_name},
            )

    # This is also resume after pause
    @intent_handler("pause.intent")
    def handle_pause(self, message: Message):
        """Pause, or resume when the request says so; never the play/pause toggle."""
        self.log.debug("Pause intent received:\n%s", message.data)
        location = message.data.get("location")
        resume = self.voc_match(message.data.get("utterance", ""), "resume", lang=self.lang)

        try:
            # Get player
            player_id = self._get_player(location, message)
            if not player_id:
                return

            if resume:
                self.mass_client.send_command("player_queues/resume", queue_id=player_id)
                self.speak_dialog("resumed")
            else:
                self.mass_client.send_command("player_queues/pause", queue_id=player_id)
                self.speak_dialog("paused")

        except Exception as e:
            self.log.error("Pause error: %s", e)
            self.speak_dialog("could_not_pause")

    @intent_handler("next.intent")
    def handle_next(self, message: Message):
        """Handle next track commands"""
        self.log.debug("Next intent received:\n%s", message.data)
        location = message.data.get("location")

        try:
            # Get player
            player_id = self._get_player(location, message)
            if not player_id:
                return

            if self.mass_client:
                self.mass_client.queue_command_next(player_id)
            self.speak_dialog("next_track")

        except Exception as e:
            self.log.error("Next error: %s", e)
            self.speak_dialog("could_not_next_track")

    @intent_handler("previous.intent")
    def handle_previous(self, message: Message):
        """Handle previous track commands"""
        self.log.debug("Previous intent received:\n%s", message.data)
        location = message.data.get("location")

        try:
            # Get player
            player_id = self._get_player(location, message)
            if not player_id:
                return

            if self.mass_client:
                self.mass_client.queue_command_previous(player_id)
            self.speak_dialog("previous_track")

        except Exception as e:
            self.log.error("Previous error: %s", e)
            self.speak_dialog("could_not_previous_track")

    @intent_handler("volume.intent")
    def handle_volume(self, message: Message):
        """Handle volume control commands"""
        self.log.debug("Volume intent received:\n%s", message.data)
        volume_level = message.data.get("volume_level")
        location = message.data.get("location")

        try:
            # Get player
            player_id = self._get_player(location, message)
            if not player_id:
                return

            action = self._get_volume_action(message)
            if action == "unmute":
                self.log.info("Unmuting player %s", player_id)
                self.mass_client.player_command_volume_mute(player_id, muted=False)
                self.speak_dialog("volume_unmuted")
                return
            if action == "mute":
                self.log.info("Muting player %s", player_id)
                self.mass_client.player_command_volume_mute(player_id, muted=True)
                self.speak_dialog("volume_muted")
                return

            # Parse volume level (could be "50", "fifty", "moitié", etc.)
            volume = self._parse_volume_level(volume_level)
            if volume == "up":
                self.mass_client.player_command_volume_up(player_id)
                self.speak_dialog("volume_up")
                return
            if volume == "down":
                self.mass_client.player_command_volume_down(player_id)
                self.speak_dialog("volume_down")
                return
            if volume is None:
                self.log.error("Invalid volume level: %s", volume_level)
                self.speak_dialog("could_not_understand_volume", {"volume_level": volume_level})
                return

            # Use our HTTP client for volume control
            if self.mass_client:
                self.log.info("Setting volume to %s for player %s", volume, player_id)
                self.mass_client.player_command_volume_set(player_id, volume)
            self.log.debug("Set volume to %s for player %s", volume, player_id)
            self.speak_dialog("volume_set", {"volume": volume})

        except Exception as e:
            self.log.error("Volume error: %s", e)
            self.speak_dialog("could_not_change_volume")

    @debug_method
    def _parse_volume_level(self, volume_input: str):
        """Parse volume level from various input formats"""
        if not volume_input:
            return None

        volume_input = str(volume_input).lower().strip()

        # Handle numeric input
        if volume_input.isdigit():
            vol = int(volume_input)
            return max(0, min(100, vol))

        aliases = self._load_volume_aliases()
        if volume_input in aliases:
            return aliases[volume_input]

        # Handle localized percent suffixes before full number parsing so
        # phrases like "trente pour cent" don't get misread as 100.
        for suffix in ["%", *self._load_cached_list("percent_phrases")]:
            if suffix and volume_input.endswith(suffix):
                num_part = volume_input[: -len(suffix)].strip()
                if num_part.isdigit():
                    vol = int(num_part)
                    return max(0, min(100, vol))
                volume = extract_number(num_part, lang=self.lang)
                if volume is not None and volume is not False:
                    return max(0, min(100, int(volume)))

        volume = extract_number(volume_input, lang=self.lang)
        if volume is not None and volume is not False:
            return max(0, min(100, int(volume)))

        return None

    @intent_handler("play_track.intent")
    def handle_play_track(self, message: Message):
        """Handle playing a track"""

        track_name = message.data.get("track")
        artist_name = message.data.get("artist")
        location = message.data.get("location")
        radio_mode = message.data.get("radio_mode")

        try:
            # Get player
            player_id = self._get_player(location, message)
            if not player_id:
                return

            track = self._resolve(catalog.resolve_track, track_name, artist_name)
            if not track:
                found = self._search_media(track_name, MediaType.TRACK, artist_name)
                track = self._as_resolved(found, "track") if found else None
            if not track and artist_name:
                # minimy's diff_artist: play the version we have and say whose it is
                track = self._resolve(catalog.resolve_track, track_name)
            if not track:
                search_query = f"{track_name} {artist_name}" if artist_name else track_name
                self.log.error("No track found for search query: %s", search_query)
                self.speak_dialog("could_not_find_track", {"track": search_query})
                return

            self.log.info("Playing track %s on player %s", track, player_id)
            success = self._play_media_item(track, player_id, bool(radio_mode))

            if success:
                self._speak_if_different_artist(artist_name, track)
                self._speak_playing(track)
            else:
                self.speak_dialog("could_not_play_track", {"track": track_name})

        except MusicAssistantError as e:
            self._handle_exception(e, "Music Assistant error: %s", "could_not_play_track", {"track": track_name})
        except Exception as e:
            self._handle_exception(
                e,
                "Unexpected error while trying to play a track: %s",
                "could_not_play_track",
                {"track": track_name},
            )

    @intent_handler("play_album.intent")
    def handle_play_album(self, message: Message):
        """Handle playing an album"""

        album_name = message.data.get("album")
        artist_name = message.data.get("artist")
        location = message.data.get("location")
        radio_mode = message.data.get("radio_mode")  # TODO: Devise tests for this, possibly remove

        try:
            # Get player
            player_id = self._get_player(location, message)
            if not player_id:
                return

            album = self._resolve(catalog.resolve_album, album_name, artist_name)
            if not album:
                album = self._album_from_search(album_name, artist_name)
            if not album and artist_name:
                album = self._resolve(catalog.resolve_album, album_name)
            if not album:
                search_query = f"{album_name} {artist_name}" if artist_name else album_name
                self.speak_dialog("could_not_find_album", {"album": search_query})
                return

            self.log.info("Playing album %s on player %s", album, player_id)
            success = self._play_media_item(album, player_id, radio_mode or False)

            if success:
                self._speak_if_different_artist(artist_name, album)
                self._speak_playing(album)
            else:
                self.speak_dialog("could_not_play_album", {"album": album_name})

        except MusicAssistantError as e:
            self._handle_exception(e, "Music Assistant error: %s", "could_not_play_album", {"album": album_name})
        except Exception as e:
            self._handle_exception(
                e,
                "Unexpected error while trying to play an album: %s",
                "could_not_play_album",
                {"album": album_name},
            )

    @intent_handler("play_playlist.intent")
    def handle_play_playlist(self, message: Message):
        """Handle playing a playlist"""

        playlist_name = message.data.get("playlist")
        location = message.data.get("location")

        try:
            # Get player
            player_id = self._get_player(location, message)
            if not player_id:
                return

            # Search for playlist
            playlist = self._search_media(playlist_name, MediaType.PLAYLIST)
            if not playlist:
                self.log.error("No playlist found for search query: %s", playlist_name)
                self.speak_dialog("could_not_find_playlist", {"playlist": playlist_name})
                return

            # Play playlist
            self.log.info("Playing playlist %s on player %s", playlist, player_id)
            success = self._play_media_item(playlist, player_id)

            if success:
                self.speak_dialog("playing_playlist", {"playlist": playlist.name})
            else:
                self.speak_dialog("could_not_play_playlist", {"playlist": playlist_name})

        except MusicAssistantError as e:
            self._handle_exception(
                e,
                "Music Assistant error while trying to play a playlist: %s",
                "could_not_play_playlist",
                {"playlist": playlist_name},
            )
        except Exception as e:
            self._handle_exception(
                e,
                "Unexpected error while trying to play a playlist: %s",
                "could_not_play_playlist",
                {"playlist": playlist_name},
            )

    def _with_radio_word(self, spoken: str) -> str:
        """ "bbc 1" said inside a radio request means "bbc 1 radio", which outranks "bbc 1 tv"."""
        words = spoken.lower().split()
        return spoken if "radio" in words else f"{spoken} radio"

    @intent_handler("play_radio.intent")
    def handle_play_radio(self, message: Message):
        """Handle playing radio stations"""

        station_name = message.data.get("radio_station")
        location = message.data.get("location")

        try:
            # Get player
            player_id = self._get_player(location, message)
            if not player_id:
                return

            # Search for radio station
            station = self._resolve(catalog.search_radio, station_name, self._with_radio_word(station_name))
            if not station:
                found = self._search_media(station_name, MediaType.RADIO)
                station = self._as_resolved(found, "radio") if found else None
            if not station:
                self.speak_dialog("could_not_find_radio", {"station": station_name})
                return

            # Play radio station
            self.log.info("Playing radio station %s on player %s", station, player_id)
            success = self._play_media_item(station, player_id)

            if success:
                self.speak_dialog("playing_radio", {"radio": spoken_station_name(station.name)})
            else:
                self.speak_dialog("could_not_play_radio", {"station": station_name})

        except MusicAssistantError as e:
            self._handle_exception(e, "Music Assistant error: %s", "could_not_play_radio", {"station": station_name})
        except Exception as e:
            self._handle_exception(e, "Unexpected error: %s", "could_not_play_radio", {"station": station_name})

    def _current_media(self, message: Message):
        """(player_id, NowPlaying) for the requested or default player; speaks when nothing plays."""
        player_id = self._get_player(message.data.get("location"), message)
        if not player_id:
            return None, None
        try:
            now = catalog.now_playing_for(self.mass_client, player_id)
        except Exception as e:
            self.log.error("Could not read the current media: %s", e)
            now = None
        if not now:
            self.speak_dialog("nothing_playing")
        return player_id, now

    @intent_handler("now_playing.intent")
    def handle_now_playing(self, message: Message):
        """Say which track and artist a player is rendering."""
        _, now = self._current_media(message)
        if not now:
            return
        if now.is_radio:
            station = spoken_station_name(now.station or "")
            if now.title != now.station:
                self.speak_dialog("now_playing_radio_track", {"title": now.title, "station": station})
            else:
                self.speak_dialog("now_playing_radio", {"station": station})
            self.gui.show_text(station)
            return
        self.speak_dialog("now_playing", {"title": now.title, "artist": now.artist or "Unknown Artist"})
        self.gui.show_text(f"{now.title} - {now.artist or ''}")

    @intent_handler("like.intent")
    def handle_like(self, message: Message):
        """Add the current track to the Music Assistant favorites."""
        _, now = self._current_media(message)
        if not now:
            return
        if not now.uri:
            self.speak_dialog("could_not_find_track", {"track": now.title})
            return
        try:
            self.mass_client.add_favorite(now.uri)
        except Exception as e:
            self._handle_exception(e, "Could not add to favorites: %s", "could_not_find_track", {"track": now.title})
            return
        self.speak_dialog("liked", {"title": now.title})

    def can_answer(self, *args, **kwargs) -> bool:
        """Pre-check the fallback service runs before dispatching to this skill.

        Signature differs by ovos-workshop version: ``(utterances, lang)`` on the
        0.x line Neon ships, ``(message)`` on 9.x, where it is also abstract.
        Claims only utterances that start with a play verb.
        """
        if not self.generic_play_fallback:
            return False
        verbs = self._load_cached_list("play_verbs")
        return any(strip_leading_verb(u, verbs) for u in self._utterances_from(args, kwargs))

    @staticmethod
    def _utterances_from(args, kwargs) -> List[str]:
        """Normalize the two can_answer calling conventions to a list of transcriptions."""
        candidate = kwargs.get("message") or kwargs.get("utterances") or (args[0] if args else None)
        if isinstance(candidate, Message):
            return list(candidate.data.get("utterances") or [candidate.data.get("utterance", "")])
        if isinstance(candidate, str):
            return [candidate]
        return list(candidate or [])

    @fallback_handler(priority=GENERIC_PLAY_FALLBACK_PRIORITY)
    def handle_generic_play(self, message: Message) -> bool:
        """Resolve "play X" with no type word when no intent claimed it.

        Runs in the medium fallback tier, after every registered intent and
        before the LLM fallbacks (85+). Claims the utterance only when it starts
        with a play verb AND the server resolves the remainder to something
        playable; otherwise returns False so later fallbacks get their turn.
        """
        if not self.generic_play_fallback:
            return False
        utterance = message.data.get("utterance", "")
        query = strip_leading_verb(utterance, self._load_cached_list("play_verbs"))
        if not query:
            return False
        query, player_id = self._query_and_player(query, message)
        if not player_id:
            return False
        item = self._resolve(catalog.resolve_generic, query)
        if not item:
            return False
        shuffle = True if item.media_type in ("artist", "playlist") else None
        if not self._play_media_item(item, player_id, shuffle=shuffle):
            return False
        self._speak_playing(item)
        return True

    def _query_and_player(self, query: str, message: Message):
        """Peel a trailing "on the kitchen speaker" off the query when it names a player."""
        for remainder, location in split_trailing_location(query, self._load_cached_list("location_prefixes")):
            if self._match_player(location):
                return remainder, self._get_player_id(location, message)
        return query, self._get_player_id(None, message)

    def _play_uris(self, uris: List[str], player_id: str) -> bool:
        """Replace the queue with a shuffled list of uris.

        A genre or random request starts a new listening session, so the old
        queue goes; inserting left a Hub queue at 2,600 items after an hour.
        """
        try:
            self.mass_client.play_media(queue_id=player_id, media=uris, option=QueueOption.REPLACE, shuffle=True)
            return True
        except Exception as e:
            self.log.error("Play media error: %s", e)
            return False

    @intent_handler("play_genre.intent")
    def handle_play_genre(self, message: Message):
        """Play a shuffled sample of a library genre.

        "play {genre} music" also catches "play some music" and "play beatles
        music", so filler words mean random and a name that is not a genre is
        resolved like a bare "play X".
        """
        spoken = strip_filler(
            message.data.get("genre") or "",
            self._load_cached_list("random_words"),
            self._load_cached_list("media_words"),
        )
        if not spoken or len(spoken) < MIN_GENRE_LENGTH:
            return self.handle_play_random(message)
        player_id = self._get_player(message.data.get("location"), message)
        if not player_id:
            return
        genre = self._resolve(catalog.find_genre, spoken)
        if genre:
            self._play_genre(genre, spoken, player_id)
            return
        item = self._resolve(catalog.resolve_generic, spoken)
        if not item:
            self.speak_dialog("could_not_find_genre", {"genre": spoken})
            return
        shuffle = True if item.media_type in ("artist", "playlist") else None
        if self._play_media_item(item, player_id, shuffle=shuffle):
            self._speak_playing(item)
        else:
            self.speak_dialog("could_not_play_music")

    def _play_genre(self, genre: dict, spoken: str, player_id: str):
        uris = self._resolve(catalog.genre_uris, genre, GENRE_TRACK_LIMIT)
        if not uris:
            self.speak_dialog("could_not_find_genre", {"genre": spoken})
            return
        if self._play_uris(uris, player_id):
            self.speak_dialog("playing_genre", {"genre": genre.get("name") or spoken})
        else:
            self.speak_dialog("could_not_play_music")

    @intent_handler("play_random.intent")
    def handle_play_random(self, message: Message):
        """Play a random, shuffled sample of the whole library."""
        player_id = self._get_player(message.data.get("location"), message)
        if not player_id:
            return
        uris = self._resolve(catalog.random_track_uris, RANDOM_TRACK_LIMIT)
        if not uris:
            self.speak_dialog("library_empty")
            return
        if self._play_uris(uris, player_id):
            self.speak_dialog("playing_random")
        else:
            self.speak_dialog("could_not_play_music")

    @intent_handler("shuffle.intent")
    def handle_shuffle(self, message: Message):
        """Turn queue shuffle on or off."""
        enabled = not self.voc_match(message.data.get("utterance", ""), "shuffle_off", lang=self.lang)
        player_id = self._get_player(message.data.get("location"), message)
        if not player_id:
            return
        try:
            self.mass_client.queue_set_shuffle(player_id, enabled)
        except Exception as e:
            self._handle_exception(e, "Could not change shuffle: %s", "could_not_play_music")
            return
        self.speak_dialog("shuffle_on" if enabled else "shuffle_off")

    @intent_handler("repeat.intent")
    def handle_repeat(self, message: Message):
        """Set the queue repeat mode from the words used: off, all, or this track."""
        mode = self._repeat_mode(message.data.get("utterance", ""))
        player_id = self._get_player(message.data.get("location"), message)
        if not player_id:
            return
        try:
            self.mass_client.queue_set_repeat(player_id, mode)
        except Exception as e:
            self._handle_exception(e, "Could not change repeat: %s", "could_not_play_music")
            return
        self.speak_dialog(f"repeat_{mode.value}")

    def _repeat_mode(self, utterance: str) -> RepeatMode:
        if self.voc_match(utterance, "repeat_off", lang=self.lang):
            return RepeatMode.OFF
        if self.voc_match(utterance, "repeat_all", lang=self.lang):
            return RepeatMode.ALL
        return RepeatMode.ONE

    @intent_handler("set_default_player.intent")
    def handle_set_default_player(self, message: Message):
        """Handle setting the default player for this session (or globally for the local device)"""
        spoken_name = message.data.get("player")
        player = self._match_player(spoken_name)
        if not player and self.mass_client:
            try:
                self.players = self.mass_client.get_players()
            except Exception as e:
                self.log.error("Error refreshing players: %s", e)
            player = self._match_player(spoken_name)
        if not player:
            self.speak_dialog("could_not_find_player")
            self.gui.show_text(f"Could not find a player matching {spoken_name}.")
            return

        session = SessionManager.get(message)
        if session.session_id == DEFAULT_SESSION_ID:
            self._persist_setting("default_player", player.name)
        else:
            self.session_default_players[session.session_id] = player.name
        self.log.info("Default player for session %s set to %s", session.session_id, player.name)
        self.speak_dialog("default_player_set", {"player": player.name})
        self.gui.show_text(f"Default player set to {player.name}.")

    def shutdown(self):
        """Clean shutdown"""
        if self.session:
            # Close requests session
            self.session.close()

        super().shutdown()

    def stop(self) -> bool | None:
        """Handle stop commands
        This method should return True if it stopped something or
        False (or None) otherwise.
        """
        player = self._stop_target()
        if player is None or not self.mass_client:
            return False
        try:
            if self._playback_state(player) not in ("playing", "paused"):
                return False
            # a real stop: play_pause would start a paused or idle speaker
            self.mass_client.player_command_stop(player.player_id)
            return True
        except Exception:
            self.log.exception("Error stopping media playback")
            return False

    def _stop_target(self) -> Optional[Player]:
        """The player a bare "stop" means: the one used most recently, else the default. Never a random one."""
        if self._last_used_player is not None:
            return self._last_used_player
        return self._match_player(self.default_player)

    def _playback_state(self, player: Player) -> str:
        """Fresh playback state of a player, lower-cased ("playing", "paused", "idle")."""
        for current in self.mass_client.get_players():
            if current.player_id == player.player_id:
                state = getattr(current, "playback_state", None)
                return str(getattr(state, "value", state) or "").lower()
        return ""

from typing import List

import requests
from music_assistant_models.enums import MediaType, QueueOption
from music_assistant_models.errors import MusicAssistantError
from music_assistant_models.player import Player
from ovos_bus_client import Message
from ovos_utils.process_utils import RuntimeRequirements
from ovos_workshop.decorators import intent_handler
from ovos_workshop.skills import OVOSSkill

from skill_musicassistant.music_assistant_client import SimpleHTTPMusicAssistantClient, debug_method
from skill_musicassistant.version import __version__


__all__ = [
    "__version__",
    "MusicAssistantSkill",
    "SimpleHTTPMusicAssistantClient",
]


class MusicAssistantSkill(OVOSSkill):
    """OVOS/Neon skill for music assistant functionality."""

    def __init__(self, *args, bus=None, skill_id="", **kwargs):
        super().__init__(*args, bus=bus, skill_id=skill_id, **kwargs)

    def initialize(self):
        """Initialize the skill and set up Music Assistant client"""
        # TODO: Validate that OCP is not enabled, log a warning if it is
        self.session = requests.Session()
        self.mass_client = SimpleHTTPMusicAssistantClient(server_url=self.music_assistant_url, session=self.session)
        self.players: List[Player] = self.mass_client.get_players()
        self.cache_refreshed: bool = False
        self.last_player: List[
            Player
        ] = []  # TODO: Probably do this by session ID in a dict to support Neon Nodes/HiveMind

    @property
    def music_assistant_url(self):
        """Get the Music Assistant server URL from the skill settings"""
        # Use base HTTP URL - client will automatically add /ws for WebSocket connection
        return self.settings.get("music_assistant_url", "http://localhost:8095")

    @property
    def default_player(self):
        """Get the default player from the skill settings"""
        # TODO: Intent for setting default player
        # Maybe also make it per session, so we can support Neon Nodes/HiveMind
        return self.settings.get("default_player")

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

    def _get_player_id(self, location=None):
        """
        Resolve player ID with fallback logic:
        1. Explicit location from utterance
        2. Default player from settings
        """
        self.log.debug("Getting player ID for location: %s", location)
        # TODO: Fuzzy search
        player_names = [x.name.lower() for x in self.players]
        if location and location.lower() in player_names:
            self.log.debug("Found player by location in cache: %s", location)
            self.last_player.append(self.players[player_names.index(location.lower())])
            return self.last_player[0].player_id
        # Not in cache, try cached default player
        if self.default_player and self.default_player.lower() in player_names:
            self.log.debug("Couldn't find player by location, found default player in cache: %s", self.default_player)
            self.last_player.append(self.players[player_names.index(self.default_player.lower())])
            return self.last_player[0].player_id
        if not self.mass_client:
            self.log.warning("Music Assistant client not initialized, cannot get player ID")
            return ""

        try:
            # Get all available players using our HTTP client
            if self.cache_refreshed:
                self.log.error("Cache already refreshed, player ID cannot be found")
                self.cache_refreshed = False
                self.speak_dialog("generic_could_not", {"thing": "find a player."})
                return None
            self.log.info("Could not find %s in cache, getting players from Music Assistant", location)
            players: list[Player] = self.mass_client.get_players()
            self.log.info("Got %s players", len(players))
            self.players = players
            self.cache_refreshed = True
            return self._get_player_id(location)

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

    def _play_media_item(self, media_item, player_id, radio_mode=False, enqueue=QueueOption.PLAY) -> bool:
        """Play a media item using the Music Assistant HTTP client"""
        try:
            if self.mass_client is None:
                self.log.error("Failed to create Music Assistant client")
                return False

            # Use our HTTP client to play media
            # TODO: Get enum instead of passing raw string
            self.mass_client.play_media(
                queue_id=player_id, media=media_item.uri, option=enqueue, radio_mode=radio_mode
            )
            return True
        except Exception as e:
            self.log.error("Play media error: %s", e)
            return False

    def _get_player(self, location=None) -> str:
        """Get the player ID for the given location"""
        player_id = self._get_player_id(location)
        if not player_id:
            self.speak_dialog("generic_could_not", {"thing": "find a player."})
            self.gui.show_text(f"Could not find a player for {location}.")
            return ""
        return player_id

    def _handle_exception(self, e: Exception, message: str):
        self.log.exception(message, e)
        self.gui.show_text(f"{message}. Check the logs for more details.")
        self.speak_dialog("generic_could_not", {"thing": message})

    @intent_handler("play_artist.intent")
    def handle_play_artist(self, message: Message):
        """Handle playing an artist"""
        artist_name = message.data.get("artist")
        location = message.data.get("location") or self.default_player

        try:
            # Get player
            player_id = self._get_player(location)
            if not player_id:
                return

            # Search for artist
            artist = self._search_media(artist_name, MediaType.ARTIST)
            if not artist:
                self.speak_dialog("generic_could_not", {"thing": f"find the artist {artist_name}."})
                self.gui.show_text(f"Could not find the artist {artist_name}.")
                return
            # Play artist
            success: bool = self._play_media_item(artist, player_id)
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
                self.speak_dialog("generic_could_not", {"thing": f"play the artist {artist_name}."})

        except MusicAssistantError as e:
            self._handle_exception(e, "Music Assistant error: %s")
        except Exception as e:
            self._handle_exception(e, "Unexpected error while trying to play an artist: %s")

    # This is also resume after pause
    @intent_handler("pause.intent")
    def handle_pause(self, message: Message):
        """Handle pause commands"""
        self.log.debug("Pause intent received:\n%s", message.data)
        location = message.data.get("location")

        try:
            # Get player
            player_id = self._get_player(location)
            if not player_id:
                return

            if self.mass_client:
                self.mass_client.queue_command_pause(player_id)
            self.speak_dialog("paused")

        except Exception as e:
            self.log.error("Pause error: %s", e)
            self.speak_dialog("generic_could_not", {"thing": "pause the music."})

    @intent_handler("next.intent")
    def handle_next(self, message: Message):
        """Handle next track commands"""
        self.log.debug("Next intent received:\n%s", message.data)
        location = message.data.get("location")

        try:
            # Get player
            player_id = self._get_player(location)
            if not player_id:
                return

            if self.mass_client:
                self.mass_client.queue_command_next(player_id)
            self.speak_dialog("next_track")

        except Exception as e:
            self.log.error("Next error: %s", e)
            self.speak_dialog("generic_could_not", {"thing": "skip to the next track."})

    @intent_handler("previous.intent")
    def handle_previous(self, message: Message):
        """Handle previous track commands"""
        self.log.debug("Previous intent received:\n%s", message.data)
        location = message.data.get("location")

        try:
            # Get player
            player_id = self._get_player(location)
            if not player_id:
                return

            if self.mass_client:
                self.mass_client.queue_command_previous(player_id)
            self.speak_dialog("previous_track")

        except Exception as e:
            self.log.error("Previous error: %s", e)
            self.speak_dialog("generic_could_not", {"thing": "go to the previous track."})

    @intent_handler("volume.intent")
    def handle_volume(self, message: Message):
        """Handle volume control commands"""
        self.log.debug("Volume intent received:\n%s", message.data)
        volume_level = message.data.get("volume_level")
        location = message.data.get("location")

        try:
            # Get player
            player_id = self._get_player(location)
            if not player_id:
                return

            # Parse volume level (could be "50", "fifty", "half", etc.)
            volume = self._parse_volume_level(str(volume_level))
            if volume == "up":
                self.mass_client.player_command_volume_up(player_id)
                self.speak_dialog("volume_up")
                return
            if volume == "down":
                self.mass_client.player_command_volume_down(player_id)
                self.speak_dialog("volume_down")
                return
            if volume is None and "mute" in message.data:
                if "unmute" in message.data:
                    self.log.info("Unmuting player %s", player_id)
                    self.mass_client.player_command_volume_mute(player_id, muted=False)
                    self.speak_dialog("volume_unmuted")
                    return
                else:
                    self.log.info("Muting player %s", player_id)
                    self.mass_client.player_command_volume_mute(player_id, muted=True)
                    self.speak_dialog("volume_muted")
                    return
                return
            if volume is None:
                self.log.error("Invalid volume level: %s", volume_level)
                self.speak_dialog("generic_could_not", {"thing": f"understand volume level {volume_level}."})
                return

            # Use our HTTP client for volume control
            if self.mass_client:
                self.log.info("Setting volume to %s for player %s", volume, player_id)
                self.mass_client.player_command_volume_set(player_id, volume)
            self.log.debug("Set volume to %s for player %s", volume, player_id)
            self.speak_dialog("volume_set", {"volume": volume})

        except Exception as e:
            self.log.error("Volume error: %s", e)
            self.speak_dialog("generic_could_not", {"thing": "change the volume."})

    @debug_method
    def _parse_volume_level(self, volume_input: str):
        """Parse volume level from various input formats"""
        if not volume_input:
            return None

        volume_input = volume_input.lower().strip()

        # Handle numeric input
        if volume_input.isdigit():
            vol = int(volume_input)
            return max(0, min(100, vol))

        # Handle word-based volumes
        # TODO: Use OVOS libraries so we can be language agnostic
        volume_words = {
            "zero": 0,
            "off": 0,
            "mute": 0,
            "ten": 10,
            "twenty": 20,
            "thirty": 30,
            "forty": 40,
            "fifty": 50,
            "sixty": 60,
            "seventy": 70,
            "eighty": 80,
            "ninety": 90,
            "hundred": 100,
            "low": 25,
            "medium": 50,
            "high": 75,
            "max": 100,
            "maximum": 100,
            "quiet": 25,
            "loud": 75,
            "half": 50,
            "full": 100,
            "up": "up",
            "down": "down",
        }

        if volume_input in volume_words:
            return volume_words[volume_input]

        # Handle "percent" suffix
        if volume_input.endswith(" percent") or volume_input.endswith("%"):
            num_part = volume_input.replace(" percent", "").replace("%", "")
            if num_part.isdigit():
                vol = int(num_part)
                return max(0, min(100, vol))

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
            player_id = self._get_player(location)
            if not player_id:
                return

            # Search for track
            track = self._search_media(track_name, MediaType.TRACK, artist_name)
            if not track:
                search_query = f"{track_name} {artist_name}" if artist_name else track_name
                self.log.error("No track found for search query: %s", search_query)
                self.speak_dialog("generic_could_not", {"thing": f"find {search_query}."})
                return

            # Play track
            self.log.info("Playing track %s on player %s", track, player_id)
            success = self._play_media_item(track, player_id, bool(radio_mode))

            if success:
                self.speak_dialog(
                    "playing",
                    {
                        "track_name": track.name,
                        "artist_name": track.artists[0].name if track.artists else "Unknown Artist",
                    },
                )
            else:
                self.speak_dialog("generic_could_not", {"thing": f"play {track_name}."})

        except MusicAssistantError as e:
            self.log.exception("Music Assistant error: %s", e)
            self.speak_dialog("generic_could_not", {"thing": "play the track. Check the logs for more details."})
        except Exception as e:
            self.log.exception("Unexpected error while trying to play a track: %s", e)
            self.speak_dialog("generic_could_not", {"thing": "play the track. Check the logs for more details."})

    @intent_handler("play_album.intent")
    def handle_play_album(self, message: Message):
        """Handle playing an album"""

        album_name = message.data.get("album")
        artist_name = message.data.get("artist")
        location = message.data.get("location")
        radio_mode = message.data.get("radio_mode")  # TODO: Devise tests for this, possibly remove

        try:
            # Get player
            player_id = self._get_player(location)
            if not player_id:
                return

            # Search for album
            album = self._search_media(album_name, MediaType.ALBUM, artist_name)
            if not album:
                search_query = f"{album_name} {artist_name}" if artist_name else album_name
                self.speak_dialog("generic_could_not", {"thing": f"find the album {search_query}."})
                return

            # Play album
            self.log.info("Playing album %s on player %s", album, player_id)
            success = self._play_media_item(album, player_id, radio_mode or False)

            if success:
                self.speak_dialog(
                    "playing_album",
                    {
                        "album": album.name,
                        "artist": album.artists[0].name if album.artists else "Unknown Artist",
                    },
                )
            else:
                self.speak_dialog("generic_could_not", {"thing": f"play {album_name}."})

        except MusicAssistantError as e:
            self.log.error("Music Assistant error: %s", e)
            self.speak_dialog("generic_could_not", {"thing": "play the album. Check the logs for more details."})
        except Exception as e:
            self.log.exception("Unexpected error while trying to play an album: %s", e)
            self.speak_dialog("generic_could_not", {"thing": "play the album. Check the logs for more details."})

    @intent_handler("play_playlist.intent")
    def handle_play_playlist(self, message: Message):
        """Handle playing a playlist"""

        playlist_name = message.data.get("playlist")
        location = message.data.get("location")

        try:
            # Get player
            player_id = self._get_player(location)
            if not player_id:
                return

            # Search for playlist
            playlist = self._search_media(playlist_name, MediaType.PLAYLIST)
            if not playlist:
                self.log.error("No playlist found for search query: %s", playlist_name)
                self.speak_dialog("generic_could_not", {"thing": f"find the playlist {playlist_name}."})
                return

            # Play playlist
            self.log.info("Playing playlist %s on player %s", playlist, player_id)
            success = self._play_media_item(playlist, player_id)

            if success:
                self.speak_dialog("playing_playlist", {"playlist": playlist.name})
            else:
                self.speak_dialog("generic_could_not", {"thing": f"play {playlist_name}."})

        except MusicAssistantError as e:
            self.log.exception("Music Assistant error while trying to play a playlist: %s", e)
            self.speak_dialog("generic_could_not", {"thing": "play the playlist. Check the logs for more details."})
        except Exception as e:
            self.log.exception("Unexpected error while trying to play a playlist: %s", e)
            self.speak_dialog("generic_could_not", {"thing": "play the playlist. Check the logs for more details."})

    @intent_handler("play_radio.intent")
    def handle_play_radio(self, message: Message):
        """Handle playing radio stations"""

        station_name = message.data.get("radio_station")
        location = message.data.get("location")

        try:
            # Get player
            player_id = self._get_player(location)
            if not player_id:
                return

            # Search for radio station
            station = self._search_media(station_name, MediaType.RADIO)
            if not station:
                self.speak_dialog("generic_could_not", {"thing": f"find the radio station {station_name}."})
                return

            # Play radio station
            self.log.info("Playing radio station %s on player %s", station, player_id)
            success = self._play_media_item(station, player_id)

            if success:
                self.speak_dialog("playing_radio", {"radio": station.name})
            else:
                self.speak_dialog("generic_could_not", {"thing": f"play {station_name}."})

        except MusicAssistantError as e:
            self.log.error("Music Assistant error: %s", e)
            self.speak_dialog(
                "generic_could_not", {"thing": "play the radio station. Check the logs for more details."}
            )
        except Exception as e:
            self.log.error("Unexpected error: %s", e)
            self.speak_dialog(
                "generic_could_not", {"thing": "play the radio station. Check the logs for more details."}
            )

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
        # TODO: Track the last thing we did and stop it
        try:
            self.mass_client.queue_command_pause(self.mass_client.get_players()[0].player_id)
            return True
        except Exception:
            self.log.exception("Error stopping media playback")
            return False

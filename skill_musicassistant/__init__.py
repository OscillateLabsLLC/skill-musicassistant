import functools
import json
import os
import threading
from typing import Dict, List, Optional

import requests
from ma_http_client import SimpleHTTPMusicAssistantClient, debug_method
from music_assistant_models.enums import QueueOption, RepeatMode
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

    def fallback_handler(priority: int = 50):  # pylint: disable=unused-argument
        """Stand-in that registers nothing; the handler is still an ordinary method."""

        def decorator(func):
            return func

        return decorator


from skill_musicassistant import catalog, feedback
from skill_musicassistant.catalog import ResolvedItem
from skill_musicassistant.parser import Kind, Lexicon, MediaRequest, parse
from skill_musicassistant.request import spoken_station_name, strip_leading_verb
from skill_musicassistant.resolve import Resolution, resolve
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
# Spoken lists stay short enough to follow by ear
MAX_SPOKEN_PLAYLIST_NAMES = 5
MAX_SPOKEN_TRACK_TITLES = 3
# Dead radio streams stall the server until the request times out; stop trying after this many
MAX_STATION_ATTEMPTS = 3
# Media types whose single item is a collection worth shuffling
SHUFFLED_TYPES = ("artist", "playlist")
# Errors that mean the server, not the skill, failed
SERVER_ERRORS = (requests.RequestException, MusicAssistantError)


def reports_failures(handler):
    """Last line of defence for an intent handler: nothing escapes unspoken.

    A server error is spoken as such, anything else as a failed request, and
    both are logged with their traceback. Returns True after speaking so a
    fallback handler counts as having answered.
    """

    @functools.wraps(handler)
    def wrapper(self, message: Message):
        try:
            return handler(self, message)
        except SERVER_ERRORS as e:
            self._handle_exception(e, f"{handler.__name__}: Music Assistant did not answer", "could_not_reach_server")
        except Exception as e:
            self._handle_exception(e, f"{handler.__name__} failed", "request_failed")
        return True

    return wrapper


class MusicAssistantSkill(_SkillBase):
    """OVOS/Neon skill for music assistant functionality."""

    def __init__(self, *args, bus=None, skill_id="", **kwargs):
        # defaults first, so stop() and shutdown() work even if initialize() fails
        self.session: Optional[requests.Session] = None
        self.mass_client: Optional[SimpleHTTPMusicAssistantClient] = None
        self.players: List[Player] = []
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
        except (OSError, ValueError) as e:
            self.log.warning("Could not read %s; writing the in-memory settings over it: %s", path, e)
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

    def _refresh_players(self) -> None:
        """Fetch the player list again; raises when the server does not answer."""
        self.players = self.mass_client.get_players()

    def _first_match(self, names: List[Optional[str]]) -> Optional[Player]:
        for name in names:
            player = self._match_player(name)
            if player:
                return player
        return None

    def _default_player_names(self, message: Optional[Message]) -> List[Optional[str]]:
        """What a command without a player means, most specific first."""
        last_used = self.last_player.get(SessionManager.get(message).session_id)
        return [last_used.name if last_used else None, self._session_default_player(message), self.default_player]

    def _find_player(self, location: Optional[str], message: Optional[Message]) -> Optional[Player]:
        """The player a request means, or None.

        1. The player named in the utterance; a name that matches nothing is
           never swapped for a default
        2. The player this session used most recently, so "skip" follows
           "play X on the office speaker"
        3. This session's default player, if one was set by voice
        4. The default_player setting

        The player list is fetched again once before giving up, which raises
        when the server does not answer.
        """
        names = [location] if location else self._default_player_names(message)
        player = self._first_match(names)
        if player is None and self.mass_client is not None:
            self._refresh_players()
            player = self._first_match(names)
        return player

    def _get_player_id(self, location=None, message: Optional[Message] = None) -> Optional[str]:
        """Player id for a request, remembered as the session's last used; None when nothing matched."""
        player = self._find_player(location, message)
        if player is None:
            return None
        self.last_player[SessionManager.get(message).session_id] = player
        self._last_used_player = player
        return player.player_id

    def _get_player(self, location=None, message: Optional[Message] = None, quiet: bool = False) -> str:
        """Player id for a request, or "" after saying why there is none.

        ``quiet`` is for the fallback handler, which declines without a word
        so another skill can answer. A server error propagates either way.
        """
        if not self.configured:
            if not quiet:
                self.speak_dialog("not_configured")
            return ""
        player_id = self._get_player_id(location, message)
        if not player_id:
            if not quiet:
                self._say_no_player(location)
            return ""
        player = self._last_used_player
        if player is not None and getattr(player, "available", True) is False:
            if not quiet:
                self.speak_dialog("player_unavailable", {"player": player.name})
            return ""
        return player_id

    def _say_no_player(self, location: Optional[str]) -> None:
        """Say that no player matched, naming the one asked for when there was one."""
        if location:
            self.speak_dialog("could_not_find_named_player", {"player": location})
            self.gui.show_text(f"Could not find a player called {location}.")
            return
        self.speak_dialog("could_not_find_player")
        self.gui.show_text("Could not find a player. Set a default player or name one.")

    def _handle_exception(self, e: Exception, what_failed: str, dialog: str, dialog_data: Optional[dict] = None):
        """Log a failure with its traceback, show it, and say the matching dialog."""
        self.log.exception("%s: %s", what_failed, e)
        self.gui.show_text(f"{what_failed}. Check the logs for more details.")
        self._say(dialog, dialog_data)

    def _load_volume_aliases(self):
        """Load locale-specific volume aliases."""
        cache_key = f"{self.lang}:volume_levels.value"
        if cache_key not in self.resources.static:
            aliases = {}
            try:
                values = self.resources.load_named_value_file("volume_levels").items()
            except FileNotFoundError:
                self.log.warning("No volume_levels.value for %s; spoken volume levels are disabled", self.lang)
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
                self.log.warning("No %s.list for %s; the phrasings it covers are disabled", name, self.lang)
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

    @intent_handler("pause.intent")
    @reports_failures
    def handle_pause(self, message: Message):
        """Pause, or resume when the request says so; never the play/pause toggle."""
        self.log.debug("Pause intent received:\n%s", message.data)
        resume = self.voc_match(message.data.get("utterance", ""), "resume", lang=self.lang)
        player_id = self._get_player(message.data.get("location"), message)
        if not player_id:
            return
        try:
            if resume:
                self.mass_client.send_command("player_queues/resume", queue_id=player_id)
                self.speak_dialog("resumed")
            else:
                self.mass_client.send_command("player_queues/pause", queue_id=player_id)
                self.speak_dialog("paused")
        except Exception as e:
            self._handle_exception(e, "Pause failed", "could_not_pause")

    @intent_handler("next.intent")
    @reports_failures
    def handle_next(self, message: Message):
        """Skip to the next track or station."""
        self.log.debug("Next intent received:\n%s", message.data)
        player_id = self._get_player(message.data.get("location"), message)
        if not player_id:
            return
        try:
            self.mass_client.queue_command_next(player_id)
        except Exception as e:
            self._handle_exception(e, "Next track failed", "could_not_next_track")
            return
        self.speak_dialog("next_track")

    @intent_handler("previous.intent")
    @reports_failures
    def handle_previous(self, message: Message):
        """Go back to the previous track."""
        self.log.debug("Previous intent received:\n%s", message.data)
        player_id = self._get_player(message.data.get("location"), message)
        if not player_id:
            return
        try:
            self.mass_client.queue_command_previous(player_id)
        except Exception as e:
            self._handle_exception(e, "Previous track failed", "could_not_previous_track")
            return
        self.speak_dialog("previous_track")

    @intent_handler("volume.intent")
    @reports_failures
    def handle_volume(self, message: Message):
        """Mute, unmute, step, or set the volume of a player."""
        self.log.debug("Volume intent received:\n%s", message.data)
        player_id = self._get_player(message.data.get("location"), message)
        if not player_id:
            return
        try:
            self._change_volume(player_id, self._get_volume_action(message), message.data.get("volume_level"))
        except Exception as e:
            self._handle_exception(e, "Volume change failed", "could_not_change_volume")

    def _change_volume(self, player_id: str, action: Optional[str], volume_level) -> None:
        """Send one volume command and say what was done."""
        if action == "unmute":
            self.mass_client.player_command_volume_mute(player_id, muted=False)
            self.speak_dialog("volume_unmuted")
            return
        if action == "mute":
            self.mass_client.player_command_volume_mute(player_id, muted=True)
            self.speak_dialog("volume_muted")
            return
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
        self.log.info("Setting volume to %s for player %s", volume, player_id)
        self.mass_client.player_command_volume_set(player_id, volume)
        self.speak_dialog("volume_set", {"volume": volume})

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

    def _current_media(self, message: Message):
        """(player_id, NowPlaying) for the requested or default player; speaks when nothing plays."""
        player_id = self._get_player(message.data.get("location"), message)
        if not player_id:
            return None, None
        now = catalog.now_playing_for(self.mass_client, player_id)
        if not now:
            self.speak_dialog("nothing_playing")
        return player_id, now

    @intent_handler("now_playing.intent")
    @reports_failures
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
    @reports_failures
    def handle_like(self, message: Message):
        """Add the current track to the Music Assistant favorites."""
        _, now = self._current_media(message)
        if not now:
            return
        if not now.uri:
            self.speak_dialog("could_not_like", {"title": now.title})
            return
        try:
            self.mass_client.add_favorite(now.uri)
        except Exception as e:
            self._handle_exception(e, "Could not add to favorites", "could_not_like", {"title": now.title})
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

    # Playing

    @property
    def lexicon(self) -> Lexicon:
        """Parser word lists for the current language, cached with the other resources."""
        cache_key = f"{self.lang}:lexicon"
        if cache_key not in self.resources.static:
            self.resources.static[cache_key] = Lexicon.from_loader(self._load_cached_list)
        return self.resources.static[cache_key]

    def _parse(self, utterance: str) -> MediaRequest:
        """Parse with this language's lexicon; a location only counts when it names a known player."""
        return parse(utterance, self.lexicon, is_player=lambda name: self._match_player(name) is not None)

    @intent_handler("play.intent")
    @reports_failures
    def handle_play(self, message: Message):
        """Any request that starts with a play verb: parse, resolve, play, speak."""
        request = self._parse(message.data.get("utterance") or message.data.get("query") or "")
        if request.is_empty:
            self.speak_dialog("could_not_play_music")
            return
        self._play_request(request, message, claimed=True)

    @fallback_handler(priority=GENERIC_PLAY_FALLBACK_PRIORITY)
    @reports_failures
    def handle_generic_play(self, message: Message) -> bool:
        """The same pipeline for a play-verb utterance no intent claimed.

        Runs in the medium fallback tier, after every registered intent and
        before the LLM fallbacks (85+). Declines without a word (False) when
        the request is not for this skill or nothing was found, so later
        fallbacks get their turn. A server error or a playback failure is
        spoken, because no other skill can fix it.
        """
        if not self.generic_play_fallback:
            return False
        utterance = message.data.get("utterance", "")
        if strip_leading_verb(utterance, self.lexicon.play_verbs) is None:
            return False
        request = self._parse(utterance)
        if request.is_empty:
            return False
        return self._play_request(request, message, claimed=False)

    def _play_request(self, request: MediaRequest, message: Message, claimed: bool) -> bool:
        """The one play pipeline: player, catalog, playback, feedback. True when the skill answered."""
        player_id = self._get_player(request.location or None, message, quiet=not claimed)
        if not player_id:
            return False
        found = resolve(self.mass_client, request)
        self.log.info("Request %s resolved to %s", request, found)
        if not found.found:
            if found.failed_lookups:
                self._say("could_not_reach_server")
                return True
            if claimed:
                self._say(*feedback.not_found(request))
            return False
        if not self._start_playback(found, request, player_id):
            self._say(*feedback.could_not_play(request))
            return True
        for dialog, data in feedback.playing(request, found):
            self._say(dialog, data)
        return True

    def _say(self, dialog: str, data: Optional[dict] = None) -> None:
        """speak_dialog without an empty data argument, which keeps the call shape tests expect."""
        if data:
            self.speak_dialog(dialog, data)
        else:
            self.speak_dialog(dialog)

    def _start_playback(self, found: Resolution, request: MediaRequest, player_id: str) -> bool:
        """Send the play command the resolution calls for.

        One item plays as is; artists and playlists are shuffled. A list of
        uris replaces the queue: inserting left a Hub queue at 2,600 items
        after an hour. Radio categories start with one station and append the
        rest in the background (see _enqueue_rest).
        """
        try:
            if found.item is not None:
                self._play_item(found.item, request, player_id)
            elif found.kind is Kind.RADIO_CATEGORY:
                return self._play_first_station(list(found.uris), player_id)
            else:
                self.mass_client.play_media(
                    queue_id=player_id, media=list(found.uris), option=QueueOption.REPLACE, shuffle=True
                )
            return True
        except Exception as e:
            self.log.exception("Play media error: %s", e)
            return False

    def _play_first_station(self, uris: List[str], player_id: str) -> bool:
        """Start the first station that plays, then append the rest in the background.

        A dead stream makes the server hang on play_media until the request
        times out, so the next station is tried instead of giving up on the
        whole category.
        """
        for index, uri in enumerate(uris[:MAX_STATION_ATTEMPTS]):
            try:
                self.mass_client.play_media(queue_id=player_id, media=uri, option=QueueOption.REPLACE)
            except Exception as e:
                self.log.warning("Station %s did not start, trying the next one: %s", uri, e)
                continue
            self._enqueue_rest(uris[index + 1 :], player_id)
            return True
        return False

    def _play_item(self, item: ResolvedItem, request: MediaRequest, player_id: str) -> None:
        kwargs = {
            "queue_id": player_id,
            "media": item.uri,
            "option": QueueOption.PLAY,
            "radio_mode": request.radio_mode,
        }
        if request.shuffle or item.media_type in SHUFFLED_TYPES:
            kwargs["shuffle"] = True
        self.mass_client.play_media(**kwargs)

    @intent_handler("shuffle.intent")
    @reports_failures
    def handle_shuffle(self, message: Message):
        """Turn queue shuffle on or off."""
        enabled = not self.voc_match(message.data.get("utterance", ""), "shuffle_off", lang=self.lang)
        player_id = self._get_player(message.data.get("location"), message)
        if not player_id:
            return
        try:
            self.mass_client.queue_set_shuffle(player_id, enabled)
        except Exception as e:
            self._handle_exception(e, "Could not change shuffle", "could_not_change_queue_mode")
            return
        self.speak_dialog("shuffle_on" if enabled else "shuffle_off")

    @intent_handler("repeat.intent")
    @reports_failures
    def handle_repeat(self, message: Message):
        """Set the queue repeat mode from the words used: off, all, or this track."""
        mode = self._repeat_mode(message.data.get("utterance", ""))
        player_id = self._get_player(message.data.get("location"), message)
        if not player_id:
            return
        try:
            self.mass_client.queue_set_repeat(player_id, mode)
        except Exception as e:
            self._handle_exception(e, "Could not change repeat", "could_not_change_queue_mode")
            return
        self.speak_dialog(f"repeat_{mode.value}")

    def _repeat_mode(self, utterance: str) -> RepeatMode:
        if self.voc_match(utterance, "repeat_off", lang=self.lang):
            return RepeatMode.OFF
        if self.voc_match(utterance, "repeat_all", lang=self.lang):
            return RepeatMode.ALL
        return RepeatMode.ONE

    def _enqueue_rest(self, uris: List[str], player_id: str) -> Optional[threading.Thread]:
        """Add the remaining stations after the first one is already playing.

        Music Assistant resolves every radio-browser uri before a multi-item
        play starts, which took longer than the request timeout on a real
        server, so the rest is appended in the background.
        """
        if not uris:
            return None

        def add():
            try:
                self.mass_client.play_media(queue_id=player_id, media=uris, option=QueueOption.ADD)
            except Exception as e:
                self.log.warning("Could not add the remaining stations: %s", e)

        thread = threading.Thread(target=add, name="musicassistant-enqueue", daemon=True)
        thread.start()
        return thread

    # Playlists by voice
    def _spoken_playlist_name(self, message: Message) -> str:
        """The playlist slot as spoken, stripped."""
        return (message.data.get("playlist") or "").strip()

    def _playlist_from(self, message: Message) -> Optional[catalog.PlaylistRef]:
        """The library playlist the utterance names, speaking when there is none."""
        name = self._spoken_playlist_name(message)
        playlist = catalog.find_playlist(self.mass_client, name)
        if not playlist:
            self.speak_dialog("could_not_find_playlist", {"playlist": name})
        return playlist

    @intent_handler("create_playlist.intent")
    @reports_failures
    def handle_create_playlist(self, message: Message):
        """Create an empty library playlist by name."""
        name = self._spoken_playlist_name(message)
        if catalog.find_playlist(self.mass_client, name):
            self.speak_dialog("playlist_exists", {"playlist": name})
            return
        try:
            created = catalog.create_playlist(self.mass_client, name)
        except Exception as e:
            self._handle_exception(e, "Could not create the playlist", "could_not_change_playlist", {"playlist": name})
            return
        self.speak_dialog("playlist_created", {"playlist": created.name})

    @intent_handler("add_to_playlist.intent")
    @reports_failures
    def handle_add_to_playlist(self, message: Message):
        """Append the current track; the playlist is created on first use, as in minimy."""
        _, now = self._current_media(message)
        if not now:
            return
        name = self._spoken_playlist_name(message)
        if not now.uri:
            self.speak_dialog("could_not_change_playlist", {"playlist": name})
            return
        try:
            playlist = catalog.find_playlist(self.mass_client, name) or catalog.create_playlist(self.mass_client, name)
            self.mass_client.add_playlist_tracks(playlist.item_id, [now.uri])
        except Exception as e:
            self._handle_exception(e, "Could not add to the playlist", "could_not_change_playlist", {"playlist": name})
            return
        self.speak_dialog("added_to_playlist", {"title": now.title, "playlist": playlist.name})

    @intent_handler("remove_from_playlist.intent")
    @reports_failures
    def handle_remove_from_playlist(self, message: Message):
        """Remove the current track from a playlist, by uri first, then by title and artist."""
        _, now = self._current_media(message)
        if not now:
            return
        playlist = self._playlist_from(message)
        if not playlist:
            return
        positions = catalog.positions_of(self.mass_client, playlist, now)
        if not positions:
            self.speak_dialog("not_in_playlist", {"title": now.title, "playlist": playlist.name})
            return
        try:
            self.mass_client.remove_playlist_tracks(playlist.item_id, positions)
        except Exception as e:
            self._handle_exception(
                e, "Could not remove from the playlist", "could_not_change_playlist", {"playlist": playlist.name}
            )
            return
        self.speak_dialog("removed_from_playlist", {"title": now.title, "playlist": playlist.name})

    @intent_handler("save_queue.intent")
    @reports_failures
    def handle_save_queue(self, message: Message):
        """Save the current queue as a new library playlist."""
        name = self._spoken_playlist_name(message)
        player_id = self._get_player(message.data.get("location"), message)
        if not player_id:
            return
        try:
            self.mass_client.save_queue_as_playlist(player_id, name)
        except Exception as e:
            self._handle_exception(e, "Could not save the queue", "could_not_change_playlist", {"playlist": name})
            return
        self.speak_dialog("queue_saved", {"playlist": name})

    @intent_handler("list_playlists.intent")
    @reports_failures
    def handle_list_playlists(self, message: Message):  # pylint: disable=unused-argument
        """Say how many playlists there are and name the first few."""
        playlists = catalog.list_playlists(self.mass_client)
        if not playlists:
            self.speak_dialog("no_playlists")
            return
        names = ", ".join(p.name for p in playlists[:MAX_SPOKEN_PLAYLIST_NAMES])
        self.speak_dialog("playlists_list", {"count": len(playlists), "names": names})

    @intent_handler("playlist_contents.intent")
    @reports_failures
    def handle_playlist_contents(self, message: Message):
        """Say how many tracks a playlist holds and name the first few."""
        playlist = self._playlist_from(message)
        if not playlist:
            return
        titles = catalog.playlist_track_titles(self.mass_client, playlist)
        if not titles:
            self.speak_dialog("playlist_empty", {"playlist": playlist.name})
            return
        first = ", ".join(titles[:MAX_SPOKEN_TRACK_TITLES])
        self.speak_dialog("playlist_contents", {"playlist": playlist.name, "count": len(titles), "titles": first})

    @intent_handler("set_default_player.intent")
    @reports_failures
    def handle_set_default_player(self, message: Message):
        """Set the default player for this session, or for the device when it is the local session."""
        spoken_name = (message.data.get("player") or "").strip()
        player = self._find_player(spoken_name, message) if spoken_name else None
        if not player:
            self._say_no_player(spoken_name)
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
                return catalog.playback_state(current)
        return ""

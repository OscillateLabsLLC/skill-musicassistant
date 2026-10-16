"""Integration tests for the MusicAssistantSkill class."""

from typing import cast
from unittest.mock import Mock, PropertyMock, patch

import pytest
from ma_http_client import SimpleHTTPMusicAssistantClient
from music_assistant_models.enums import MediaType
from ovos_bus_client import Message, MessageBusClient
from ovos_bus_client.session import Session
from ovos_utils.fakebus import FakeBus

from skill_musicassistant import MusicAssistantSkill


def _make_player(name, player_id):
    player = Mock()
    player.name = name
    player.player_id = player_id
    return player


def _message_with_session(session_id, data=None):
    return Message("test", data or {}, {"session": Session(session_id).serialize()})


class TestMusicAssistantSkillIntegration:
    """Integration tests for the main skill class using mocked client."""

    @pytest.fixture
    def mock_client(self):
        """Mock the SimpleHTTPMusicAssistantClient."""
        return Mock(spec=SimpleHTTPMusicAssistantClient)

    @pytest.fixture
    def skill(self):
        """Create a clean skill instance."""
        # Patch the SimpleHTTPMusicAssistantClient to prevent real HTTP calls during testing
        with patch("skill_musicassistant.SimpleHTTPMusicAssistantClient") as mock_client_class:
            # Create a mock instance that will be returned by the constructor
            mock_client_instance = Mock(spec=SimpleHTTPMusicAssistantClient)
            mock_client_instance.get_players.return_value = []
            mock_client_class.return_value = mock_client_instance

            skill = MusicAssistantSkill(bus=cast(MessageBusClient, FakeBus()), skill_id="test-skill")
        return skill

    @pytest.fixture
    def skill_with_mock_client(self, skill, mock_client):
        """Create skill instance with mocked client."""
        # Replace the auto-created mock client with our specific mock
        skill.mass_client = mock_client
        return skill

    def test_skill_initialization(self, skill):
        """Test that skill initializes properly."""
        assert skill is not None
        assert hasattr(skill, "music_assistant_url")
        assert hasattr(skill, "default_player")
        assert hasattr(skill, "session")
        assert hasattr(skill, "mass_client")
        assert hasattr(skill, "players")
        assert hasattr(skill, "last_player")

    def test_get_player_id_no_players(self, skill_with_mock_client, mock_client):
        """Test behavior when no players are available."""
        mock_client.get_players.return_value = []

        # Mock default_player to return None so we test the no-players case
        with patch.object(type(skill_with_mock_client), "default_player", new_callable=lambda: None):
            player_id = skill_with_mock_client._get_player_id("Any")
            assert player_id is None

    def test_get_player_id_client_error(self, skill_with_mock_client, mock_client):
        """Test behavior when client throws an error."""
        mock_client.get_players.side_effect = Exception("Connection error")

        player_id = skill_with_mock_client._get_player_id("Any")
        assert player_id is None

    def test_search_media_artist(self, skill_with_mock_client, mock_client):
        """Test media search for artists."""
        # Mock search response
        mock_client.search_media.return_value = {"artists": [{"name": "Test Artist", "uri": "test://artist/1"}]}

        with patch("music_assistant_models.media_items.Artist") as mock_artist_class:
            mock_artist = Mock(name="Test Artist")
            mock_artist_class.from_dict.return_value = mock_artist

            result = skill_with_mock_client._search_media("Test Artist", MediaType.ARTIST)

            # Verify the client was called correctly
            mock_client.search_media.assert_called_once_with(
                query="Test Artist", media_types=[MediaType.ARTIST], limit=5
            )
            assert result == mock_artist

    def test_search_media_track_with_artist(self, skill_with_mock_client, mock_client):
        """Test media search for tracks with artist filtering."""
        # Mock search response
        mock_client.search_media.return_value = {
            "tracks": [
                {"name": "Test Song", "artist": {"name": "Test Artist"}},
                {"name": "Other Song", "artist": {"name": "Other Artist"}},
            ]
        }

        with patch("music_assistant_models.media_items.Track") as mock_track_class:
            mock_track = Mock()
            mock_track.artist = Mock(name="Test Artist")
            mock_track_class.from_dict.return_value = mock_track

            skill_with_mock_client._search_media("Test Song", MediaType.TRACK, artist="Test")

            # Should filter by artist name
            mock_client.search_media.assert_called_once_with(query="Test Song", media_types=[MediaType.TRACK], limit=5)

    def test_search_media_no_results(self, skill_with_mock_client, mock_client):
        """Test media search with no results."""
        mock_client.search_media.return_value = {"artists": []}

        result = skill_with_mock_client._search_media("Nonexistent", MediaType.ARTIST)
        assert result is None

    def test_play_media_item_success(self, skill_with_mock_client, mock_client):
        """Test successful media playback."""
        mock_media = Mock(uri="test://uri")
        mock_client.play_media.return_value = True

        result = skill_with_mock_client._play_media_item(mock_media, "test-player", radio_mode=True)

        assert result is True
        mock_client.play_media.assert_called_once()

    def test_play_media_item_no_client(self, skill):
        """Test media playback with no client."""
        mock_media = Mock(uri="test://uri")
        skill.mass_client = None

        result = skill._play_media_item(mock_media, "test-player")
        assert result is False

    def test_play_media_item_error(self, skill_with_mock_client, mock_client):
        """Test media playback with error."""
        mock_media = Mock(uri="test://uri")
        mock_client.play_media.side_effect = Exception("Playback error")

        result = skill_with_mock_client._play_media_item(mock_media, "test-player")
        assert result is False

    def test_parse_volume_level_numeric(self, skill):
        """Test volume level parsing with numeric input."""
        assert skill._parse_volume_level("50") == 50
        assert skill._parse_volume_level("0") == 0
        assert skill._parse_volume_level("100") == 100
        assert skill._parse_volume_level("150") == 100  # Should cap at 100

    def test_parse_volume_level_words(self, skill):
        """Test volume level parsing with word input."""
        with patch.object(
            skill,
            "_load_volume_aliases",
            return_value={"mute": 0, "half": 50, "max": 100, "loud": 75},
        ):
            assert skill._parse_volume_level("mute") == 0
            assert skill._parse_volume_level("half") == 50
            assert skill._parse_volume_level("max") == 100
            assert skill._parse_volume_level("loud") == 75

    def test_parse_volume_level_percent(self, skill):
        """Test volume level parsing with percent notation."""
        with patch.object(skill, "_load_cached_list", return_value=["percent"]):
            assert skill._parse_volume_level("75%") == 75
            assert skill._parse_volume_level("25 percent") == 25

    def test_parse_volume_level_french(self, skill):
        """Test volume parsing with French words."""
        with (
            patch.object(type(skill), "lang", new_callable=PropertyMock, return_value="fr-fr"),
            patch.object(
                skill,
                "_load_volume_aliases",
                return_value={"moitié": 50, "plus fort": "up", "moins fort": "down"},
            ),
            patch.object(skill, "_load_cached_list", return_value=["pour cent"]),
        ):
            assert skill._parse_volume_level("trente") == 30
            assert skill._parse_volume_level("trente pour cent") == 30
            assert skill._parse_volume_level("moitié") == 50
            assert skill._parse_volume_level("plus fort") == "up"
            assert skill._parse_volume_level("moins fort") == "down"

    def test_parse_volume_level_invalid(self, skill):
        """Test volume level parsing with invalid input."""
        assert skill._parse_volume_level("invalid") is None
        assert skill._parse_volume_level("") is None
        assert skill._parse_volume_level(None) is None


class TestSkillMessageHandlers:
    """Test the skill's message handlers with mocked components."""

    @pytest.fixture
    def skill_with_mocks(self):
        """Create skill with all necessary mocks."""
        # Patch the SimpleHTTPMusicAssistantClient to prevent real HTTP calls during testing
        with patch("skill_musicassistant.SimpleHTTPMusicAssistantClient") as mock_client_class:
            # Create a mock instance that will be returned by the constructor
            mock_client_instance = Mock(spec=SimpleHTTPMusicAssistantClient)
            mock_client_instance.get_players.return_value = []
            mock_client_class.return_value = mock_client_instance

            skill = MusicAssistantSkill(bus=cast(MessageBusClient, FakeBus()), skill_id="test-skill")

        # Override with our own mock for more control
        skill.mass_client = Mock(spec=SimpleHTTPMusicAssistantClient)
        skill.speak = Mock()
        skill.speak_dialog = Mock()
        skill.log = Mock()
        return skill

    def test_handle_pause_success(self, skill_with_mocks):
        """Test successful pause handling."""
        mock_message = Mock()
        mock_message.data = {}

        # Mock successful player ID resolution
        with patch.object(skill_with_mocks, "_get_player_id", return_value="test-player"):
            skill_with_mocks.handle_pause(mock_message)

            skill_with_mocks.mass_client.queue_command_pause.assert_called_once_with("test-player")
            skill_with_mocks.speak_dialog.assert_called_once_with("paused")

    def test_handle_pause_no_player(self, skill_with_mocks):
        """Test pause handling with no player found."""
        mock_message = Mock()
        mock_message.data = {}

        with patch.object(skill_with_mocks, "_get_player_id", return_value=None):
            skill_with_mocks.handle_pause(mock_message)

            skill_with_mocks.speak_dialog.assert_called_once_with("could_not_find_player")

    def test_handle_next_success(self, skill_with_mocks):
        """Test successful next track handling."""
        mock_message = Mock()
        mock_message.data = {}

        with patch.object(skill_with_mocks, "_get_player_id", return_value="test-player"):
            skill_with_mocks.handle_next(mock_message)

            skill_with_mocks.mass_client.queue_command_next.assert_called_once_with("test-player")
            skill_with_mocks.speak_dialog.assert_called_once_with("next_track")

    def test_handle_previous_success(self, skill_with_mocks):
        """Test successful previous track handling."""
        mock_message = Mock()
        mock_message.data = {}

        with patch.object(skill_with_mocks, "_get_player_id", return_value="test-player"):
            skill_with_mocks.handle_previous(mock_message)

            skill_with_mocks.mass_client.queue_command_previous.assert_called_once_with("test-player")
            skill_with_mocks.speak_dialog.assert_called_once_with("previous_track")

    def test_handle_volume_mute_with_localized_utterance(self, skill_with_mocks):
        """Test mute handling via localized utterance matching."""
        mock_message = Mock()
        mock_message.data = {"utterance": "avec music assistant coupe le son"}

        with (
            patch.object(type(skill_with_mocks), "lang", new_callable=PropertyMock, return_value="fr-fr"),
            patch.object(skill_with_mocks, "_get_player", return_value="test-player"),
            patch.object(
                skill_with_mocks,
                "voc_match",
                side_effect=lambda utt, voc_filename, lang=None: voc_filename == "mute",
            ),
        ):
            skill_with_mocks.handle_volume(mock_message)

        skill_with_mocks.mass_client.player_command_volume_mute.assert_called_once_with("test-player", muted=True)
        skill_with_mocks.speak_dialog.assert_called_once_with("volume_muted")


class TestPlayerResolution:
    """Tests for fuzzy player matching and session-aware default players."""

    @pytest.fixture
    def skill(self):
        """Create a skill with a cached set of players and mocked speech/GUI."""
        with patch("skill_musicassistant.SimpleHTTPMusicAssistantClient") as mock_client_class:
            mock_client_instance = Mock(spec=SimpleHTTPMusicAssistantClient)
            mock_client_instance.get_players.return_value = []
            mock_client_class.return_value = mock_client_instance

            skill = MusicAssistantSkill(bus=cast(MessageBusClient, FakeBus()), skill_id="test-skill")

        skill.mass_client = Mock(spec=SimpleHTTPMusicAssistantClient)
        skill.speak_dialog = Mock()
        skill.gui = Mock()
        skill.settings.pop("default_player", None)
        skill.players = [
            _make_player("Living Room Speaker", "lr-1"),
            _make_player("Office Speaker", "office-1"),
            _make_player("Kitchen Display", "kitchen-1"),
        ]
        return skill

    def test_match_player_case_insensitive(self, skill):
        assert skill._match_player("living room speaker").player_id == "lr-1"

    def test_match_player_prefers_exact_name_over_suffixed_sibling(self, skill):
        """Music Assistant often exposes "X speaker+" next to "X speaker"; both normalize the same."""
        skill.players = [
            _make_player("Office speaker+", "office-plus"),
            _make_player("Office speaker", "office-1"),
        ]
        assert skill._match_player("office speaker").player_id == "office-1"
        assert skill._match_player("Office Speaker").player_id == "office-1"

    def test_match_player_tolerates_stt_noise(self, skill):
        assert skill._match_player("livingroom speaker").player_id == "lr-1"
        assert skill._match_player("the office").player_id == "office-1"

    def test_match_player_no_close_match(self, skill):
        assert skill._match_player("garage") is None
        assert skill._match_player(None) is None
        assert skill._match_player("") is None

    def test_get_player_id_fuzzy_location(self, skill):
        assert skill._get_player_id("livingroom speaker") == "lr-1"

    def test_get_player_id_uses_session_default(self, skill):
        skill.session_default_players["work-laptop"] = "Office Speaker"
        message = _message_with_session("work-laptop")

        assert skill._get_player_id(None, message) == "office-1"

    def test_get_player_id_falls_back_to_global_default(self, skill):
        skill.settings["default_player"] = "Kitchen Display"
        message = _message_with_session("work-laptop")

        assert skill._get_player_id(None, message) == "kitchen-1"

    def test_get_player_id_location_beats_session_default(self, skill):
        skill.session_default_players["work-laptop"] = "Office Speaker"
        message = _message_with_session("work-laptop")

        assert skill._get_player_id("kitchen display", message) == "kitchen-1"

    def test_get_player_id_tracks_last_player_per_session(self, skill):
        skill._get_player_id("Office Speaker", _message_with_session("client-a"))
        skill._get_player_id("Kitchen Display", _message_with_session("client-b"))

        assert skill.last_player["client-a"].player_id == "office-1"
        assert skill.last_player["client-b"].player_id == "kitchen-1"


class TestSetDefaultPlayer:
    """Tests for the set_default_player intent handler."""

    @pytest.fixture
    def skill(self):
        """Create a skill with a cached set of players and mocked speech/GUI."""
        with patch("skill_musicassistant.SimpleHTTPMusicAssistantClient") as mock_client_class:
            mock_client_instance = Mock(spec=SimpleHTTPMusicAssistantClient)
            mock_client_instance.get_players.return_value = []
            mock_client_class.return_value = mock_client_instance

            skill = MusicAssistantSkill(bus=cast(MessageBusClient, FakeBus()), skill_id="test-skill")

        skill.mass_client = Mock(spec=SimpleHTTPMusicAssistantClient)
        skill.speak_dialog = Mock()
        skill.gui = Mock()
        skill.settings.pop("default_player", None)
        skill.players = [
            _make_player("Living Room Speaker", "lr-1"),
            _make_player("Office Speaker", "office-1"),
        ]
        return skill

    def test_local_session_persists_to_settings(self, skill):
        message = Message("set_default_player.intent", {"player": "living room speaker"})

        with patch.object(skill.settings, "store") as mock_store:
            skill.handle_set_default_player(message)

        assert skill.settings["default_player"] == "Living Room Speaker"
        mock_store.assert_called_once()
        skill.speak_dialog.assert_called_once_with("default_player_set", {"player": "Living Room Speaker"})

    def test_hivemind_session_stays_in_memory(self, skill):
        message = _message_with_session("work-laptop", {"player": "office speaker"})

        skill.handle_set_default_player(message)

        assert skill.session_default_players["work-laptop"] == "Office Speaker"
        assert skill.settings.get("default_player") is None
        skill.speak_dialog.assert_called_once_with("default_player_set", {"player": "Office Speaker"})

    def test_refreshes_player_cache_on_miss(self, skill):
        skill.players = []
        skill.mass_client.get_players.return_value = [_make_player("Office Speaker", "office-1")]
        message = _message_with_session("work-laptop", {"player": "office speaker"})

        skill.handle_set_default_player(message)

        skill.mass_client.get_players.assert_called_once()
        assert skill.session_default_players["work-laptop"] == "Office Speaker"

    def test_no_match_speaks_failure(self, skill):
        skill.mass_client.get_players.return_value = skill.players
        message = Message("set_default_player.intent", {"player": "garage"})

        skill.handle_set_default_player(message)

        skill.speak_dialog.assert_called_once_with("could_not_find_player")
        assert skill.settings.get("default_player") is None


def _media(title, artist="Daft Punk", album="Discovery", uri="library://track/7"):
    media = Mock()
    media.title = title
    media.artist = artist
    media.album = album
    media.uri = uri
    return media


def _skill_with_player(player_id="lr-1", name="Living Room Speaker", current_media=None):
    with patch("skill_musicassistant.SimpleHTTPMusicAssistantClient") as mock_client_class:
        mock_client_class.return_value = Mock(spec=SimpleHTTPMusicAssistantClient, **{"get_players.return_value": []})
        skill = MusicAssistantSkill(bus=cast(MessageBusClient, FakeBus()), skill_id="test-skill")
    player = _make_player(name, player_id)
    player.current_media = current_media
    skill.mass_client = Mock(spec=SimpleHTTPMusicAssistantClient)
    skill.mass_client.get_players.return_value = [player]
    skill.players = [player]
    skill.settings["default_player"] = name
    # settings persist to disk per skill_id, so an earlier test's override would leak into this one
    skill.settings.pop("generic_play_fallback", None)
    skill.speak_dialog = Mock()
    skill.gui = Mock()
    return skill


class TestNowPlayingAndLike:
    def test_now_playing_speaks_title_and_artist(self):
        skill = _skill_with_player(current_media=_media("One More Time"))

        skill.handle_now_playing(Message("now_playing.intent", {}))

        skill.speak_dialog.assert_called_once_with("now_playing", {"title": "One More Time", "artist": "Daft Punk"})

    def test_now_playing_with_blank_title_falls_back(self):
        skill = _skill_with_player(current_media=_media("  ", album=None))

        skill.handle_now_playing(Message("now_playing.intent", {}))

        skill.speak_dialog.assert_called_once_with(
            "now_playing", {"title": "an untitled track", "artist": "Daft Punk"}
        )

    def test_now_playing_when_idle(self):
        skill = _skill_with_player(current_media=None)

        skill.handle_now_playing(Message("now_playing.intent", {}))

        skill.speak_dialog.assert_called_once_with("nothing_playing")

    def test_like_adds_current_uri_to_favorites(self):
        skill = _skill_with_player(current_media=_media("One More Time"))

        skill.handle_like(Message("like.intent", {}))

        skill.mass_client.add_favorite.assert_called_once_with("library://track/7")
        skill.speak_dialog.assert_called_once_with("liked", {"title": "One More Time"})

    def test_like_when_idle_does_not_call_server(self):
        skill = _skill_with_player(current_media=None)

        skill.handle_like(Message("like.intent", {}))

        skill.mass_client.add_favorite.assert_not_called()
        skill.speak_dialog.assert_called_once_with("nothing_playing")


class TestGenericPlayFallback:
    def _utterance(self, text):
        return Message("ovos.skills.fallback", {"utterance": text, "lang": "en-us"})

    def test_declines_without_play_verb(self):
        skill = _skill_with_player()

        assert skill.handle_generic_play(self._utterance("what time is it")) is False
        skill.mass_client.get_item_by_name.assert_not_called()

    def test_declines_when_nothing_resolves(self):
        skill = _skill_with_player()
        skill.mass_client.get_item_by_name.return_value = None

        assert skill.handle_generic_play(self._utterance("play the news")) is False
        skill.mass_client.play_media.assert_not_called()

    def test_declines_when_setting_is_off(self):
        skill = _skill_with_player()
        skill.settings["generic_play_fallback"] = False

        assert skill.handle_generic_play(self._utterance("play discovery")) is False
        skill.mass_client.get_item_by_name.assert_not_called()

    def test_plays_resolved_album_and_speaks_its_type(self):
        skill = _skill_with_player()
        skill.mass_client.get_item_by_name.return_value = {
            "name": "Discovery",
            "uri": "library://album/3",
            "media_type": "album",
            "artists": [{"name": "Daft Punk"}],
        }

        assert skill.handle_generic_play(self._utterance("play discovery")) is True

        skill.mass_client.get_item_by_name.assert_called_once_with("discovery")
        kwargs = skill.mass_client.play_media.call_args.kwargs
        assert kwargs["media"] == "library://album/3"
        assert "shuffle" not in kwargs
        skill.speak_dialog.assert_called_once_with("playing_album", {"album": "Discovery", "artist": "Daft Punk"})

    def test_confident_artist_search_hit_beats_server_pick(self):
        skill = _skill_with_player()
        skill.mass_client.search_media.return_value = {
            "artists": [{"name": "The Beatles", "uri": "library://artist/119"}],
            "tracks": [{"name": "Across the Universe", "uri": "library://track/1884"}],
        }

        assert skill.handle_generic_play(self._utterance("play beatles")) is True

        skill.mass_client.get_item_by_name.assert_not_called()
        kwargs = skill.mass_client.play_media.call_args.kwargs
        assert kwargs["media"] == "library://artist/119"
        assert kwargs["shuffle"] is True
        skill.speak_dialog.assert_called_once_with("playing", {"track_name": "music", "artist_name": "The Beatles"})

    def test_weak_search_hits_defer_to_server_by_name(self):
        skill = _skill_with_player()
        skill.mass_client.search_media.return_value = {
            "artists": [{"name": "Red Hot Chili Peppers", "uri": "library://artist/5"}],
        }
        skill.mass_client.get_item_by_name.return_value = None

        assert skill.handle_generic_play(self._utterance("play red knight")) is False
        skill.mass_client.get_item_by_name.assert_called_once_with("red knight")

    def test_artist_is_shuffled(self):
        skill = _skill_with_player()
        skill.mass_client.get_item_by_name.return_value = {
            "name": "Daft Punk",
            "uri": "library://artist/1",
            "media_type": "artist",
        }

        skill.handle_generic_play(self._utterance("listen to daft punk"))

        assert skill.mass_client.play_media.call_args.kwargs["shuffle"] is True
        skill.speak_dialog.assert_called_once_with("playing", {"track_name": "music", "artist_name": "Daft Punk"})

    def test_trailing_location_selects_player(self):
        skill = _skill_with_player(player_id="office-1", name="Office Speaker")
        skill.mass_client.get_item_by_name.return_value = {
            "name": "Discovery",
            "uri": "library://album/3",
            "media_type": "album",
        }

        skill.handle_generic_play(self._utterance("play discovery on the office speaker"))

        skill.mass_client.get_item_by_name.assert_called_once_with("discovery")
        assert skill.mass_client.play_media.call_args.kwargs["queue_id"] == "office-1"

    def test_server_error_declines_instead_of_raising(self):
        skill = _skill_with_player()
        skill.mass_client.get_item_by_name.side_effect = Exception("unknown command")

        assert skill.handle_generic_play(self._utterance("play discovery")) is False

    def test_can_answer_accepts_both_workshop_signatures(self):
        skill = _skill_with_player()

        assert skill.can_answer(["play discovery"], "en-us") is True
        assert skill.can_answer(["what time is it"], "en-us") is False
        assert skill.can_answer(Message("fallback", {"utterances": ["listen to daft punk"]})) is True
        assert skill.can_answer(Message("fallback", {"utterances": ["who are you"]})) is False

    def test_can_answer_respects_setting(self):
        skill = _skill_with_player()
        skill.settings["generic_play_fallback"] = False

        assert skill.can_answer(["play discovery"], "en-us") is False


class TestSpokenDisambiguation:
    def test_track_by_name_announces_different_artist(self):
        skill = _skill_with_player()
        skill.mass_client.get_track_by_name.return_value = {
            "name": "Hallelujah",
            "uri": "library://track/9",
            "media_type": "track",
            "artists": [{"name": "Jeff Buckley"}],
        }

        skill.handle_play_track(Message("play_track.intent", {"track": "hallelujah", "artist": "leonard cohen"}))

        skill.mass_client.get_track_by_name.assert_called_once_with("hallelujah", artist_name="leonard cohen")
        assert skill.speak_dialog.call_args_list[0].args == (
            "playing_different_artist",
            {"requested": "leonard cohen", "actual": "Jeff Buckley"},
        )
        assert skill.speak_dialog.call_args_list[1].args[0] == "playing"

    def test_track_missing_for_that_artist_plays_the_version_we_have(self):
        skill = _skill_with_player()
        other_version = {
            "name": "Hallelujah",
            "uri": "library://track/16625",
            "media_type": "track",
            "artists": [{"name": "Jeff Buckley"}],
        }
        skill.mass_client.get_track_by_name.side_effect = lambda name, artist_name=None, album_name=None: (
            None if artist_name else other_version
        )
        skill.mass_client.search_media.return_value = {"tracks": []}

        skill.handle_play_track(Message("play_track.intent", {"track": "hallelujah", "artist": "leonard cohen"}))

        assert skill.mass_client.play_media.call_args.kwargs["media"] == "library://track/16625"
        assert skill.speak_dialog.call_args_list[0].args == (
            "playing_different_artist",
            {"requested": "leonard cohen", "actual": "Jeff Buckley"},
        )

    def test_track_same_artist_is_silent_about_it(self):
        skill = _skill_with_player()
        skill.mass_client.get_track_by_name.return_value = {
            "name": "Hallelujah",
            "uri": "library://track/9",
            "media_type": "track",
            "artists": [{"name": "Leonard Cohen"}],
        }

        skill.handle_play_track(Message("play_track.intent", {"track": "hallelujah", "artist": "leonard cohen"}))

        assert skill.speak_dialog.call_count == 1
        assert skill.speak_dialog.call_args.args[0] == "playing"

    def test_album_falls_back_to_search_and_counts_matches(self):
        skill = _skill_with_player()
        skill.mass_client.get_item_by_name.return_value = None
        skill.mass_client.search_media.return_value = {
            "albums": [
                {"name": "Greatest Hits", "uri": "library://album/1", "artists": [{"name": "Queen"}]},
                {"name": "Greatest Hits", "uri": "library://album/2", "artists": [{"name": "ABBA"}]},
            ]
        }

        skill.handle_play_album(Message("play_album.intent", {"album": "greatest hits"}))

        assert skill.speak_dialog.call_args_list[0].args == (
            "found_several_albums",
            {"count": 2, "album": "greatest hits"},
        )
        assert skill.mass_client.play_media.call_args.kwargs["media"] == "library://album/1"

    def test_album_search_prefers_requested_artist(self):
        skill = _skill_with_player()
        skill.mass_client.get_item_by_name.return_value = None
        skill.mass_client.search_media.return_value = {
            "albums": [
                {"name": "Greatest Hits", "uri": "library://album/1", "artists": [{"name": "Queen"}]},
                {"name": "Greatest Hits", "uri": "library://album/2", "artists": [{"name": "ABBA"}]},
            ]
        }

        skill.handle_play_album(Message("play_album.intent", {"album": "greatest hits", "artist": "abba"}))

        assert skill.mass_client.play_media.call_args.kwargs["media"] == "library://album/2"
        assert skill.speak_dialog.call_count == 1


class TestStop:
    def test_stop_pauses_last_used_player(self):
        skill = _skill_with_player()
        skill.players.append(_make_player("Office Speaker", "office-1"))
        skill.last_player["default"] = skill.players[1]

        assert skill.stop() is True
        skill.mass_client.queue_command_pause.assert_called_once_with("office-1")

    def test_stop_falls_back_to_default_player(self):
        skill = _skill_with_player()

        assert skill.stop() is True
        skill.mass_client.queue_command_pause.assert_called_once_with("lr-1")

    def test_stop_with_no_players_returns_false(self):
        skill = _skill_with_player()
        skill.players = []
        skill.settings.pop("default_player", None)
        skill.mass_client.get_players.return_value = []

        assert skill.stop() is False


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])

"""Integration tests for the MusicAssistantSkill class."""

import json
import threading
from typing import cast
from unittest.mock import Mock, PropertyMock, patch

import pytest
from ma_http_client import SimpleHTTPMusicAssistantClient
from music_assistant_models.enums import MediaType, QueueOption
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
        skill.settings["music_assistant_url"] = "http://ma:8095"
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

            skill_with_mocks.mass_client.send_command.assert_called_once_with(
                "player_queues/pause", queue_id="test-player"
            )
            skill_with_mocks.speak_dialog.assert_called_once_with("paused")

    def test_handle_resume_uses_resume_not_the_toggle(self, skill_with_mocks):
        mock_message = Mock()
        mock_message.data = {"utterance": "resume the music"}

        with (
            patch.object(skill_with_mocks, "_get_player_id", return_value="test-player"),
            patch.object(skill_with_mocks, "voc_match", side_effect=lambda utt, voc, lang=None: voc == "resume"),
        ):
            skill_with_mocks.handle_pause(mock_message)

        skill_with_mocks.mass_client.send_command.assert_called_once_with(
            "player_queues/resume", queue_id="test-player"
        )
        skill_with_mocks.speak_dialog.assert_called_once_with("resumed")

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

    def test_local_session_persists_to_settings(self, skill, tmp_path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"music_assistant_url": "http://ma:8095", "music_assistant_token": "t"}))
        skill.settings.path = str(settings_file)
        message = Message("set_default_player.intent", {"player": "living room speaker"})

        skill.handle_set_default_player(message)

        assert skill.settings["default_player"] == "Living Room Speaker"
        on_disk = json.loads(settings_file.read_text())
        assert on_disk["default_player"] == "Living Room Speaker"
        assert on_disk["music_assistant_url"] == "http://ma:8095"
        assert on_disk["music_assistant_token"] == "t"
        skill.speak_dialog.assert_called_once_with("default_player_set", {"player": "Living Room Speaker"})

    def test_persisting_never_drops_keys_the_memory_copy_lost(self, skill, tmp_path):
        """Reproduces the Hub incident: a mid-write reload emptied the in-memory settings."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"music_assistant_url": "http://ma:8095", "music_assistant_token": "t"}))
        skill.settings.path = str(settings_file)
        skill.settings.clear()

        skill._persist_setting("default_player", "Office speaker")

        on_disk = json.loads(settings_file.read_text())
        assert on_disk == {
            "music_assistant_url": "http://ma:8095",
            "music_assistant_token": "t",
            "default_player": "Office speaker",
        }
        assert not (tmp_path / "settings.json.tmp").exists()

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


def _media(title, artist="Daft Punk", album="Discovery", uri="library://track/7", media_type="track"):
    media = Mock()
    media.title = title
    media.artist = artist
    media.album = album
    media.uri = uri
    media.media_type = media_type
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
    skill.settings["music_assistant_url"] = "http://ma:8095"
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

    def test_now_playing_radio_names_the_station_not_the_stream_junk(self):
        skill = _skill_with_player(
            current_media=_media("no desc", artist=None, album="BBC RADIO 1 - The biggest new pop", media_type="radio")
        )

        skill.handle_now_playing(Message("now_playing.intent", {}))

        skill.speak_dialog.assert_called_once_with("now_playing_radio", {"station": "BBC RADIO 1"})

    def test_now_playing_radio_with_a_song_in_the_stream_title(self):
        skill = _skill_with_player(
            current_media=_media("Daft Punk - Voyager", artist=None, album="KEXP", media_type="radio")
        )

        skill.handle_now_playing(Message("now_playing.intent", {}))

        skill.speak_dialog.assert_called_once_with(
            "now_playing_radio_track", {"title": "Daft Punk - Voyager", "station": "KEXP"}
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


class TestRadioByName:
    STATIONS = [
        {"name": "bbc 1 tv", "uri": "radiobrowser://radio/tv", "media_type": "radio"},
        {
            "name": "BBC RADIO 1 - The biggest new pop and all-day vibes",
            "uri": "radiobrowser://radio/r1",
            "media_type": "radio",
        },
    ]

    def test_named_station_is_found_through_a_radio_word_variant(self):
        """The server's substring search gives "bbc 1 tv" for "bbc 1" and the real station only for "bbc radio 1"."""
        skill = _skill_with_player()
        by_query = {
            "bbc 1": {"radio": [self.STATIONS[0]]},
            "bbc radio 1": {"radio": [self.STATIONS[1]]},
        }
        skill.mass_client.search_media.side_effect = lambda query, media_types=None, limit=5: by_query.get(query, {})

        skill.handle_play_radio(Message("play_radio.intent", {"radio_station": "bbc 1"}))

        queries = [c.kwargs["query"] for c in skill.mass_client.search_media.call_args_list]
        assert queries == ["bbc 1", "radio bbc 1", "bbc radio 1", "bbc 1 radio"]
        assert skill.mass_client.play_media.call_args.kwargs["media"] == "radiobrowser://radio/r1"
        skill.speak_dialog.assert_called_once_with("playing_radio", {"radio": "BBC RADIO 1"})

    def test_named_station_with_radio_in_the_name_searches_once(self):
        skill = _skill_with_player()
        skill.mass_client.search_media.return_value = {"radio": self.STATIONS}

        skill.handle_play_radio(Message("play_radio.intent", {"radio_station": "bbc radio 1"}))

        skill.mass_client.search_media.assert_called_once_with(
            query="bbc radio 1", media_types=[MediaType.RADIO], limit=10
        )

    def test_generic_play_prefers_the_station_over_a_track_mentioning_it(self):
        skill = _skill_with_player()
        skill.mass_client.search_media.return_value = {
            "tracks": [{"name": "3rd Planet BBC Radio 1 Session Version Radio Edit", "uri": "library://track/1"}],
            "radio": self.STATIONS,
        }

        assert skill.handle_generic_play(Message("fallback", {"utterance": "play bbc radio 1"})) is True
        assert skill.mass_client.play_media.call_args.kwargs["media"] == "radiobrowser://radio/r1"


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


GENRE_SEARCH = [
    {"item_id": "3", "name": "Blues"},
    {"item_id": "11", "name": "Funk"},
    {"item_id": "7", "name": "Jazz"},
    {"item_id": "19", "name": "Hip Hop"},
]


class TestGenreAndRandom:
    def test_genre_is_picked_by_name_from_the_unranked_search(self):
        skill = _skill_with_player()
        skill.mass_client.search_genres.return_value = GENRE_SEARCH
        skill.mass_client.genre_tracks.return_value = [{"uri": "library://track/1"}, {"uri": "library://track/2"}]

        skill.handle_play_genre(Message("play_genre.intent", {"genre": "jazz"}))

        skill.mass_client.search_genres.assert_called_once_with("jazz", limit=25)
        skill.mass_client.genre_tracks.assert_called_once_with("7", limit=50, sort_field="random")
        kwargs = skill.mass_client.play_media.call_args.kwargs
        assert kwargs["media"] == ["library://track/1", "library://track/2"]
        assert kwargs["shuffle"] is True
        assert kwargs["option"] == QueueOption.REPLACE
        skill.speak_dialog.assert_called_once_with("playing_genre", {"genre": "Jazz"})

    def test_genre_without_track_tags_plays_its_albums(self):
        skill = _skill_with_player()
        skill.mass_client.search_genres.return_value = GENRE_SEARCH
        skill.mass_client.genre_tracks.return_value = []
        skill.mass_client.genre_albums.return_value = [{"uri": f"library://album/{i}"} for i in range(8)]

        skill.handle_play_genre(Message("play_genre.intent", {"genre": "jazz"}))

        skill.mass_client.genre_albums.assert_called_once_with("7", limit=50, sort_field="random")
        assert skill.mass_client.play_media.call_args.kwargs["media"] == [f"library://album/{i}" for i in range(5)]
        skill.speak_dialog.assert_called_once_with("playing_genre", {"genre": "Jazz"})

    def test_filler_words_are_stripped_before_the_lookup(self):
        skill = _skill_with_player()
        skill.mass_client.search_genres.return_value = GENRE_SEARCH
        skill.mass_client.genre_tracks.return_value = [{"uri": "library://track/1"}]

        skill.handle_play_genre(Message("play_genre.intent", {"genre": "some jazz music"}))

        skill.mass_client.search_genres.assert_called_once_with("jazz", limit=25)

    def test_artist_caught_by_the_genre_pattern_plays_the_artist(self):
        skill = _skill_with_player()
        skill.mass_client.search_genres.return_value = GENRE_SEARCH
        skill.mass_client.send_command.return_value = GENRE_SEARCH
        skill.mass_client.search_media.return_value = {
            "artists": [{"name": "The Beatles", "uri": "library://artist/119"}],
        }

        skill.handle_play_genre(Message("play_genre.intent", {"genre": "beatles"}))

        skill.mass_client.genre_tracks.assert_not_called()
        kwargs = skill.mass_client.play_media.call_args.kwargs
        assert kwargs["media"] == "library://artist/119"
        assert kwargs["shuffle"] is True
        skill.speak_dialog.assert_called_once_with("playing", {"track_name": "music", "artist_name": "The Beatles"})

    def test_unknown_name(self):
        skill = _skill_with_player()
        skill.mass_client.search_genres.return_value = GENRE_SEARCH
        skill.mass_client.send_command.return_value = GENRE_SEARCH
        skill.mass_client.search_media.return_value = {}
        skill.mass_client.get_item_by_name.return_value = None

        skill.handle_play_genre(Message("play_genre.intent", {"genre": "polka"}))

        skill.mass_client.play_media.assert_not_called()
        skill.speak_dialog.assert_called_once_with("could_not_find_genre", {"genre": "polka"})

    def test_stt_noise_slot_means_random(self):
        skill = _skill_with_player()
        skill.mass_client.library_items.return_value = [{"uri": "library://track/9"}]

        skill.handle_play_genre(Message("play_genre.intent", {"genre": "in"}))

        skill.mass_client.search_genres.assert_not_called()
        skill.speak_dialog.assert_called_once_with("playing_random")

    def test_some_music_is_random_not_a_genre(self):
        skill = _skill_with_player()
        skill.mass_client.library_items.return_value = [{"uri": "library://track/9"}]

        skill.handle_play_genre(Message("play_genre.intent", {"genre": "some"}))

        skill.mass_client.search_genres.assert_not_called()
        skill.mass_client.library_items.assert_called_once_with(MediaType.TRACK, limit=50, sort_field="random")
        skill.speak_dialog.assert_called_once_with("playing_random")

    def test_random_with_empty_library(self):
        skill = _skill_with_player()
        skill.mass_client.library_items.return_value = []

        skill.handle_play_random(Message("play_random.intent", {}))

        skill.mass_client.play_media.assert_not_called()
        skill.speak_dialog.assert_called_once_with("library_empty")

    def test_artist_intent_now_shuffles(self):
        skill = _skill_with_player()
        artist = Mock()
        artist.name = "Daft Punk"
        artist.uri = "library://artist/1"
        with patch.object(skill, "_search_media", return_value=artist):
            skill.handle_play_artist(Message("play_artist.intent", {"artist": "daft punk"}))

        assert skill.mass_client.play_media.call_args.kwargs["shuffle"] is True


class TestShuffleAndRepeat:
    def _with_voc(self, skill, matching):
        return patch.object(skill, "voc_match", side_effect=lambda utt, voc, lang=None: voc in matching)

    def test_shuffle_on(self):
        skill = _skill_with_player()
        with self._with_voc(skill, set()):
            skill.handle_shuffle(Message("shuffle.intent", {"utterance": "shuffle on"}))

        skill.mass_client.queue_set_shuffle.assert_called_once_with("lr-1", True)
        skill.speak_dialog.assert_called_once_with("shuffle_on")

    def test_shuffle_off(self):
        skill = _skill_with_player()
        with self._with_voc(skill, {"shuffle_off"}):
            skill.handle_shuffle(Message("shuffle.intent", {"utterance": "stop shuffling"}))

        skill.mass_client.queue_set_shuffle.assert_called_once_with("lr-1", False)
        skill.speak_dialog.assert_called_once_with("shuffle_off")

    @pytest.mark.parametrize(
        "matching,mode,dialog",
        [
            ({"repeat_off"}, "off", "repeat_off"),
            ({"repeat_all"}, "all", "repeat_all"),
            ({"repeat_one"}, "one", "repeat_one"),
            (set(), "one", "repeat_one"),
        ],
    )
    def test_repeat_modes(self, matching, mode, dialog):
        skill = _skill_with_player()
        with self._with_voc(skill, matching):
            skill.handle_repeat(Message("repeat.intent", {"utterance": "repeat"}))

        assert skill.mass_client.queue_set_repeat.call_args.args[1].value == mode
        skill.speak_dialog.assert_called_once_with(dialog)

    def test_repeat_off_wins_over_other_words(self):
        skill = _skill_with_player()
        with self._with_voc(skill, {"repeat_off", "repeat_one"}):
            skill.handle_repeat(Message("repeat.intent", {"utterance": "don't repeat this song"}))

        assert skill.mass_client.queue_set_repeat.call_args.args[1].value == "off"


WORKOUT = {"item_id": "12", "name": "Workout", "uri": "library://playlist/12"}


class TestPlaylistsByVoice:
    def test_create_new_playlist(self):
        skill = _skill_with_player()
        skill.mass_client.library_playlists.return_value = []
        skill.mass_client.create_playlist.return_value = WORKOUT

        skill.handle_create_playlist(Message("create_playlist.intent", {"playlist": "workout"}))

        skill.mass_client.create_playlist.assert_called_once_with("workout")
        skill.speak_dialog.assert_called_once_with("playlist_created", {"playlist": "Workout"})

    def test_create_existing_playlist_is_refused(self):
        skill = _skill_with_player()
        skill.mass_client.library_playlists.return_value = [WORKOUT]

        skill.handle_create_playlist(Message("create_playlist.intent", {"playlist": "workout"}))

        skill.mass_client.create_playlist.assert_not_called()
        skill.speak_dialog.assert_called_once_with("playlist_exists", {"playlist": "workout"})

    def test_add_current_track_creates_playlist_on_first_use(self):
        skill = _skill_with_player(current_media=_media("One More Time"))
        skill.mass_client.library_playlists.return_value = []
        skill.mass_client.create_playlist.return_value = WORKOUT

        skill.handle_add_to_playlist(Message("add_to_playlist.intent", {"playlist": "workout"}))

        skill.mass_client.add_playlist_tracks.assert_called_once_with("12", ["library://track/7"])
        skill.speak_dialog.assert_called_once_with(
            "added_to_playlist", {"title": "One More Time", "playlist": "Workout"}
        )

    def test_add_matches_playlist_fuzzily(self):
        skill = _skill_with_player(current_media=_media("One More Time"))
        skill.mass_client.library_playlists.return_value = [WORKOUT, {"item_id": "3", "name": "Focus", "uri": "u"}]

        skill.handle_add_to_playlist(Message("add_to_playlist.intent", {"playlist": "work out"}))

        skill.mass_client.create_playlist.assert_not_called()
        skill.mass_client.add_playlist_tracks.assert_called_once_with("12", ["library://track/7"])

    def test_add_when_idle(self):
        skill = _skill_with_player(current_media=None)

        skill.handle_add_to_playlist(Message("add_to_playlist.intent", {"playlist": "workout"}))

        skill.mass_client.add_playlist_tracks.assert_not_called()
        skill.speak_dialog.assert_called_once_with("nothing_playing")

    def test_remove_current_track_by_uri(self):
        skill = _skill_with_player(current_media=_media("One More Time"))
        skill.mass_client.library_playlists.return_value = [WORKOUT]
        skill.mass_client.playlist_tracks.return_value = [
            {"name": "Other", "uri": "library://track/1"},
            {"name": "One More Time", "uri": "library://track/7"},
        ]

        skill.handle_remove_from_playlist(Message("remove_from_playlist.intent", {"playlist": "workout"}))

        skill.mass_client.remove_playlist_tracks.assert_called_once_with("12", [1])
        skill.speak_dialog.assert_called_once_with(
            "removed_from_playlist", {"title": "One More Time", "playlist": "Workout"}
        )

    def test_remove_falls_back_to_title_and_artist(self):
        skill = _skill_with_player(current_media=_media("One More Time", uri="http://stream/x"))
        skill.mass_client.library_playlists.return_value = [WORKOUT]
        skill.mass_client.playlist_tracks.return_value = [
            {"name": "One More Time", "uri": "library://track/7", "artists": [{"name": "Daft Punk"}]},
        ]

        skill.handle_remove_from_playlist(Message("remove_from_playlist.intent", {"playlist": "workout"}))

        skill.mass_client.remove_playlist_tracks.assert_called_once_with("12", [0])

    def test_remove_track_not_on_playlist(self):
        skill = _skill_with_player(current_media=_media("One More Time"))
        skill.mass_client.library_playlists.return_value = [WORKOUT]
        skill.mass_client.playlist_tracks.return_value = [{"name": "Other", "uri": "library://track/1"}]

        skill.handle_remove_from_playlist(Message("remove_from_playlist.intent", {"playlist": "workout"}))

        skill.mass_client.remove_playlist_tracks.assert_not_called()
        skill.speak_dialog.assert_called_once_with(
            "not_in_playlist", {"title": "One More Time", "playlist": "Workout"}
        )

    def test_save_queue(self):
        skill = _skill_with_player()

        skill.handle_save_queue(Message("save_queue.intent", {"playlist": "tonight"}))

        skill.mass_client.save_queue_as_playlist.assert_called_once_with("lr-1", "tonight")
        skill.speak_dialog.assert_called_once_with("queue_saved", {"playlist": "tonight"})

    def test_list_playlists_speaks_count_and_names(self):
        skill = _skill_with_player()
        skill.mass_client.library_playlists.return_value = [WORKOUT, {"item_id": "3", "name": "Focus", "uri": "u"}]

        skill.handle_list_playlists(Message("list_playlists.intent", {}))

        skill.speak_dialog.assert_called_once_with("playlists_list", {"count": 2, "names": "Workout, Focus"})

    def test_list_playlists_when_none(self):
        skill = _skill_with_player()
        skill.mass_client.library_playlists.return_value = []

        skill.handle_list_playlists(Message("list_playlists.intent", {}))

        skill.speak_dialog.assert_called_once_with("no_playlists")

    def test_playlist_contents_first_three(self):
        skill = _skill_with_player()
        skill.mass_client.library_playlists.return_value = [WORKOUT]
        skill.mass_client.playlist_tracks.return_value = [{"name": f"Track {i}"} for i in range(5)]

        skill.handle_playlist_contents(Message("playlist_contents.intent", {"playlist": "workout"}))

        skill.speak_dialog.assert_called_once_with(
            "playlist_contents", {"playlist": "Workout", "count": 5, "titles": "Track 0, Track 1, Track 2"}
        )

    def test_playlist_contents_unknown_playlist(self):
        skill = _skill_with_player()
        skill.mass_client.library_playlists.return_value = []

        skill.handle_playlist_contents(Message("playlist_contents.intent", {"playlist": "nope"}))

        skill.speak_dialog.assert_called_once_with("could_not_find_playlist", {"playlist": "nope"})


class TestRadioDiscovery:
    def test_plays_first_station_then_enqueues_the_rest(self):
        skill = _skill_with_player()
        stations = ["radiobrowser://radio/a", "radiobrowser://radio/b", "radiobrowser://radio/c"]
        with patch("skill_musicassistant.catalog.radio_category_station_uris", return_value=stations) as resolver:
            skill.handle_play_radio_category(Message("play_radio_category.intent", {"category": "spain"}))
        for thread in threading.enumerate():
            if thread.name == "musicassistant-enqueue":
                thread.join(timeout=5)

        resolver.assert_called_once_with(skill.mass_client, "spain", 5)
        first, rest = skill.mass_client.play_media.call_args_list
        assert first.kwargs["media"] == "radiobrowser://radio/a"
        assert first.kwargs["option"] == QueueOption.REPLACE
        assert rest.kwargs["media"] == ["radiobrowser://radio/b", "radiobrowser://radio/c"]
        assert rest.kwargs["option"] == QueueOption.ADD
        skill.speak_dialog.assert_called_once_with("playing_radio_category", {"category": "spain", "count": 3})

    def test_single_station_adds_nothing_in_the_background(self):
        skill = _skill_with_player()
        with patch(
            "skill_musicassistant.catalog.radio_category_station_uris", return_value=["radiobrowser://radio/a"]
        ):
            skill.handle_play_radio_category(Message("play_radio_category.intent", {"category": "spain"}))

        assert skill.mass_client.play_media.call_count == 1

    def test_unknown_category(self):
        skill = _skill_with_player()
        skill.mass_client.browse.return_value = []

        skill.handle_play_radio_category(Message("play_radio_category.intent", {"category": "zorblax"}))

        skill.mass_client.play_media.assert_not_called()
        skill.speak_dialog.assert_called_once_with("could_not_find_radio_category", {"category": "zorblax"})


class TestStop:
    def _states(self, skill, **states):
        for player in skill.players:
            state = Mock()
            state.value = states.get(player.player_id, "idle")
            player.playback_state = state
        skill.mass_client.get_players.return_value = skill.players

    def test_stop_stops_the_player_used_most_recently(self):
        skill = _skill_with_player()
        office = _make_player("Office Speaker", "office-1")
        skill.players.append(office)
        skill._last_used_player = office
        self._states(skill, **{"office-1": "playing"})

        assert skill.stop() is True
        skill.mass_client.player_command_stop.assert_called_once_with("office-1")
        skill.mass_client.queue_command_pause.assert_not_called()

    def test_stop_falls_back_to_default_player(self):
        skill = _skill_with_player()
        self._states(skill, **{"lr-1": "paused"})

        assert skill.stop() is True
        skill.mass_client.player_command_stop.assert_called_once_with("lr-1")

    def test_stop_does_nothing_to_an_idle_player(self):
        """stop used to call play_pause, which started idle speakers."""
        skill = _skill_with_player()
        self._states(skill, **{"lr-1": "idle"})

        assert skill.stop() is False
        skill.mass_client.player_command_stop.assert_not_called()
        skill.mass_client.queue_command_pause.assert_not_called()

    def test_stop_with_no_known_player_returns_false(self):
        skill = _skill_with_player()
        skill.players = []
        skill.settings.pop("default_player", None)
        skill._last_used_player = None

        assert skill.stop() is False


class TestRobustness:
    def test_init_survives_an_unreachable_server(self):
        with patch("skill_musicassistant.SimpleHTTPMusicAssistantClient") as mock_client_class:
            instance = Mock(spec=SimpleHTTPMusicAssistantClient)
            instance.get_players.side_effect = ConnectionError("refused")
            mock_client_class.return_value = instance
            skill = MusicAssistantSkill(bus=cast(MessageBusClient, FakeBus()), skill_id="test-skill")

        assert skill.players == []
        assert skill.stop() is False

    def test_unconfigured_skill_says_so(self):
        skill = _skill_with_player()
        skill.settings.pop("music_assistant_url", None)

        skill.handle_pause(Message("pause.intent", {"utterance": "pause the music"}))

        skill.speak_dialog.assert_called_once_with("not_configured")
        skill.mass_client.send_command.assert_not_called()

    def test_unavailable_player_is_reported(self):
        skill = _skill_with_player()
        skill.players[0].available = False
        skill.settings["music_assistant_url"] = "http://ma:8095"

        skill.handle_pause(Message("pause.intent", {"utterance": "pause the music"}))

        skill.speak_dialog.assert_called_once_with("player_unavailable", {"player": "Living Room Speaker"})
        skill.mass_client.send_command.assert_not_called()


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])

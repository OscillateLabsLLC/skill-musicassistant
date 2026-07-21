"""Integration tests for the MusicAssistantSkill class."""

from typing import cast
from unittest.mock import Mock, PropertyMock, patch

import pytest
from music_assistant_models.enums import MediaType
from ovos_bus_client import Message, MessageBusClient
from ovos_bus_client.session import Session
from ovos_utils.fakebus import FakeBus

from skill_musicassistant import MusicAssistantSkill
from skill_musicassistant.music_assistant_client import SimpleHTTPMusicAssistantClient


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


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])

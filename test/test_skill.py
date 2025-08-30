"""Integration tests for the MusicAssistantSkill class."""

from typing import cast
from unittest.mock import Mock, patch

import pytest
from ovos_bus_client import MessageBusClient
from ovos_utils.fakebus import FakeBus

from skill_musicassistant import MusicAssistantSkill
from skill_musicassistant.music_assistant_client import SimpleHTTPMusicAssistantClient


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

    def test_get_player_id_with_location(self, skill_with_mock_client, mock_client):
        """Test player ID resolution with location."""
        # Mock players response with proper name attributes
        mock_players = [
            Mock(name="Office Speaker", player_id="office-123"),
            Mock(name="Living Room", player_id="living-456"),
        ]
        # Set the name attribute properly for string operations
        mock_players[0].name = "Office Speaker"
        mock_players[1].name = "Living Room"
        mock_client.get_players.return_value = mock_players

        # Test finding by location
        player_id = skill_with_mock_client._get_player_id("Office")
        assert player_id == "office-123"

        # Test fallback to default - mock the default_player property
        with patch.object(type(skill_with_mock_client), "default_player", new_callable=lambda: "default_player"):
            player_id = skill_with_mock_client._get_player_id("Nonexistent")
            assert player_id == "default_player"

    def test_get_player_id_fallback_to_first(self, skill_with_mock_client, mock_client):
        """Test fallback to first available player."""
        # Mock players response
        mock_players = [
            Mock(name="Random Player", player_id="random-123"),
        ]
        mock_players[0].name = "Random Player"
        mock_client.get_players.return_value = mock_players

        # Mock the default_player property to return None for this test
        with patch.object(type(skill_with_mock_client), "default_player", new_callable=lambda: None):
            player_id = skill_with_mock_client._get_player_id("Nonexistent")
            assert player_id == "random-123"

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

    def test_search_media_no_results(self, skill_with_mock_client, mock_client):
        """Test media search with no results."""
        mock_client.search_media.return_value = {"artists": []}

        result = skill_with_mock_client._search_media("Nonexistent", "artist")
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
        assert skill._parse_volume_level("mute") == 0
        assert skill._parse_volume_level("half") == 50
        assert skill._parse_volume_level("max") == 100
        assert skill._parse_volume_level("loud") == 75

    def test_parse_volume_level_percent(self, skill):
        """Test volume level parsing with percent notation."""
        assert skill._parse_volume_level("75%") == 75
        assert skill._parse_volume_level("25 percent") == 25

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

            skill_with_mocks.speak_dialog.assert_called_once_with("generic_could_not", {"thing": "find a player."})

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

    def test_handle_volume_success(self, skill_with_mocks):
        """Test successful volume handling."""
        mock_message = Mock()
        mock_message.data = {"volume": "50"}

        with patch.object(skill_with_mocks, "_get_player_id", return_value="test-player"):
            skill_with_mocks.handle_volume(mock_message)

            print(f"Mass client: {skill_with_mocks.mass_client.player_command_volume_set.call_args}")
            skill_with_mocks.mass_client.player_command_volume_set.assert_called_once_with("test-player", 50)
            skill_with_mocks.speak_dialog.assert_called_once_with("volume_set", {"volume": 50})

    def test_handle_volume_invalid_level(self, skill_with_mocks):
        """Test volume handling with invalid level."""
        mock_message = Mock()
        mock_message.data = {"volume": "invalid"}

        with patch.object(skill_with_mocks, "_get_player_id", return_value="test-player"):
            skill_with_mocks.handle_volume(mock_message)

            skill_with_mocks.speak_dialog.assert_called_once_with(
                "generic_could_not", {"thing": "understand volume level invalid."}
            )


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])

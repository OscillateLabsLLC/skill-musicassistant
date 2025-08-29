import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import Mock, patch

import pytest
import requests

from skill_musicassistant.music_assistant_client import SimpleHTTPMusicAssistantClient


class TestSimpleHTTPMusicAssistantClientAdvanced:
    """Advanced tests for SimpleHTTPMusicAssistantClient including queue, player, and state methods."""

    @pytest.fixture
    def fixtures_dir(self):
        """Get fixtures directory."""
        return Path(__file__).parent / "fixtures"

    @pytest.fixture
    def load_fixture(self, fixtures_dir):
        """Helper to load fixtures."""

        def _load_fixture(filename: str) -> Dict[str, Any]:
            fixture_path = fixtures_dir / filename
            with open(fixture_path, "r", encoding="utf-8") as f:
                return json.load(f)

        return _load_fixture

    @pytest.fixture
    def mock_session(self):
        """Mock requests session for testing."""
        return Mock(spec=requests.Session)

    @pytest.fixture
    def client(self, mock_session):
        """Create a client instance with mocked session."""
        return SimpleHTTPMusicAssistantClient(server_url="http://test-server:8095", session=mock_session)

    def test_play_media(self, client, mock_session, load_fixture):
        """Test playing media."""
        fixture = load_fixture("009_send_command_player_queues_play_media.json")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = fixture["response"]
        mock_session.post.return_value = mock_response

        client.play_media(queue_id="test-queue-id", media="library://artist/204", option="play", radio_mode=False)

        call_args = mock_session.post.call_args
        assert call_args[1]["json"]["command"] == "player_queues/play_media"
        assert call_args[1]["json"]["args"]["queue_id"] == "test-queue-id"
        assert call_args[1]["json"]["args"]["media"] == "library://artist/204"
        assert call_args[1]["json"]["args"]["option"] == "play"
        assert call_args[1]["json"]["args"]["radio_mode"] is False

    def test_queue_commands(self, client, mock_session):
        """Test all queue control commands."""
        queue_id = "test-queue-id"

        # Test each queue command
        commands = [
            ("queue_command_play", "player_queues/play", {}),
            ("queue_command_pause", "player_queues/pause", {}),
            ("queue_command_next", "player_queues/next", {}),
            ("queue_command_previous", "player_queues/previous", {}),
        ]

        for method_name, expected_command, extra_args in commands:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = None
            mock_session.post.return_value = mock_response

            # Call the method
            method = getattr(client, method_name)
            method(queue_id, **extra_args)

            # Verify the call
            call_args = mock_session.post.call_args
            assert call_args[1]["json"]["command"] == expected_command
            assert call_args[1]["json"]["args"]["queue_id"] == queue_id

    def test_player_power_commands(self, client, mock_session):
        """Test player power control commands."""
        player_id = "test-player-id"

        # Test player power commands
        power_commands = [
            ("player_command_power_on", "players/player_command_power_on"),
            ("player_command_power_off", "players/player_command_power_off"),
        ]

        for method_name, expected_command in power_commands:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = None
            mock_session.post.return_value = mock_response

            method = getattr(client, method_name)
            method(player_id)

            call_args = mock_session.post.call_args
            assert call_args[1]["json"]["command"] == expected_command
            assert call_args[1]["json"]["args"]["player_id"] == player_id

    def test_volume_commands(self, client, mock_session, load_fixture):
        """Test volume control commands."""
        player_id = "test-player-id"

        # Test volume set
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = None
        mock_session.post.return_value = mock_response

        client.player_command_volume_set(player_id, 50)

        call_args = mock_session.post.call_args
        assert call_args[1]["json"]["command"] == "players/cmd/volume_set"
        assert call_args[1]["json"]["args"]["player_id"] == player_id
        assert call_args[1]["json"]["args"]["volume_level"] == 50

        # Test volume up/down
        volume_commands = [
            ("player_command_volume_up", "players/cmd/volume_up", {"step": 10}),
            ("player_command_volume_down", "players/cmd/volume_down", {"step": 5}),
        ]

        for method_name, expected_command, kwargs in volume_commands:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = None
            mock_session.post.return_value = mock_response

            method = getattr(client, method_name)
            method(player_id, **kwargs)

            call_args = mock_session.post.call_args
            assert call_args[1]["json"]["command"] == expected_command
            assert call_args[1]["json"]["args"]["player_id"] == player_id
            if "step" in kwargs:
                assert call_args[1]["json"]["args"]["step"] == kwargs["step"]

        # Test volume mute
        client.player_command_volume_mute(player_id, True)
        call_args = mock_session.post.call_args
        assert call_args[1]["json"]["command"] == "players/cmd/volume_mute"
        assert call_args[1]["json"]["args"]["muted"] is True

    def test_state_checking_methods(self, client, mock_session):
        """Test state checking and queue methods."""
        player_id = "test-player-id"
        queue_id = "test-queue-id"

        # Test get_player_queue_items
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_session.post.return_value = mock_response

        client.get_player_queue_items(queue_id, limit=5, offset=10)

        call_args = mock_session.post.call_args
        assert call_args[1]["json"]["command"] == "player_queues/items"
        assert call_args[1]["json"]["args"]["queue_id"] == queue_id
        assert call_args[1]["json"]["args"]["limit"] == 5
        assert call_args[1]["json"]["args"]["offset"] == 10

        # Test get_active_queue
        client.get_active_queue(player_id)
        call_args = mock_session.post.call_args
        assert call_args[1]["json"]["command"] == "player_queues/get_active_queue"
        assert call_args[1]["json"]["args"]["player_id"] == player_id

    def test_find_player_by_id(self, client, mock_session, load_fixture):
        """Test finding a player by ID."""
        fixture = load_fixture("002_get_players.json")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = fixture["raw_response"]
        mock_session.post.return_value = mock_response

        # Find existing player
        first_player_id = fixture["raw_response"][0]["player_id"]
        found_player = client._find_player_by_id(first_player_id)
        assert found_player is not None
        assert found_player["player_id"] == first_player_id

        # Try to find non-existent player
        not_found = client._find_player_by_id("non-existent-id")
        assert not_found is None

    def test_get_player_state(self, client, mock_session, load_fixture):
        """Test getting player state."""
        fixture = load_fixture("002_get_players.json")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = fixture["raw_response"]
        mock_session.post.return_value = mock_response

        # Get state for existing player
        first_player_id = fixture["raw_response"][0]["player_id"]
        state = client.get_player_state(first_player_id)

        assert state is not None
        assert "state" in state
        assert "powered" in state
        assert "volume_level" in state
        assert "volume_muted" in state
        assert "current_track" in state
        assert "player_name" in state

        # Test with non-existent player
        state = client.get_player_state("non-existent")
        assert state is None

    def test_formatting_methods(self, client):
        """Test display formatting helper methods."""
        # Test status emoji
        assert client._format_status_emoji("playing") == "▶️"
        assert client._format_status_emoji("paused") == "⏸️"
        assert client._format_status_emoji("stopped") == "⏹️"
        assert client._format_status_emoji("idle") == "💤"
        assert client._format_status_emoji("unknown") == "❓"

        # Test power display
        assert client._format_power_display(True) == "🔌"
        assert client._format_power_display(False) == "🔌❌"

        # Test volume display
        assert client._format_volume_display(50, False) == "🔊 50%"
        assert client._format_volume_display(50, True) == "🔇 50%"
        assert client._format_volume_display(None, False) == "🔊 ?"

    @patch.object(SimpleHTTPMusicAssistantClient, "get_player_state")
    def test_show_current_state(self, mock_get_state, client):
        """Test show_current_state method."""
        # Mock successful state retrieval
        mock_get_state.return_value = {
            "state": "playing",
            "powered": True,
            "volume_level": 75,
            "volume_muted": False,
            "current_track": "Test Artist - Test Song",
            "player_name": "Test Player",
        }

        # Should not raise any exceptions
        client.show_current_state("test-player", "Test Action")

        # Test with failed state retrieval
        mock_get_state.return_value = None
        client.show_current_state("test-player", "Failed Action")

    def test_error_handling(self, client, mock_session):
        """Test various error scenarios."""
        # Test network error
        mock_session.post.side_effect = requests.RequestException("Network error")

        with pytest.raises(requests.RequestException):
            client.send_command("test/command")

        # Test JSON decode error
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_session.post.return_value = mock_response
        mock_session.post.side_effect = None  # Reset side effect

        with pytest.raises(ValueError):
            client.send_command("test/command")

    def test_integration_with_real_fixtures(self, load_fixture):
        """Test that our client works with all captured fixture data."""
        # This test validates that our understanding of fixture format is correct

        # Test a few key fixtures
        players_fixture = load_fixture("001_send_command_players_all.json")
        assert "command" in players_fixture
        assert "response" in players_fixture

        search_fixture = load_fixture("005_send_command_music_search.json")
        assert search_fixture["command"] == "music/search"
        assert "artists" in search_fixture["response"]

        # Verify we can create Player objects from the data
        players_data = players_fixture["response"]
        assert len(players_data) > 0


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])

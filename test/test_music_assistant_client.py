import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import Mock

import pytest
import requests
from music_assistant_models.enums import MediaType
from music_assistant_models.errors import MusicAssistantError
from music_assistant_models.player import Player

from skill_musicassistant.music_assistant_client import SimpleHTTPMusicAssistantClient


class FixtureHelper:
    """Helper class to load and manage test fixtures."""

    def __init__(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures"
        self._fixture_cache = {}

    def load_fixture(self, filename: str) -> Dict[str, Any]:
        """Load a fixture file and cache it."""
        if filename not in self._fixture_cache:
            fixture_path = self.fixtures_dir / filename
            if not fixture_path.exists():
                raise FileNotFoundError(f"Fixture file not found: {fixture_path}")

            with open(fixture_path, "r", encoding="utf-8") as f:
                self._fixture_cache[filename] = json.load(f)

        return self._fixture_cache[filename]

    def get_command_fixture(self, fixture_number: int) -> Dict[str, Any]:
        """Get a command fixture by number (e.g., 001 for players/all)."""
        filename = f"{fixture_number:03d}_send_command_*.json"
        # Find the actual filename
        for file in self.fixtures_dir.glob(filename):
            return self.load_fixture(file.name)
        raise FileNotFoundError(f"Command fixture {fixture_number:03d} not found")

    def get_response_fixture(self, fixture_number: int) -> Dict[str, Any]:
        """Get a response fixture by number."""
        filename = f"{fixture_number:03d}_*.json"
        # Find the actual filename (prefer non-send_command files)
        for file in self.fixtures_dir.glob(filename):
            if not file.name.startswith(f"{fixture_number:03d}_send_command"):
                return self.load_fixture(file.name)
        # Fallback to send_command file
        for file in self.fixtures_dir.glob(filename):
            return self.load_fixture(file.name)
        raise FileNotFoundError(f"Response fixture {fixture_number:03d} not found")


class TestSimpleHTTPMusicAssistantClient:
    """Comprehensive tests for SimpleHTTPMusicAssistantClient using captured fixtures."""

    @pytest.fixture
    def fixtures(self):
        """Provide test fixtures helper."""
        return FixtureHelper()

    @pytest.fixture
    def mock_session(self):
        """Mock requests session for testing."""
        return Mock(spec=requests.Session)

    @pytest.fixture
    def client(self, mock_session):
        """Create a client instance with mocked session."""
        return SimpleHTTPMusicAssistantClient(server_url="http://test-server:8095", session=mock_session)

    def test_client_initialization(self):
        """Test client initialization with different configurations."""
        # Test with session
        session = Mock(spec=requests.Session)
        client = SimpleHTTPMusicAssistantClient("http://localhost:8095", "test-token", session)
        assert client.server_url == "http://localhost:8095"
        assert client.api_url == "http://localhost:8095/api"
        assert client.token == "test-token"
        assert client.session is session

    def test_send_command_success(self, client, mock_session, fixtures):
        """Test successful command sending."""
        # Use the players/all fixture
        fixture = fixtures.load_fixture("001_send_command_players_all.json")

        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = fixture["response"]
        mock_session.post.return_value = mock_response

        # Send command
        result = client.send_command("players/all")

        # Verify request was made correctly
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        assert call_args[1]["json"]["command"] == "players/all"
        assert call_args[1]["json"]["args"] == {}
        assert "message_id" in call_args[1]["json"]

        # Verify response
        assert result == fixture["response"]

    def test_send_command_with_args(self, client, mock_session, fixtures):
        """Test command sending with arguments."""
        fixture = fixtures.load_fixture("005_send_command_music_search.json")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = fixture["response"]
        mock_session.post.return_value = mock_response

        # Send command with args
        client.send_command("music/search", search_query="Carbon Leaf", limit=5, media_types=["artist"])

        # Verify request
        call_args = mock_session.post.call_args
        assert call_args[1]["json"]["command"] == "music/search"
        assert call_args[1]["json"]["args"]["search_query"] == "Carbon Leaf"
        assert call_args[1]["json"]["args"]["limit"] == 5
        assert call_args[1]["json"]["args"]["media_types"] == ["artist"]

    def test_send_command_http_error(self, client, mock_session):
        """Test command sending with HTTP error."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_session.post.return_value = mock_response

        with pytest.raises(MusicAssistantError) as exc_info:
            client.send_command("test/command")

        assert "HTTP 500" in str(exc_info.value)

    def test_get_players(self, client, mock_session, fixtures):
        """Test getting all players."""
        fixture = fixtures.load_fixture("002_get_players.json")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = fixture["raw_response"]
        mock_session.post.return_value = mock_response

        players = client.get_players()

        # Verify it's a list of Player objects
        assert isinstance(players, list)
        assert len(players) > 0
        assert all(isinstance(p, Player) for p in players)

        # Check first player matches fixture data
        first_player = players[0]
        first_fixture_player = fixture["raw_response"][0]
        assert first_player.player_id == first_fixture_player["player_id"]
        assert first_player.name == first_fixture_player["name"]

    def test_search_media_with_media_types(self, client, mock_session, fixtures):
        """Test media search with specific media types."""
        fixture = fixtures.load_fixture("005_send_command_music_search.json")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = fixture["response"]
        mock_session.post.return_value = mock_response

        result = client.search_media(query="Carbon Leaf", media_types=[MediaType.ARTIST], limit=5)

        # Verify command was called correctly
        call_args = mock_session.post.call_args
        assert call_args[1]["json"]["args"]["search_query"] == "Carbon Leaf"
        assert call_args[1]["json"]["args"]["media_types"] == ["artist"]
        assert call_args[1]["json"]["args"]["limit"] == 5

        # Verify response
        assert result == fixture["response"]

    def test_search_media_without_media_types(self, client, mock_session):
        """Test media search without specific media types."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"tracks": [], "artists": [], "albums": []}
        mock_session.post.return_value = mock_response

        client.search_media("test query")

        call_args = mock_session.post.call_args
        assert "media_types" not in call_args[1]["json"]["args"]

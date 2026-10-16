"""Tests for radio discovery through the radio-browser category folders."""

from unittest.mock import Mock

from skill_musicassistant.catalog import radio_category_station_uris


COUNTRIES = [
    {"name": "Spain", "path": "radiobrowser://category/country/es", "media_type": "folder"},
    {"name": "France", "path": "radiobrowser://category/country/fr", "media_type": "folder"},
]
LANGUAGES = [
    {"name": "spanish", "path": "radiobrowser://category/language/spanish", "media_type": "folder"},
    {"name": "french", "path": "radiobrowser://category/language/french", "media_type": "folder"},
]
TAGS = [
    {"name": "Jazz", "path": "radiobrowser://category/tag/jazz", "media_type": "folder"},
    {"name": "Rock", "path": "radiobrowser://category/tag/rock", "media_type": "folder"},
]
STATIONS = [
    {"name": "Radio One", "uri": "radiobrowser://radio/aaa", "media_type": "radio"},
    {"name": "Radio Two", "item_id": "bbb", "provider": "radiobrowser", "media_type": "radio"},
    {"name": "Broken", "media_type": "radio"},
]


def _client(station_path):
    client = Mock()

    def browse(path, limit=100, offset=0):
        folders = {
            "radiobrowser://category/country": COUNTRIES,
            "radiobrowser://category/language": LANGUAGES,
            "radiobrowser://category/tag": TAGS,
        }
        if path in folders:
            return folders[path]
        return STATIONS if path == station_path else []

    client.browse.side_effect = browse
    return client


def test_country_name_resolves_to_country_folder():
    client = _client("radiobrowser://category/country/es")

    uris = radio_category_station_uris(client, "spain", limit=10)

    assert uris == ["radiobrowser://radio/aaa", "radiobrowser://radio/bbb"]
    client.browse.assert_any_call("radiobrowser://category/country/es", limit=10)


def test_language_word_resolves_to_language_folder():
    client = _client("radiobrowser://category/language/spanish")

    assert radio_category_station_uris(client, "spanish", limit=10) == [
        "radiobrowser://radio/aaa",
        "radiobrowser://radio/bbb",
    ]


def test_genre_word_resolves_to_tag_folder():
    client = _client("radiobrowser://category/tag/jazz")

    assert len(radio_category_station_uris(client, "jazz", limit=10)) == 2


def test_unknown_word_gives_nothing():
    client = _client("radiobrowser://category/tag/jazz")

    assert radio_category_station_uris(client, "zorblax", limit=10) == []

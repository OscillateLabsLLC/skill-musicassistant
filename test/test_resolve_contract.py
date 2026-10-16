"""Contract tests: the resolver against recorded Music Assistant responses.

Each test replays the recording made for the same-named scenario in
``ma_scenarios.py``. Re-record with ``scripts/record_ma_fixtures.py`` when the
server changes; the recording diff then shows what moved.
"""

# pylint: disable=missing-docstring

import pytest

from skill_musicassistant.parser import Kind, MediaRequest
from skill_musicassistant.resolve import Resolution, resolve

from .ma_recording import FIXTURE_DIR, ReplayClient, UnrecordedCall
from .ma_scenarios import SCENARIOS


def replay(name: str) -> Resolution:
    return resolve(ReplayClient.load(name), SCENARIOS[name])


class TestBareRequests:
    def test_artist_name_plays_the_artist_not_a_track(self):
        found = replay("bare_artist")
        assert found.kind is Kind.ARTIST
        assert found.item.name == "Daft Punk"

    def test_leading_article_in_the_catalog_name_does_not_matter(self):
        assert replay("bare_band_without_article").item.name == "The Beatles"

    def test_album_name_plays_the_album(self):
        found = replay("bare_album")
        assert (found.kind, found.item.name, found.item.artist) == (Kind.ALBUM, "Abbey Road", "The Beatles")

    def test_name_by_artist_tries_track_then_album(self):
        found = replay("bare_album_by_artist")
        assert (found.kind, found.item.name) == (Kind.ALBUM, "Discovery")
        assert not found.different_artist

    def test_track_by_artist(self):
        found = replay("bare_track_by_artist")
        assert (found.kind, found.item.name, found.item.artist) == (Kind.TRACK, "One More Time", "Daft Punk")

    def test_nonsense_is_not_found(self):
        found = replay("bare_nonsense")
        assert not found.found
        assert found.kind is Kind.UNKNOWN

    def test_title_containing_the_separator_does_not_fall_through_to_a_podcast(self):
        found = replay("title_with_separator")
        assert not found.found


class TestTypedRequests:
    def test_artist(self):
        assert replay("artist_explicit").item.name == "Carbon Leaf"

    def test_album(self):
        found = replay("album_explicit")
        assert (found.item.name, found.item.artist, found.alternatives) == ("Echo Echo", "Carbon Leaf", 0)

    def test_album_with_matching_artist_is_not_flagged(self):
        assert not replay("album_with_artist").different_artist

    def test_album_by_the_wrong_artist_still_plays_and_is_flagged(self):
        found = replay("album_wrong_artist")
        assert found.item.name == "Echo Echo"
        assert found.different_artist
        assert found.requested_artist == "the beatles"

    def test_ambiguous_album_name_is_settled_by_the_server(self):
        found = replay("album_ambiguous")
        assert found.item.name == "Abbey Road"

    def test_track(self):
        assert replay("track_explicit").item.name == "One More Time"

    def test_track_by_the_wrong_artist_plays_the_version_in_the_library(self):
        found = replay("track_wrong_artist")
        assert found.item.artist == "Daft Punk"
        assert found.different_artist

    def test_playlist(self):
        found = replay("playlist_explicit")
        assert (found.kind, found.item.name) == (Kind.PLAYLIST, "Art of Concentration")

    def test_playlist_name_tolerates_a_missing_apostrophe(self):
        assert replay("playlist_fuzzy").item.name == "Dad’s Music"


class TestGenreAndRandom:
    def test_genre_without_track_tags_falls_back_to_a_few_albums(self):
        found = replay("genre_jazz")
        assert found.kind is Kind.GENRE
        assert found.label == "Jazz"
        assert 0 < len(found.uris) <= 5
        assert all("album" in uri for uri in found.uris)

    def test_band_name_said_as_a_genre_plays_the_band(self):
        found = replay("genre_is_a_band")
        assert (found.kind, found.item.name) == (Kind.ARTIST, "Daft Punk")

    def test_genre_noise_means_random(self):
        found = replay("genre_noise")
        assert found.kind is Kind.RANDOM
        assert len(found.uris) == 50

    def test_random_sample(self):
        found = replay("random")
        assert len(found.uris) == 50
        assert len(set(found.uris)) == 50


class TestRadio:
    def test_station_name_with_slogan_resolves_to_the_station(self):
        found = replay("radio_named")
        assert (found.kind, found.item.name) == (Kind.RADIO, "BBC Radio 1")

    def test_short_station_name_gets_the_radio_word_inserted(self):
        assert replay("radio_short").item.name == "BBC Radio 1"

    def test_country(self):
        found = replay("radio_category_country")
        assert len(found.uris) == 5
        assert all(uri.startswith("radiobrowser://radio/") for uri in found.uris)

    def test_language_folder_needs_the_lowercase_path(self):
        found = replay("radio_category_language")
        assert len(found.uris) == 5

    def test_tag(self):
        assert len(replay("radio_category_tag").uris) == 5

    def test_unknown_category(self):
        assert not replay("radio_category_unknown").found


class TestRecordings:
    def test_every_scenario_has_a_recording(self):
        missing = [name for name in SCENARIOS if not (FIXTURE_DIR / f"{name}.json").exists()]
        assert missing == []

    def test_unrecorded_call_fails_loudly(self):
        client = ReplayClient.load("bare_artist")
        with pytest.raises(UnrecordedCall):
            client.search_media("something never recorded")

    def test_recordings_hold_no_server_address(self):
        import json

        for path in FIXTURE_DIR.glob("*.json"):
            text = path.read_text()
            assert "192.168." not in text and "8095" not in text, path.name
            json.loads(text)

    def test_resolution_requires_a_kind(self):
        with pytest.raises(TypeError):
            Resolution()  # type: ignore[call-arg]  # pylint: disable=no-value-for-parameter

    def test_media_request_defaults(self):
        assert MediaRequest().kind is Kind.UNKNOWN

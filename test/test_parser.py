"""Grammar specification for the deterministic request parser.

Each row is (utterance, expected MediaRequest fields). The lexicon is the real
en-us resource set, so a change to a list file shows up here first.
"""

from pathlib import Path

import pytest

from skill_musicassistant.parser import Kind, Lexicon, MediaRequest, parse


LOCALE_DIR = Path(__file__).parent.parent / "skill_musicassistant" / "locale" / "en-us"
PLAYERS = {"kitchen speaker", "office speaker", "living room speaker", "kitchen"}


def _load_list(name: str):
    path = LOCALE_DIR / f"{name}.list"
    if not path.exists():
        return []
    return [line for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]


LEXICON = Lexicon.from_loader(_load_list)


def _parse(utterance: str) -> MediaRequest:
    return parse(utterance, LEXICON, is_player=lambda name: name in PLAYERS)


def req(kind, name="", artist="", location="", shuffle=False, radio_mode=False):
    return dict(kind=kind, name=name, artist=artist, location=location, shuffle=shuffle, radio_mode=radio_mode)


def _fields(request: MediaRequest) -> dict:
    return req(request.kind, request.name, request.artist, request.location, request.shuffle, request.radio_mode)


ROWS = [
    # bare names: the catalog decides the type
    ("play abbey road", req(Kind.UNKNOWN, "abbey road")),
    ("play the beatles", req(Kind.UNKNOWN, "beatles")),
    ("listen to daft punk", req(Kind.UNKNOWN, "daft punk")),
    ("put on discovery by daft punk", req(Kind.UNKNOWN, "discovery", artist="daft punk")),
    ("abbey road", req(Kind.UNKNOWN, "abbey road")),
    # explicit type words, leading and trailing
    ("play the album abbey road", req(Kind.ALBUM, "abbey road")),
    ("play album abbey road by the beatles", req(Kind.ALBUM, "abbey road", artist="beatles")),
    ("play the record abbey road by the band the beatles", req(Kind.ALBUM, "abbey road", artist="beatles")),
    ("play the song hey jude", req(Kind.TRACK, "hey jude")),
    ("play the track hey jude by the beatles", req(Kind.TRACK, "hey jude", artist="beatles")),
    ("play the artist radiohead", req(Kind.ARTIST, "radiohead")),
    ("play the band radiohead", req(Kind.ARTIST, "radiohead")),
    ("play songs by radiohead", req(Kind.ARTIST, "radiohead")),
    ("play music by the beatles", req(Kind.ARTIST, "beatles")),
    ("play the playlist focus", req(Kind.PLAYLIST, "focus")),
    ("play the focus playlist", req(Kind.PLAYLIST, "focus")),
    ("play focus playlist", req(Kind.PLAYLIST, "focus")),
    ("play the genre jazz", req(Kind.GENRE, "jazz")),
    # radio by name
    ("play the radio station kexp", req(Kind.RADIO, "kexp")),
    ("play radio kexp", req(Kind.RADIO, "kexp")),
    ("play kexp radio", req(Kind.RADIO, "kexp")),
    ("tune in to bbc radio 1", req(Kind.UNKNOWN, "bbc radio 1")),
    ("play bbc 1 radio", req(Kind.RADIO, "bbc 1")),
    # radio by category
    ("play radio from france", req(Kind.RADIO_CATEGORY, "france")),
    ("play some radio from france", req(Kind.RADIO_CATEGORY, "france")),
    ("play a radio station in french", req(Kind.RADIO_CATEGORY, "french")),
    ("play jazz radio stations", req(Kind.RADIO_CATEGORY, "jazz")),
    ("play radio stations in germany", req(Kind.RADIO_CATEGORY, "germany")),
    # genre by media noun; names that are not genres fall back in the catalog
    ("play jazz music", req(Kind.GENRE, "jazz")),
    ("play some jazz music", req(Kind.GENRE, "jazz")),
    ("play beatles music", req(Kind.GENRE, "beatles")),
    ("play hip hop songs", req(Kind.GENRE, "hip hop")),
    # random
    ("play some music", req(Kind.RANDOM)),
    ("play music", req(Kind.RANDOM)),
    ("play anything", req(Kind.RANDOM)),
    ("play me something", req(Kind.RANDOM)),
    ("shuffle my music", req(Kind.RANDOM, shuffle=True)),
    ("shuffle my library", req(Kind.RANDOM, shuffle=True)),
    # shuffle verb
    ("shuffle the album abbey road", req(Kind.ALBUM, "abbey road", shuffle=True)),
    ("shuffle radiohead", req(Kind.UNKNOWN, "radiohead", shuffle=True)),
    # location
    ("play abbey road on the kitchen speaker", req(Kind.UNKNOWN, "abbey road", location="kitchen speaker")),
    ("play the album abbey road in the office speaker", req(Kind.ALBUM, "abbey road", location="office speaker")),
    ("play jazz music in the kitchen", req(Kind.GENRE, "jazz", location="kitchen")),
    (
        "play hey jude by the beatles on the kitchen speaker",
        req(Kind.UNKNOWN, "hey jude", artist="beatles", location="kitchen speaker"),
    ),
    ("play lights on the hill", req(Kind.UNKNOWN, "lights on the hill")),
    ("play music for airports", req(Kind.UNKNOWN, "music for airports")),
    # radio mode
    ("play the album abbey road with radio mode", req(Kind.ALBUM, "abbey road", radio_mode=True)),
    (
        "play the album abbey road by the beatles using radio mode",
        req(Kind.ALBUM, "abbey road", artist="beatles", radio_mode=True),
    ),
    # titles that contain a separator word still parse; the catalog retries without the split
    ("play stand by me", req(Kind.UNKNOWN, "stand", artist="me")),
]


@pytest.mark.parametrize("utterance,expected", ROWS, ids=[row[0] for row in ROWS])
def test_grammar(utterance, expected):
    assert _fields(_parse(utterance)) == expected


class TestRawAndEmpty:
    def test_raw_keeps_original_text(self):
        assert _parse("Play Abbey Road").raw == "Play Abbey Road"

    def test_bare_verb_is_empty(self):
        request = _parse("play")
        assert request.is_empty
        assert request.kind is Kind.UNKNOWN

    def test_random_is_not_empty(self):
        assert not _parse("play some music").is_empty

    def test_bare_radio_word_is_empty(self):
        assert _parse("play the radio").is_empty


class TestLexicon:
    def test_missing_lists_give_empty_tuples(self):
        lexicon = Lexicon.from_loader(lambda name: [])
        assert lexicon.play_verbs == ()
        assert lexicon.artist_separators == ("by",)

    def test_phrases_are_lowercased_and_longest_first(self):
        lexicon = Lexicon.from_loader(lambda name: ["On", "on the"] if name == "location_prefixes" else [])
        assert lexicon.location_prefixes == ("on the", "on")

    def test_every_en_us_list_exists(self):
        from skill_musicassistant.parser import LEXICON_LISTS

        missing = [name for name in LEXICON_LISTS if not (LOCALE_DIR / f"{name}.list").exists()]
        assert missing == []

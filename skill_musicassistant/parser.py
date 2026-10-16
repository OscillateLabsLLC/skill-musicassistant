"""Deterministic parser from a spoken play request to a typed MediaRequest.

The parser knows words, not backends. Every word list comes from the locale
resources, so a new language adds list files rather than code. The table
tests in ``test/test_parser.py`` are the grammar specification.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, List, Optional, Tuple

from .request import ARTICLES, split_trailing_location, strip_articles, strip_filler, strip_leading_verb


class Kind(str, Enum):
    """What a request asks for; UNKNOWN leaves the decision to the catalog."""

    TRACK = "track"
    ALBUM = "album"
    ARTIST = "artist"
    PLAYLIST = "playlist"
    GENRE = "genre"
    RADIO = "radio"
    RADIO_CATEGORY = "radio_category"
    RANDOM = "random"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MediaRequest:
    """A parsed play request: what to look up, by whom, where, and how."""

    kind: Kind = Kind.UNKNOWN
    name: str = ""
    artist: str = ""
    location: str = ""
    shuffle: bool = False
    radio_mode: bool = False
    raw: str = ""

    @property
    def is_empty(self) -> bool:
        """True when nothing was asked for by name and it is not a random request."""
        return not self.name and self.kind is not Kind.RANDOM


# Every list the parser reads, by resource file stem
LEXICON_LISTS = (
    "play_verbs",
    "shuffle_verbs",
    "location_prefixes",
    "media_words",
    "random_words",
    "album_words",
    "track_words",
    "artist_words",
    "playlist_words",
    "radio_words",
    "radio_category_prefixes",
    "radio_category_suffixes",
    "genre_words",
    "artist_separators",
    "radio_mode_phrases",
)


@dataclass(frozen=True)
class Lexicon:  # pylint: disable=too-many-instance-attributes
    """Word lists for one language, one attribute per list file. Phrases are lower-cased, longest first."""

    play_verbs: Tuple[str, ...] = ()
    shuffle_verbs: Tuple[str, ...] = ()
    location_prefixes: Tuple[str, ...] = ()
    media_words: Tuple[str, ...] = ()
    random_words: Tuple[str, ...] = ()
    album_words: Tuple[str, ...] = ()
    track_words: Tuple[str, ...] = ()
    artist_words: Tuple[str, ...] = ()
    playlist_words: Tuple[str, ...] = ()
    radio_words: Tuple[str, ...] = ()
    radio_category_prefixes: Tuple[str, ...] = ()
    radio_category_suffixes: Tuple[str, ...] = ()
    genre_words: Tuple[str, ...] = ()
    artist_separators: Tuple[str, ...] = field(default=("by",))
    radio_mode_phrases: Tuple[str, ...] = ()

    @classmethod
    def from_loader(cls, load: Callable[[str], Iterable[str]]) -> "Lexicon":
        """Build from a function that returns the lines of a named list file."""
        values = {}
        for name in LEXICON_LISTS:
            phrases = _normalize(load(name) or [])
            if phrases or name != "artist_separators":
                values[name] = phrases
        return cls(**values)

    def typed(self) -> Tuple[Tuple[Kind, Tuple[str, ...]], ...]:
        """Type-word lists paired with the kind they announce."""
        return (
            (Kind.ALBUM, self.album_words),
            (Kind.TRACK, self.track_words),
            (Kind.ARTIST, self.artist_words),
            (Kind.PLAYLIST, self.playlist_words),
            (Kind.RADIO, self.radio_words),
            (Kind.GENRE, self.genre_words),
        )


def _normalize(phrases: Iterable[str]) -> Tuple[str, ...]:
    cleaned = {p.strip().lower() for p in phrases if p and p.strip()}
    return tuple(sorted(cleaned, key=len, reverse=True))


def parse(utterance: str, lexicon: Lexicon, is_player: Callable[[str], bool] = lambda _: False) -> MediaRequest:
    """Parse a whole utterance or a bare query.

    A leading play verb is optional so the same function serves the
    ``play {query}`` intent slot and the raw fallback utterance.
    """
    text = " ".join(utterance.lower().split())
    shuffle = strip_leading_verb(text, lexicon.shuffle_verbs) is not None
    query = strip_leading_verb(text, lexicon.play_verbs + lexicon.shuffle_verbs)
    if query is None:
        query = text
    query, radio_mode = _strip_trailing_phrase(query, lexicon.radio_mode_phrases)
    query, location = _split_location(query, lexicon, is_player)
    kind, name, artist = _classify(query, lexicon)
    return MediaRequest(
        kind=kind,
        name=name,
        artist=artist,
        location=location,
        shuffle=shuffle,
        radio_mode=radio_mode,
        raw=utterance.strip(),
    )


def _split_location(query: str, lexicon: Lexicon, is_player: Callable[[str], bool]) -> Tuple[str, str]:
    for remainder, location in split_trailing_location(query, lexicon.location_prefixes):
        if is_player(location):
            return remainder, location
    return query, ""


def _classify(query: str, lexicon: Lexicon) -> Tuple[Kind, str, str]:
    if _is_random(query, lexicon):
        return Kind.RANDOM, "", ""
    category = _radio_category(query, lexicon)
    if category:
        return Kind.RADIO_CATEGORY, category, ""
    kind, name = _strip_type_word(query, lexicon)
    name, artist = _split_artist(name, lexicon)
    if artist and kind is Kind.UNKNOWN and _is_random(name, lexicon):
        return Kind.ARTIST, strip_articles(artist), ""
    if kind is Kind.UNKNOWN:
        kind, name = _genre_by_media_word(name, lexicon)
    if kind is Kind.GENRE:
        name = strip_filler(name, lexicon.random_words, lexicon.media_words)
    return kind, strip_articles(name), strip_articles(artist)


def _is_random(query: str, lexicon: Lexicon) -> bool:
    words = query.split()
    filler = set(lexicon.random_words) | set(lexicon.media_words) | set(ARTICLES)
    return bool(words) and all(w in filler for w in words)


def _radio_category(query: str, lexicon: Lexicon) -> str:
    for prefix in lexicon.radio_category_prefixes:
        if query.startswith(prefix + " "):
            return query[len(prefix) :].strip()
    for suffix in lexicon.radio_category_suffixes:
        if query.endswith(" " + suffix):
            return query[: -len(suffix)].strip()
    return ""


def _strip_type_word(query: str, lexicon: Lexicon) -> Tuple[Kind, str]:
    """ "the album abbey road" -> (ALBUM, "abbey road"); "focus playlist" -> (PLAYLIST, "focus")."""
    words = query.split()
    for kind, type_words in lexicon.typed():
        for phrase in type_words:
            phrase_words = phrase.split()
            start = _leading_phrase_start(words, phrase_words)
            if start is not None and len(words) > start + len(phrase_words):
                return kind, " ".join(words[start + len(phrase_words) :])
            if len(words) > len(phrase_words) and words[-len(phrase_words) :] == phrase_words:
                return kind, " ".join(words[: -len(phrase_words)])
    return Kind.UNKNOWN, query


def _leading_phrase_start(words: List[str], phrase_words: List[str]) -> Optional[int]:
    start = 1 if words and words[0] in ARTICLES else 0
    if words[start : start + len(phrase_words)] == phrase_words:
        return start
    return None


def _split_artist(name: str, lexicon: Lexicon) -> Tuple[str, str]:
    """Split at the last artist separator; a trailing artist type word is dropped."""
    words = name.split()
    for separator in lexicon.artist_separators:
        sep_words = separator.split()
        for start in range(len(words) - len(sep_words), 0, -1):
            if words[start : start + len(sep_words)] != sep_words:
                continue
            artist = " ".join(words[start + len(sep_words) :])
            if not artist:
                break
            artist = _strip_type_word_of(artist, lexicon.artist_words)
            return " ".join(words[:start]), artist
    return name, ""


def _strip_type_word_of(text: str, type_words: Tuple[str, ...]) -> str:
    words = text.split()
    for phrase in type_words:
        phrase_words = phrase.split()
        start = _leading_phrase_start(words, phrase_words)
        if start is not None and len(words) > start + len(phrase_words):
            return " ".join(words[start + len(phrase_words) :])
    return text


def _genre_by_media_word(name: str, lexicon: Lexicon) -> Tuple[Kind, str]:
    """ "beatles music" -> (GENRE, "beatles"): the catalog falls back to a name lookup."""
    words = name.split()
    if len(words) > 1 and words[-1] in lexicon.media_words:
        return Kind.GENRE, " ".join(words[:-1])
    return Kind.UNKNOWN, name


def _strip_trailing_phrase(query: str, phrases: Tuple[str, ...]) -> Tuple[str, bool]:
    for phrase in phrases:
        if query.endswith(" " + phrase):
            return query[: -len(phrase)].strip(), True
    return query, False

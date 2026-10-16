"""Turn spoken music requests into structured pieces.

Nothing here knows about Music Assistant, so a skill with a different backend
can reuse the same parsing and the same spoken-feedback rules.
"""

from typing import Iterable, List, Optional, Tuple

from rapidfuzz import fuzz, utils as fuzz_utils


# Below this WRatio score two artist names are treated as different people
ARTIST_MATCH_CONFIDENCE = 80


def strip_leading_verb(utterance: str, verbs: Iterable[str]) -> Optional[str]:
    """Return what follows a leading play verb, or None when the utterance has none.

    Longer verbs are tried first so "listen to" wins over a hypothetical "listen".
    """
    text = utterance.strip().lower()
    for verb in sorted((v.strip().lower() for v in verbs if v.strip()), key=len, reverse=True):
        if text == verb:
            return ""
        if text.startswith(verb + " "):
            return text[len(verb) :].strip()
    return None


def split_trailing_location(query: str, prefixes: Iterable[str]) -> List[Tuple[str, str]]:
    """Candidate (query, location) splits at the last "on the X" / "in the X" phrase.

    Callers check each location against their known players and keep the first
    that matches; an empty list means the query has no location phrase.
    """
    words = query.strip().split()
    splits: List[Tuple[str, str]] = []
    for prefix in sorted((p.strip().lower() for p in prefixes if p.strip()), key=len, reverse=True):
        prefix_words = prefix.split()
        for start in range(len(words) - len(prefix_words), 0, -1):
            if [w.lower() for w in words[start : start + len(prefix_words)]] != prefix_words:
                continue
            location = " ".join(words[start + len(prefix_words) :])
            if location:
                splits.append((" ".join(words[:start]), location))
            break
    return splits


# Leading articles never decide whether a spoken name is the catalog's name
ARTICLES = ("the", "a", "an")


def strip_articles(text: str) -> str:
    """Drop leading articles: "the beatles" -> "beatles"."""
    words = text.strip().lower().split()
    while words and words[0] in ARTICLES:
        words.pop(0)
    return " ".join(words)


def name_similarity(spoken: str, name: str) -> float:
    """Whole-name similarity, 0-100, with leading articles ignored.

    A whole-string ratio, not a partial one: "daft punk" must not score as
    the genre "Punk", and "hallelujah" must not score as the station
    "104.3 Hallelujah FM".
    """
    return fuzz.ratio(strip_articles(spoken), strip_articles(name), processor=fuzz_utils.default_process)


def radio_similarity(spoken: str, name: str) -> float:
    """Station-name similarity, 0-100, tolerant of the slogan stations append.

    Catalog names look like "BBC RADIO 1 - The biggest new pop and all-day vibes",
    so the spoken words only have to be a subset of the name's words.
    """
    return fuzz.token_set_ratio(strip_articles(spoken), strip_articles(name), processor=fuzz_utils.default_process)


def strip_filler(text: str, leading: Iterable[str], trailing: Iterable[str]) -> str:
    """Drop filler words from the ends of a slot: "some beatles music" -> "beatles".

    Leading words come from the random-word list ("some", "any"); trailing ones
    are the media nouns a genre pattern leaves behind ("music", "songs").
    """
    words = text.strip().lower().split()
    lead = {w.strip().lower() for w in leading if w.strip()}
    trail = {w.strip().lower() for w in trailing if w.strip()}
    while words and words[0] in lead:
        words.pop(0)
    while words and words[-1] in trail:
        words.pop()
    return " ".join(words)


# Station catalog names append a slogan after one of these separators
STATION_SEPARATORS = (" - ", " | ", ": ")


def spoken_station_name(name: str) -> str:
    """The part of a station name worth saying: "BBC RADIO 1 - The biggest ..." -> "BBC RADIO 1"."""
    cleaned = name.strip()
    for separator in STATION_SEPARATORS:
        if separator in cleaned:
            cleaned = cleaned.split(separator, 1)[0].strip()
    return cleaned or name.strip()


def same_artist(requested: Optional[str], actual: Optional[str]) -> bool:
    """True when the artist that was asked for is plausibly the one that was found."""
    if not requested or not actual:
        return True
    score = fuzz.WRatio(requested, actual, processor=fuzz_utils.default_process)
    return score >= ARTIST_MATCH_CONFIDENCE

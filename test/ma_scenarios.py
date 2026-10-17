"""Requests the resolver is recorded and tested against.

Names reference the library the recordings were made from; re-recording
against another library means revisiting the expectations in the contract
tests as well.
"""

from skill_musicassistant.parser import Kind, MediaRequest


SCENARIOS = {
    # no type word: the server and the ranking decide
    "bare_artist": MediaRequest(Kind.UNKNOWN, "daft punk"),
    "bare_band_without_article": MediaRequest(Kind.UNKNOWN, "beatles"),
    "bare_album": MediaRequest(Kind.UNKNOWN, "abbey road"),
    "bare_album_by_artist": MediaRequest(Kind.UNKNOWN, "discovery", artist="daft punk"),
    "bare_track_by_artist": MediaRequest(Kind.UNKNOWN, "one more time", artist="daft punk"),
    "bare_nonsense": MediaRequest(Kind.UNKNOWN, "zorblax quibbleflap"),
    "title_with_separator": MediaRequest(Kind.UNKNOWN, "stand", artist="me"),
    # explicit type words
    "artist_explicit": MediaRequest(Kind.ARTIST, "carbon leaf"),
    "album_explicit": MediaRequest(Kind.ALBUM, "echo echo"),
    "album_with_artist": MediaRequest(Kind.ALBUM, "echo echo", artist="carbon leaf"),
    "album_wrong_artist": MediaRequest(Kind.ALBUM, "echo echo", artist="the beatles"),
    "album_ambiguous": MediaRequest(Kind.ALBUM, "abbey road"),
    "track_explicit": MediaRequest(Kind.TRACK, "one more time"),
    "track_wrong_artist": MediaRequest(Kind.TRACK, "one more time", artist="radiohead"),
    "playlist_explicit": MediaRequest(Kind.PLAYLIST, "art of concentration"),
    "playlist_fuzzy": MediaRequest(Kind.PLAYLIST, "dads music"),
    # genre, with the fallbacks "play X music" relies on
    "genre_jazz": MediaRequest(Kind.GENRE, "jazz"),
    "genre_is_a_band": MediaRequest(Kind.GENRE, "daft punk"),
    "genre_noise": MediaRequest(Kind.GENRE, "in"),
    "random": MediaRequest(Kind.RANDOM),
    # radio
    "radio_named": MediaRequest(Kind.RADIO, "bbc radio 1"),
    "radio_short": MediaRequest(Kind.RADIO, "bbc 1"),
    "radio_category_country": MediaRequest(Kind.RADIO_CATEGORY, "france"),
    "radio_category_language": MediaRequest(Kind.RADIO_CATEGORY, "french"),
    "radio_category_tag": MediaRequest(Kind.RADIO_CATEGORY, "jazz"),
    "radio_category_unknown": MediaRequest(Kind.RADIO_CATEGORY, "zorblax"),
}

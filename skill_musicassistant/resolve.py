"""Turn a MediaRequest into something playable.

Every ranking and fallback rule that decides *what* plays lives here, on top
of the lookup primitives in ``catalog``. The contract tests in
``test/test_resolve_contract.py`` replay recorded server responses through
this module, so a server-side change shows up as a failing scenario.
"""

# every resolver takes (lookup, request, limits) so the dispatch table can call any of them
# pylint: disable=unused-argument
import logging
from dataclasses import dataclass, replace
from typing import Callable, Dict, Optional, Tuple

from skill_musicassistant import catalog
from skill_musicassistant.catalog import ResolvedItem
from skill_musicassistant.parser import Kind, MediaRequest
from skill_musicassistant.request import same_artist


log = logging.getLogger(__name__)

# A genre word shorter than this is STT noise ("play in music") and means random
MIN_GENRE_LENGTH = 3

_KIND_BY_MEDIA_TYPE = {
    "track": Kind.TRACK,
    "album": Kind.ALBUM,
    "artist": Kind.ARTIST,
    "playlist": Kind.PLAYLIST,
    "radio": Kind.RADIO,
}


@dataclass(frozen=True)
class Limits:
    """How much a list request queues; shuffle makes a sample feel endless enough."""

    genre_tracks: int = 50
    random_tracks: int = 50
    radio_stations: int = 5


@dataclass(frozen=True)
class Resolution:
    """What the catalog found for a request, in the shape the play pipeline needs."""

    kind: Kind
    item: Optional[ResolvedItem] = None
    uris: Tuple[str, ...] = ()
    label: str = ""
    alternatives: int = 0
    requested_artist: str = ""
    # lookups the server failed on the way here; with nothing found, the failure is the answer
    failed_lookups: int = 0

    @property
    def found(self) -> bool:
        """True when there is something to play."""
        return self.item is not None or bool(self.uris)

    @property
    def different_artist(self) -> bool:
        """True when the artist asked for is not the one whose item will play."""
        if not self.requested_artist or self.item is None:
            return False
        return not same_artist(self.requested_artist, self.item.artist)


class _Lookups:  # pylint: disable=too-few-public-methods  # a callable with state, not a service
    """Runs catalog lookups against one client and counts the ones the server failed.

    A failure returns None so the next fallback gets its turn; the count lets
    the skill tell "nothing matched" from "the server did not answer" instead
    of reporting every error as not found.
    """

    def __init__(self, client):
        self.client = client
        self.failures = 0

    def __call__(self, lookup: Callable, *args):
        try:
            return lookup(self.client, *args)
        except Exception as e:
            self.failures += 1
            log.warning("Catalog lookup %s failed: %s", getattr(lookup, "__name__", lookup), e, exc_info=True)
            return None


def resolve(client, request: MediaRequest, limits: Limits = Limits()) -> Resolution:
    """Resolve a parsed request against the server.

    Never raises for server errors: a failed lookup is counted in
    ``failed_lookups`` and the next fallback rule gets its turn.
    """
    lookup = _Lookups(client)
    resolver = _RESOLVERS.get(request.kind, _resolve_unknown)
    return replace(resolver(lookup, request, limits), failed_lookups=lookup.failures)


def _resolve_random(lookup: _Lookups, request: MediaRequest, limits: Limits) -> Resolution:
    uris = lookup(catalog.random_track_uris, limits.random_tracks) or []
    return Resolution(Kind.RANDOM, uris=tuple(uris))


def _resolve_genre(lookup: _Lookups, request: MediaRequest, limits: Limits) -> Resolution:
    """A library genre, or whatever the name turns out to be ("play beatles music")."""
    if len(request.name) < MIN_GENRE_LENGTH:
        return _resolve_random(lookup, request, limits)
    genre = lookup(catalog.find_genre, request.name)
    if genre:
        uris = lookup(catalog.genre_uris, genre, limits.genre_tracks) or []
        return Resolution(Kind.GENRE, uris=tuple(uris), label=genre.get("name") or request.name)
    by_name = _resolve_unknown(lookup, request, limits)
    if by_name.found:
        return by_name
    return Resolution(Kind.GENRE, label=request.name)


def _resolve_radio_category(lookup: _Lookups, request: MediaRequest, limits: Limits) -> Resolution:
    uris = lookup(catalog.radio_category_station_uris, request.name, limits.radio_stations) or []
    return Resolution(Kind.RADIO_CATEGORY, uris=tuple(uris), label=request.name)


def _resolve_radio(lookup: _Lookups, request: MediaRequest, limits: Limits) -> Resolution:
    item = lookup(catalog.search_radio, request.name, _with_radio_word(request.name))
    return Resolution(Kind.RADIO, item=item)


def _with_radio_word(spoken: str) -> str:
    """ "bbc 1" inside a radio request means "bbc 1 radio", which outranks "bbc 1 tv"."""
    return spoken if "radio" in spoken.lower().split() else f"{spoken} radio"


def _resolve_track(lookup: _Lookups, request: MediaRequest, limits: Limits) -> Resolution:
    artist = request.artist or None
    item = lookup(catalog.resolve_track, request.name, artist)
    if not item:
        item = _first_by_artist(lookup(catalog.search_tracks, request.name) or [], artist)
    if not item and artist:
        item = lookup(catalog.resolve_track, request.name)
    return Resolution(Kind.TRACK, item=item, requested_artist=request.artist)


def _resolve_album(lookup: _Lookups, request: MediaRequest, limits: Limits) -> Resolution:
    artist = request.artist or None
    item = lookup(catalog.resolve_album, request.name, artist)
    alternatives = 0
    if not item:
        albums = lookup(catalog.search_albums, request.name) or []
        item = _first_by_artist(albums, artist)
        if item and not artist:
            alternatives = len(albums) - 1
    if not item and artist:
        item = lookup(catalog.resolve_album, request.name)
    return Resolution(Kind.ALBUM, item=item, alternatives=alternatives, requested_artist=request.artist)


def _first_by_artist(items, artist: Optional[str]) -> Optional[ResolvedItem]:
    """The first item by the requested artist, or the first item at all when none is."""
    if artist:
        items = [i for i in items if same_artist(artist, i.artist)] or items
    return items[0] if items else None


def _resolve_artist(lookup: _Lookups, request: MediaRequest, limits: Limits) -> Resolution:
    item = lookup(catalog.resolve_artist, request.name)
    if not item:
        artists = lookup(catalog.search_artists, request.name) or []
        item = artists[0] if artists else None
    return Resolution(Kind.ARTIST, item=item)


def _resolve_playlist(lookup: _Lookups, request: MediaRequest, limits: Limits) -> Resolution:
    ref = lookup(catalog.find_playlist, request.name)
    item = ResolvedItem(name=ref.name, uri=ref.uri, media_type="playlist") if ref else None
    if not item:
        playlists = lookup(catalog.search_playlists, request.name) or []
        item = playlists[0] if playlists else None
    return Resolution(Kind.PLAYLIST, item=item)


def _resolve_unknown(lookup: _Lookups, request: MediaRequest, limits: Limits) -> Resolution:
    """No type word: the server decides, artist before album before track."""
    if request.artist:
        item = lookup(catalog.resolve_track, request.name, request.artist)
        if not item:
            item = lookup(catalog.resolve_album, request.name, request.artist)
        if not item:
            # the separator may be part of a title: "stand by me"
            item = lookup(catalog.resolve_generic, f"{request.name} by {request.artist}")
    else:
        item = lookup(catalog.resolve_generic, request.name)
    kind = _KIND_BY_MEDIA_TYPE.get(item.media_type, Kind.UNKNOWN) if item else Kind.UNKNOWN
    return Resolution(kind, item=item, requested_artist=request.artist)


_RESOLVERS: Dict[Kind, Callable[..., Resolution]] = {
    Kind.RANDOM: _resolve_random,
    Kind.GENRE: _resolve_genre,
    Kind.RADIO_CATEGORY: _resolve_radio_category,
    Kind.RADIO: _resolve_radio,
    Kind.TRACK: _resolve_track,
    Kind.ALBUM: _resolve_album,
    Kind.ARTIST: _resolve_artist,
    Kind.PLAYLIST: _resolve_playlist,
    Kind.UNKNOWN: _resolve_unknown,
}

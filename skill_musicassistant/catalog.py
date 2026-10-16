"""Music Assistant lookups that return small, backend-neutral results.

Handlers in the skill speak and play; they never read raw server payloads.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ma_http_client import SORT_RANDOM
from music_assistant_models.enums import MediaType
from rapidfuzz import fuzz, process, utils as fuzz_utils

from skill_musicassistant.request import name_similarity, radio_similarity


@dataclass
class ResolvedItem:
    """One playable thing the server matched for a request."""

    name: str
    uri: str
    media_type: str
    artist: Optional[str] = None

    @classmethod
    def from_dict(cls, item: Dict[str, Any]) -> "ResolvedItem":
        name = item.get("name") or ""
        media_type = str(item.get("media_type") or "")
        artist = name if media_type == "artist" else _first_artist(item)
        return cls(name=name, uri=item.get("uri") or "", media_type=media_type, artist=artist)


# Spoken in place of a title when a stream reports none
UNTITLED = "an untitled track"


@dataclass
class NowPlaying:
    """What a player is currently rendering."""

    title: str
    artist: Optional[str]
    album: Optional[str]
    uri: Optional[str]
    station: Optional[str] = None
    is_radio: bool = False


def _first_artist(item: Dict[str, Any]) -> Optional[str]:
    artists = item.get("artists") or []
    if artists and isinstance(artists[0], dict):
        return artists[0].get("name")
    artist = item.get("artist")
    if isinstance(artist, dict):
        return artist.get("name")
    return artist if isinstance(artist, str) else None


def _resolved(item: Optional[Dict[str, Any]]) -> Optional[ResolvedItem]:
    if not item or not item.get("uri"):
        return None
    return ResolvedItem.from_dict(item)


# Below this whole-name similarity a search hit is not what a bare "play X" meant
GENERIC_MATCH_CONFIDENCE = 85
# Bare requests resolve in minimy's order: an artist beats an album beats a track of the same name;
# radio stations come last because their catalog names are rarely what people say
_SEARCH_BUCKETS = (
    ("artists", "artist"),
    ("albums", "album"),
    ("playlists", "playlist"),
    ("tracks", "track"),
    ("radio", "radio"),
)


def best_named(
    items: List[Dict[str, Any]], spoken: str, cutoff: float, scorer=name_similarity
) -> Optional[Dict[str, Any]]:
    """The item whose name is closest to ``spoken`` under ``scorer``, or None below ``cutoff``."""
    named = [item for item in items if isinstance(item, dict) and item.get("name")]
    scored = [(scorer(spoken, item["name"]), item) for item in named]
    best = max(scored, key=lambda pair: pair[0], default=None)
    return best[1] if best and best[0] >= cutoff else None


# Radio names are "NAME - slogan", so the station bucket uses the word-subset scorer
RADIO_MATCH_CONFIDENCE = 90
_BUCKET_SCORERS = {"radio": radio_similarity}


def search_radio(client, spoken: str, rank_as: Optional[str] = None) -> Optional[ResolvedItem]:
    """The radio station whose name best fits the request.

    The server searches by substring, so the query is the raw spoken name;
    ranking may use a fuller phrase (``rank_as``), such as the name plus the
    word "radio" the intent stripped. A named request always gets the best
    candidate.
    """
    stations: Dict[str, Dict[str, Any]] = {}
    for query in radio_query_variants(spoken):
        results = client.search_media(query=query, media_types=[MediaType.RADIO], limit=10)
        for station in (results or {}).get("radio") or []:
            if isinstance(station, dict) and station.get("uri"):
                stations.setdefault(station["uri"], station)
    best = best_named(list(stations.values()), rank_as or spoken, cutoff=0, scorer=radio_similarity)
    return _resolved({**best, "media_type": "radio"}) if best else None


# Longer spoken names are specific enough; variants only help short ones like "bbc 1"
MAX_WORDS_FOR_RADIO_VARIANTS = 3


def radio_query_variants(spoken: str) -> List[str]:
    """The spoken name, then the name with "radio" inserted at each position.

    The server search is a substring match, so "bbc 1" never returns
    "BBC Radio 1"; "bbc radio 1" does.
    """
    words = spoken.split()
    variants = [spoken]
    if "radio" in (w.lower() for w in words) or len(words) > MAX_WORDS_FOR_RADIO_VARIANTS:
        return variants
    for position in range(len(words) + 1):
        variants.append(" ".join(words[:position] + ["radio"] + words[position:]))
    return variants


def resolve_generic(client, query: str) -> Optional[ResolvedItem]:
    """Best item of any type for a bare request.

    A confident name match in the free-text search wins, artist first, so
    "beatles" plays The Beatles rather than the one track the server would pick.
    Otherwise the server's own by-name lookup decides.
    """
    results = client.search_media(query=query, limit=5)
    if isinstance(results, dict):
        for bucket, media_type in _SEARCH_BUCKETS:
            scorer = _BUCKET_SCORERS.get(bucket, name_similarity)
            cutoff = RADIO_MATCH_CONFIDENCE if bucket == "radio" else GENERIC_MATCH_CONFIDENCE
            best = best_named(results.get(bucket) or [], query, cutoff, scorer)
            if best and best.get("uri"):
                return ResolvedItem.from_dict({**best, "media_type": media_type})
    return _resolved(client.get_item_by_name(query))


def resolve_track(client, name: str, artist: Optional[str] = None) -> Optional[ResolvedItem]:
    return _resolved(client.get_track_by_name(name, artist_name=artist))


def resolve_album(client, name: str, artist: Optional[str] = None) -> Optional[ResolvedItem]:
    return _resolved(client.get_item_by_name(name, artist=artist, media_type=MediaType.ALBUM))


def search_albums(client, name: str, limit: int = 5) -> List[ResolvedItem]:
    """Every album the free-text search returns for a name, best match first."""
    results = client.search_media(query=name, media_types=[MediaType.ALBUM], limit=limit)
    return [ResolvedItem.from_dict(a) for a in results.get("albums", []) if a.get("uri")]


def _radio_now_playing(stream_title: str, station: Optional[str], uri: Optional[str]) -> NowPlaying:
    """For a station the album field holds its name and the title is stream metadata, often junk."""
    station_name = station or stream_title or UNTITLED
    song = stream_title if " - " in stream_title else None
    return NowPlaying(
        title=song or station_name, artist=None, album=None, uri=uri, station=station_name, is_radio=True
    )

def _uris(items: List[Dict[str, Any]]) -> List[str]:
    return [item["uri"] for item in items if item.get("uri")]


# Below this WRatio score a spoken word is not one of the library's genres
GENRE_MATCH_CONFIDENCE = 85


def find_genre(client, spoken: str) -> Optional[Dict[str, Any]]:
    """The library genre whose name best matches ``spoken``, or None.

    The server's genre search returns an unranked, alias-widened set ("jazz"
    comes back with Blues, Funk and Hip Hop beside Jazz), so the pick is made
    here by name. A miss on the search falls back to the whole genre list.
    """
    candidates = client.search_genres(spoken, limit=25)
    best = _best_genre(candidates, spoken)
    if best is None:
        best = _best_genre(client.send_command("music/genres/library_items", limit=500), spoken)
    return best


def _best_genre(genres: List[Dict[str, Any]], spoken: str) -> Optional[Dict[str, Any]]:
    """Whole-name match only: "daft punk" is not the genre "Punk" and "discovery" is not "Disco"."""
    return best_named(genres, spoken, GENRE_MATCH_CONFIDENCE)


# Albums expand to many tracks server side, and a long list makes the server resolve them all before playing
GENRE_ALBUM_LIMIT = 5


def genre_uris(client, genre: Dict[str, Any], limit: int) -> List[str]:
    """Playable uris for a genre: a random track sample, or a few of its albums when tracks carry no genre tags."""
    tracks = _uris(client.genre_tracks(genre["item_id"], limit=limit, sort_field=SORT_RANDOM))
    if tracks:
        return tracks
    albums = _uris(client.genre_albums(genre["item_id"], limit=limit, sort_field=SORT_RANDOM))
    return albums[:GENRE_ALBUM_LIMIT]


def random_track_uris(client, limit: int) -> List[str]:
    """A random sample of library tracks."""
    return _uris(client.library_items(MediaType.TRACK, limit=limit, sort_field=SORT_RANDOM))


@dataclass
class PlaylistRef:
    """A library playlist the user can add to, remove from, or ask about."""

    item_id: str
    name: str
    uri: str

    @classmethod
    def from_dict(cls, item: Dict[str, Any]) -> "PlaylistRef":
        return cls(item_id=str(item.get("item_id") or ""), name=item.get("name") or "", uri=item.get("uri") or "")


# Below this WRatio score a spoken playlist name is not the one in the library
PLAYLIST_MATCH_CONFIDENCE = 70


def find_playlist(client, name: str) -> Optional[PlaylistRef]:
    """The library playlist whose name best matches ``name``, or None."""
    candidates = [PlaylistRef.from_dict(p) for p in client.library_playlists(search=name, limit=10)]
    if not candidates:
        return None
    match = process.extractOne(
        name,
        [c.name for c in candidates],
        scorer=fuzz.WRatio,
        processor=fuzz_utils.default_process,
        score_cutoff=PLAYLIST_MATCH_CONFIDENCE,
    )
    return candidates[match[2]] if match else None


def create_playlist(client, name: str) -> PlaylistRef:
    return PlaylistRef.from_dict(client.create_playlist(name))


def list_playlists(client, limit: int = 50) -> List[PlaylistRef]:
    return [PlaylistRef.from_dict(p) for p in client.library_playlists(limit=limit)]


def playlist_track_titles(client, playlist: PlaylistRef) -> List[str]:
    """Titles of a playlist's tracks in order."""
    return [t.get("name") or "" for t in client.playlist_tracks(playlist.item_id)]


def positions_of(client, playlist: PlaylistRef, now: NowPlaying) -> List[int]:
    """Where the current track sits in a playlist, by uri first, then by title and artist."""
    tracks = client.playlist_tracks(playlist.item_id)
    by_uri = [i for i, t in enumerate(tracks) if now.uri and t.get("uri") == now.uri]
    if by_uri:
        return by_uri
    return [
        i
        for i, t in enumerate(tracks)
        if (t.get("name") or "").lower() == now.title.lower() and _same_or_missing(_first_artist(t), now.artist)
    ]


def _same_or_missing(a: Optional[str], b: Optional[str]) -> bool:
    return not a or not b or a.lower() == b.lower()


def now_playing_for(client, player_id: str) -> Optional[NowPlaying]:
    """Current media on a player, or None when it is idle."""
    for player in client.get_players():
        if player.player_id != player_id:
            continue
        media = getattr(player, "current_media", None)
        if not media:
            return None
        title = (getattr(media, "title", None) or "").strip()
        album = getattr(media, "album", None)
        uri = getattr(media, "uri", None)
        if not title and not uri:
            return None
        if "radio" in str(getattr(media, "media_type", "") or "").lower():
            return _radio_now_playing(title, album, uri)
        return NowPlaying(
            # some streams carry no title; the album or the item uri is still worth speaking
            title=title or album or UNTITLED,
            artist=getattr(media, "artist", None),
            album=album,
            uri=uri,
        )
    return None

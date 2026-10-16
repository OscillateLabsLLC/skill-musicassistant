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
        """Adapt a server item dict; an artist is its own artist."""
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


# What a music request may resolve to; the server's by-name lookup also knows podcasts and audiobooks
MUSIC_MEDIA_TYPES = frozenset({"track", "album", "artist", "playlist", "radio"})


def _resolved(item: Optional[Dict[str, Any]]) -> Optional[ResolvedItem]:
    if not item or not item.get("uri"):
        return None
    if str(item.get("media_type") or "") not in MUSIC_MEDIA_TYPES:
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
    """Server-side track lookup by title, optionally narrowed to an artist."""
    return _resolved(client.get_track_by_name(name, artist_name=artist))


def resolve_album(client, name: str, artist: Optional[str] = None) -> Optional[ResolvedItem]:
    """Server-side album lookup by name, optionally narrowed to an artist."""
    return _resolved(client.get_item_by_name(name, artist=artist, media_type=MediaType.ALBUM))


def resolve_artist(client, name: str) -> Optional[ResolvedItem]:
    """Server-side artist lookup by name."""
    return _resolved(client.get_item_by_name(name, media_type=MediaType.ARTIST))


def _search_bucket(client, name: str, media_type: MediaType, bucket: str, limit: int) -> List[ResolvedItem]:
    """Every item of one type the free-text search returns for a name, server order."""
    results = client.search_media(query=name, media_types=[media_type], limit=limit) or {}
    items = [
        ResolvedItem.from_dict({**i, "media_type": media_type.value}) for i in results.get(bucket, []) if i.get("uri")
    ]
    return items


def search_albums(client, name: str, limit: int = 5) -> List[ResolvedItem]:
    """Albums the free-text search returns for a name, server order."""
    return _search_bucket(client, name, MediaType.ALBUM, "albums", limit)


def search_tracks(client, name: str, limit: int = 5) -> List[ResolvedItem]:
    """Tracks the free-text search returns for a title, server order."""
    return _search_bucket(client, name, MediaType.TRACK, "tracks", limit)


def search_artists(client, name: str, limit: int = 5) -> List[ResolvedItem]:
    """Artists the free-text search returns for a name, server order."""
    return _search_bucket(client, name, MediaType.ARTIST, "artists", limit)


def search_playlists(client, name: str, limit: int = 5) -> List[ResolvedItem]:
    """Playlists the free-text search returns for a name, server order."""
    return _search_bucket(client, name, MediaType.PLAYLIST, "playlists", limit)


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
        """Adapt a server playlist dict."""
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
    """Create a library playlist and return a reference to it."""
    return PlaylistRef.from_dict(client.create_playlist(name))


def list_playlists(client, limit: int = 50) -> List[PlaylistRef]:
    """The library playlists, server order."""
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
    """Case-insensitive equality that treats a missing side as a match."""
    return not a or not b or a.lower() == b.lower()


# radio-browser folders, in the order a spoken word is tried: "Spain" and "spanish" before the "jazz" tag
RADIO_BROWSER_CATEGORY_PATHS = (
    "radiobrowser://category/country",
    "radiobrowser://category/language",
    "radiobrowser://category/tag",
)
# Below this WRatio score a spoken word does not name a radio-browser country, language, or tag
RADIO_CATEGORY_MATCH_CONFIDENCE = 80


def _best_folder(folders: List[Dict[str, Any]], spoken: str):
    """(score, folder) for the folder whose name best matches, or None."""
    names = [f.get("name") or "" for f in folders]
    match = process.extractOne(
        spoken,
        names,
        scorer=fuzz.WRatio,
        processor=fuzz_utils.default_process,
        score_cutoff=RADIO_CATEGORY_MATCH_CONFIDENCE,
    )
    return (match[1], folders[match[2]]) if match else None


def _station_uri(item: Dict[str, Any]) -> Optional[str]:
    if item.get("uri"):
        return item["uri"]
    if item.get("item_id") and item.get("provider"):
        return f"{item['provider']}://radio/{item['item_id']}"
    return None


def radio_category_station_uris(client, spoken: str, limit: int) -> List[str]:
    """Stations for a spoken country, language, or genre tag, most popular first.

    radio-browser search is by station name only, so the category folders are
    browsed and the spoken word is fuzzy-matched against their names.
    """
    folder = _best_category_folder(client, spoken)
    if folder is None:
        return []
    stations = _folder_stations(client, folder.get("path") or "", limit)
    return [uri for uri in (_station_uri(s) for s in stations[:limit]) if uri]


def _best_category_folder(client, spoken: str) -> Optional[Dict[str, Any]]:
    """The country, language, or tag folder whose name best matches, across all three listings."""
    best_score, best_folder = -1.0, None
    for path in RADIO_BROWSER_CATEGORY_PATHS:
        match = _best_folder(client.browse(path, limit=1000), spoken)
        if match and match[0] > best_score:
            best_score, best_folder = match
    return best_folder


def _folder_stations(client, path: str, limit: int) -> List[Dict[str, Any]]:
    """Stations in a radio-browser folder.

    The listing starts with a ".." entry and may hold sub-folders; only
    stations are playable. Language folders are listed with a capitalised
    path ("language/French") that the provider serves empty, while the
    lowercase path works, so an empty listing is retried lowercased.
    """
    for candidate in _path_variants(path):
        listing = client.browse(candidate, limit=limit + 1)
        stations = [s for s in listing if str(s.get("media_type") or "") == "radio"]
        if stations:
            return stations
    return []


def _path_variants(path: str) -> List[str]:
    head, _, tail = path.rpartition("/")
    lowered = f"{head}/{tail.lower()}" if head else path.lower()
    return [path] if lowered == path else [path, lowered]


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

"""Music Assistant lookups that return small, backend-neutral results.

Handlers in the skill speak and play; they never read raw server payloads.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from music_assistant_models.enums import MediaType

from skill_musicassistant.request import name_similarity


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


def best_named(items: List[Dict[str, Any]], spoken: str, cutoff: float) -> Optional[Dict[str, Any]]:
    """The item whose whole name is closest to ``spoken``, or None below ``cutoff``."""
    named = [item for item in items if isinstance(item, dict) and item.get("name")]
    scored = [(name_similarity(spoken, item["name"]), item) for item in named]
    best = max(scored, key=lambda pair: pair[0], default=None)
    return best[1] if best and best[0] >= cutoff else None


def resolve_generic(client, query: str) -> Optional[ResolvedItem]:
    """Best item of any type for a bare request.

    A confident name match in the free-text search wins, artist first, so
    "beatles" plays The Beatles rather than the one track the server would pick.
    Otherwise the server's own by-name lookup decides.
    """
    results = client.search_media(query=query, limit=5)
    if isinstance(results, dict):
        for bucket, media_type in _SEARCH_BUCKETS:
            best = best_named(results.get(bucket) or [], query, GENERIC_MATCH_CONFIDENCE)
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
        return NowPlaying(
            # some streams carry no title; the album or the item uri is still worth speaking
            title=title or album or UNTITLED,
            artist=getattr(media, "artist", None),
            album=album,
            uri=uri,
        )
    return None

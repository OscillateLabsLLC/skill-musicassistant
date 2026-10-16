"""Music Assistant lookups that return small, backend-neutral results.

Handlers in the skill speak and play; they never read raw server payloads.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from music_assistant_models.enums import MediaType


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


def resolve_generic(client, query: str) -> Optional[ResolvedItem]:
    """Let the server pick the best item of any type for a bare request."""
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
        if not media or not getattr(media, "title", None):
            return None
        return NowPlaying(
            title=media.title,
            artist=getattr(media, "artist", None),
            album=getattr(media, "album", None),
            uri=getattr(media, "uri", None),
        )
    return None

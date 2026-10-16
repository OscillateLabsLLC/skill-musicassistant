"""What to say about a play request: the spoken-feedback policy in one place.

Pure functions from (request, resolution) to dialog names and data, so the
skill only calls ``speak_dialog`` on what comes back and a sibling skill with
another backend can reuse the same policy.
"""

from typing import List, Tuple

from skill_musicassistant.parser import Kind, MediaRequest
from skill_musicassistant.request import spoken_station_name
from skill_musicassistant.resolve import Resolution


Dialog = Tuple[str, dict]

UNKNOWN_ARTIST = "Unknown Artist"

_NOT_FOUND = {
    Kind.TRACK: ("could_not_find_track", "track"),
    Kind.ALBUM: ("could_not_find_album", "album"),
    Kind.ARTIST: ("could_not_find_artist", "artist"),
    Kind.PLAYLIST: ("could_not_find_playlist", "playlist"),
    Kind.GENRE: ("could_not_find_genre", "genre"),
    Kind.RADIO: ("could_not_find_radio", "station"),
    Kind.RADIO_CATEGORY: ("could_not_find_radio_category", "category"),
}


def not_found(request: MediaRequest) -> Dialog:
    """The not-found dialog for what was asked, naming the thing the way it was said."""
    if request.kind is Kind.RANDOM:
        return "library_empty", {}
    spoken = f"{request.name} {request.artist}".strip() if request.artist else request.name
    dialog, slot = _NOT_FOUND.get(request.kind, ("could_not_find_track", "track"))
    return dialog, {slot: spoken}


def could_not_play(request: MediaRequest) -> Dialog:
    """The dialog for a resolved item the server refused to play."""
    dialog, slot = _NOT_FOUND.get(request.kind, ("could_not_play_music", ""))
    if request.kind in (Kind.RANDOM, Kind.GENRE, Kind.RADIO_CATEGORY, Kind.UNKNOWN):
        return "could_not_play_music", {}
    return dialog.replace("could_not_find", "could_not_play"), {slot: request.name}


def playing(request: MediaRequest, found: Resolution) -> List[Dialog]:
    """Everything to say once playback started, caveats first."""
    dialogs: List[Dialog] = []
    if found.different_artist and found.item is not None:
        dialogs.append(
            (
                "playing_different_artist",
                {"requested": found.requested_artist, "actual": found.item.artist or UNKNOWN_ARTIST},
            )
        )
    if found.alternatives and found.item is not None:
        dialogs.append(("found_several_albums", {"count": found.alternatives + 1, "album": request.name}))
    dialogs.append(_playing_dialog(request, found))
    return dialogs


def _playing_dialog(request: MediaRequest, found: Resolution) -> Dialog:
    if found.kind is Kind.RANDOM:
        return "playing_random", {}
    if found.kind is Kind.GENRE:
        return "playing_genre", {"genre": found.label or request.name}
    if found.kind is Kind.RADIO_CATEGORY:
        return "playing_radio_category", {"category": found.label or request.name, "count": len(found.uris)}
    item = found.item
    if item is None:
        return "playing_generic", {"name": request.name}
    artist = item.artist or UNKNOWN_ARTIST
    if item.media_type == "track":
        return "playing", {"track_name": item.name, "artist_name": artist}
    if item.media_type == "artist":
        return "playing", {"track_name": "music", "artist_name": artist}
    if item.media_type == "album":
        return "playing_album", {"album": item.name, "artist": artist}
    if item.media_type == "playlist":
        return "playing_playlist", {"playlist": item.name}
    if item.media_type == "radio":
        return "playing_radio", {"radio": spoken_station_name(item.name)}
    return "playing_generic", {"name": item.name}

# Plan: borrow minimy's music UX for skill-musicassistant

Status: implemented in the 1.0 line (Phases 1 to 4). Kept as the design record.

## Why this document exists

Three code bases were compared in October 2026: minimy-mike99mac (an mpc/mpd
music skill), the 2026 rewrite of ovos-media, and ovos-ocp-pipeline-plugin.
The decision was to leave the OCP stack alone, put minimy's good ideas into
this skill first (Neon Hub runs it with OCP off), and later repackage the same
grammar as an ovos-media MediaProvider for OVOS 3.x.

## What minimy does well, and what this skill had before 1.0

| minimy capability | This skill before 1.0 |
|---|---|
| play track / album by artist, artist, playlist, radio, with location | Done. Nine Padatious intents. |
| bare "play X" with no type word, tries artist, then album, then title | Missing. Issue #8. |
| "play some jazz", "play genre jazz" | Missing. |
| "play some music", "play random music" | Missing. |
| says what it matched when it differs from the request | Missing. Only said "playing". |
| queue policy follows intent: one track = repeat off, artist or genre = shuffle and repeat on | Missing. Always QueueOption.PLAY with defaults. |
| playlist create, add track, remove track, list | Missing. |
| radio by country, language, or genre; "next station" | Missing. Radio was by station name only. |
| "what's playing" | Missing in both. The client already had get_player_state. |
| like a song | Missing in both. |

Minimy's matching itself is weaker than ours (mpc substring plus exact
lowercase filters, hardcoded CSV of 154 stations). The engine was not copied.
The grammar, the spoken feedback, and the queue policy were.

## Music Assistant API that each feature needs

Verified against music-assistant/server `dev` on 2026-10-15.

| Feature | Command | Notes |
|---|---|---|
| generic search | `music/search` (search_query, media_types, limit, providers) | Already wrapped as `search_media`. |
| by-name resolve | `music/item_by_name`, `music/track_by_name` (track_name, artist_name, album_name) | Server does the artist and album matching. |
| genre | `music/genres/library_items` (search), `music/genres/tracks`, `music/genres/albums` | Genre matching is alias-aware and normalized server side. |
| random library play | `music/tracks/library_items` with `sort_field` `random` | `SortField.RANDOM`; `RANDOM_PLAY_COUNT` also exists. |
| shuffle and repeat | `player_queues/play_media` (shuffle=bool), `player_queues/shuffle`, `player_queues/repeat` (RepeatMode) | shuffle on play_media applies only to PLAY and REPLACE. |
| now playing | `players/all` -> `current_media` | Title, artist, album, uri. |
| like | `music/favorites/add_item` (item uri) | |
| playlist create | `music/playlists/create_playlist` (name, provider_instance_or_domain) | Builtin provider is the safe default. |
| playlist add / remove | `music/playlists/add_playlist_tracks` (db_playlist_id, uris), `remove_playlist_tracks` (positions) | Remove needs the position, so list tracks first. |
| save queue as playlist | `player_queues/save_as_playlist` (queue_id, name) | One call. |
| list playlists | `music/playlists/library_items` (search) | |
| radio by country / language / tag | `music/browse` with path `radiobrowser://category/country/{code}`, `.../language/{name}`, `.../tag/{tag}` | radio-browser `search` is name only. Browse returns stations to queue. |

## Phases

Each phase is one PR with tests. Fixtures come from the DebugMusicAssistantClient
capture pattern in `test/fixtures`.

### Phase 0: make room for new intents (done)

PR #31 pruned Padatious training samples from 4,232 to 520. Keep the total
under 600 as phases add intents; the regression test from #30 guards it.

### Phase 1: small, high value

- `now_playing.intent`: "what's playing", "what song is this", "who is this".
  Speak track and artist from the player's current media.
- `like.intent`: "like this song", "I like this", "add this to my favorites".
  `music/favorites/add_item` with the current item's uri.
- Generic play (issue #8): a fallback handler, not a Padatious intent, so
  it only fires when nothing else matched. Resolve with `music/item_by_name`
  and speak what type was chosen: "Playing the album X by Y".
- Spoken disambiguation: when the matched artist differs from the requested
  one, or several albums match, say so. Mirrors minimy's `diff_artist` and
  `found_tracks` dialogs.
- Fix `stop()`: it paused `players[0]`. Pause the session's last player.

### Phase 2: genre and queue policy

- `play_genre.intent`: "play some jazz", "play jazz music", "play genre jazz".
  Resolve with `music/genres/library_items`, then `music/genres/tracks` with a
  cap, play with shuffle on.
- "play some music", "play anything", "play random music": random library
  tracks, shuffle on.
- Queue policy: artist, genre and random requests start shuffled; a single
  track or album plays in order. `shuffle.intent` and `repeat.intent`
  ("shuffle on", "repeat this song", "repeat off").

### Phase 3: playlists by voice

- "create a playlist called X", "add this to my X playlist" (create on first
  use, like minimy), "remove this from my X playlist", "save this queue as X",
  "what playlists do I have", "what's on my X playlist" (count and first
  three titles).
- Always require the word "playlist" in the phrase. "add X to Y" alone
  collides with shopping and todo skills.

### Phase 4: radio discovery

- "play radio from Spain", "play jazz radio stations", "play a radio station
  in French". Browse the radio-browser country, language and tag folders,
  fuzzy-match the spoken word against the folder names, queue the most
  popular stations so "next station" works.

## Architecture hook for the later MediaProvider

The request parsing and spoken-feedback policy live outside the OVOSSkill
class:

- `skill_musicassistant/request.py`: verb and location parsing plus artist
  comparison, with no Music Assistant references.
- `skill_musicassistant/catalog.py`: Music Assistant lookups that return
  typed results with the matched names.
- The skill handlers only speak and play.

An ovos-media MediaProvider can later wrap `catalog.py` behind
`search(signals) -> list[Release]` with no new matching code, and a skill with
a different backend (mpd, for example) can reuse `request.py` and the locale
resources unchanged.

## Decisions

1. The target Music Assistant server is current, so `music/item_by_name`,
   `music/track_by_name`, and the genres controller are available. By-name
   lookups still fall back to the free-text search on any server error.
2. Generic play ships as a fallback handler. A Padatious intent is only worth
   considering after measuring real transcripts.
3. New Music Assistant calls land in the `ma-http-client` package first; the
   skill only consumes them. The vendored client was removed in 0.5.0.
4. The 1.0 line is a breaking release: dependency change, a fallback handler
   on by default, server-side name resolution, and a different `stop` target.
5. The skill must keep working on the ovos-workshop line Neon pins (0.1.x)
   and on current OVOS (9.x); the test suite runs against both.

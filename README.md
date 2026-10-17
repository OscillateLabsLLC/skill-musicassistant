# skill-musicassistant

[![Status: Active](https://img.shields.io/badge/status-active-brightgreen)](https://github.com/OscillateLabsLLC/.github/blob/main/SUPPORT_STATUS.md)

An OVOS/Neon skill to control media through [Music Assistant](https://www.music-assistant.io/).

OCP _must_ be disabled for this skill to work. On OVOS 3.x that means removing the
`ovos-ocp-pipeline-plugin-high` and `ovos-ocp-pipeline-plugin-medium` entries from
`intents.pipeline` in `mycroft.conf`; on Neon Hub, OCP is already off.

## Features

- Play artists, tracks, albums, playlists, and radio stations on any Music Assistant player
- Just say "play X": when no other skill claims a request that starts with a play verb, the skill asks
  Music Assistant to resolve the name across artists, albums, tracks, playlists and radio
- Tells you what it actually matched: "I couldn't find that by Leonard Cohen, so here it is by Jeff Buckley"
- "What's playing?" and "like this song"
- Playback controls: pause/resume, next track, previous track, stop
- Volume control: set a level, turn it up/down, mute/unmute
- Target any player by name in the command ("...on the kitchen speaker")
- Fuzzy player name matching — minor mispronunciations and speech-to-text noise still resolve to the right player
- Set your default player by voice, per device when running under HiveMind/Neon Nodes
- Localized in English and French

## Upgrading to 2.0

2.0 replaces the typed play intents ("play the album X", "play the artist Y", and so on) with one play intent
and a parser. Every phrasing that worked before still works, and the same words now also work without the type
word; what changes is how a request is understood and which failures are spoken.

- One `play.intent` catches anything that starts with a play verb. A deterministic parser turns the words into a
  typed request (track, album, artist, playlist, genre, radio, radio category, random) using the locale word
  lists under `locale/<lang>/*.list`, so adding a language means adding lists, not code.
- The catalog policy (by-name lookup before free-text search, the different-artist fallback, genre with album
  fallback, radio name variants) lives in one module and is tested against recorded Music Assistant responses.
- A request the server cannot satisfy is reported by kind ("I couldn't find the album X"), and a request for a
  podcast or audiobook by name is no longer played as music.
- Radio by language works: the radio-browser provider only serves language folders under a lowercase path.
- The Padatious training set is roughly half its 1.x size, which matters on small devices.
- fr-fr: the control intents are translated; the parser word lists are first drafts that need review by a
  French speaker.

## Upgrading to 1.0

1.0 changes how requests are resolved. Upgrade at your own risk and review your settings afterwards.

- The skill depends on the [ma-http-client](https://pypi.org/project/ma-http-client/) package (0.2.0 or later)
  instead of a vendored copy of the client.
- A generic "play X" fallback handler is on by default. It runs after every registered intent and before the
  LLM fallback skills. Turn it off with the `generic_play_fallback` setting if another skill should own bare
  "play" requests.
- Track and album requests are resolved by name on the server first, and the skill says so when the artist it
  found differs from the one you asked for, or when several albums share a name.
- "Stop" stops the player you last used, then your default player, and only when it is playing or paused. It
  used to send a play/pause toggle to the first player the server listed, which could start an idle speaker.
- "Pause" pauses and "resume" resumes; neither toggles any more.
- Setting the default player by voice writes the settings file atomically and merges with what is on disk, after
  a plain settings store was seen emptying the file (and the server token with it) on a Neon Hub.
- New intents: "what's playing" and "like this song".

## Usage

All playback commands accept an optional player location, e.g. "play the artist Caravan Palace **on the office speaker**". Without a location, the skill uses the player you last used in this session, then your default player (see below).

### Play Music

- "Play the artist Caravan Palace"
- "Play music by Caravan Palace" / "Shuffle songs by Caravan Palace"
- "Play the track Digital Love by Daft Punk"
- "Play the album Random Access Memories by Daft Punk"
- "Play the playlist Focus"
- "Play the radio station KEXP" / "Tune into KEXP"
- "Play radio from Spain" / "Play jazz radio stations" / "Play a radio station in French" (queues the ten most
  popular radio-browser stations for that country, language, or tag; "next station" moves on)
- "Play Discovery" / "Listen to Daft Punk on the office speaker" (no type word needed; the server decides)

### Genres, Random, Shuffle and Repeat

- "Play some jazz music" / "Play the genre jazz" (a shuffled sample of that library genre)
- "Play some music" / "Play anything" / "Shuffle my library"
- "Shuffle on" / "Stop shuffling"
- "Repeat this song" / "Repeat all" / "Repeat off"

Artist, genre and random requests start shuffled; a single track or album plays in order.

### Playlists

- "Create a playlist called Workout"
- "Add this song to my Workout playlist" (creates the playlist on first use)
- "Remove this from my Workout playlist"
- "Save this queue as Tonight"
- "What playlists do I have?" / "What's on my Workout playlist?"

Always say "playlist" in these commands; "add this to Workout" alone is left to list and to-do skills.

### Now Playing and Favorites

- "What's playing?" / "What song is this?" / "Who is this?"
- "Like this song" / "Add this song to my favorites"

### Playback Controls

- "Pause the music" / "Resume the music"
- "Next track" / "Skip"
- "Previous track" / "Go back"

### Volume

- "Set the music volume to 50"
- "Set volume to 30 percent in the kitchen"
- "Mute" / "Unmute"

### Default Player

- "Make the living room speaker my default player"
- "Change my default player to the office speaker"

When you don't name a player in a command, the skill resolves one in this order:

1. The player named in the utterance (fuzzy matched)
2. The player this session used most recently, so "skip" after "play Discovery on the office speaker" skips the office speaker
3. This session's default player, if one was set by voice
4. The `default_player` skill setting

On the local device, setting a default player by voice persists it to the `default_player` setting. Under HiveMind or Neon Nodes, each client session gets its own default — for example, a HiveMind client on your work computer can use the office speaker by default while the kitchen satellite keeps its own. Per-session defaults are held in memory and reset when the skill restarts; the `default_player` setting remains the fallback.

## Configuration

The skill requires the following configuration:

- `music_assistant_url`: The URL of the Music Assistant server.
- `music_assistant_token`: The token for the Music Assistant server. _Required for version 2.7.2 and later._

The skill also accepts the following configuration:

- `default_player`: The default player to use when a command doesn't name one. Can also be set by voice ("make ... my default player"), which updates this setting on the local device.

These can be set in the skill settings or in the skill configuration file.

## Example Configuration

```json
{
  "music_assistant_url": "http://localhost:8095",
  "music_assistant_token": "MUSIC_ASSISTANT_TOKEN",
  "default_player": "Living Room Speaker"
}
```

# skill-musicassistant

[![Status: Active](https://img.shields.io/badge/status-active-brightgreen)](https://github.com/OscillateLabsLLC/.github/blob/main/SUPPORT_STATUS.md)

An OVOS/Neon skill to control media through [Music Assistant](https://www.music-assistant.io/).

OCP _must_ be disabled for this skill to work.

## Features

- Play artists, tracks, albums, playlists, and radio stations on any Music Assistant player
- Playback controls: pause/resume, next track, previous track
- Volume control: set a level, turn it up/down, mute/unmute
- Target any player by name in the command ("...on the kitchen speaker")
- Fuzzy player name matching — minor mispronunciations and speech-to-text noise still resolve to the right player
- Set your default player by voice, per device when running under HiveMind/Neon Nodes
- Localized in English and French

## Usage

All playback commands accept an optional player location, e.g. "play the artist Caravan Palace **on the office speaker**". Without a location, the skill uses your default player (see below).

### Play Music

- "Play the artist Caravan Palace"
- "Play music by Caravan Palace" / "Shuffle songs by Caravan Palace"
- "Play the track Digital Love by Daft Punk"
- "Play the album Random Access Memories by Daft Punk"
- "Play the playlist Focus"
- "Play the radio station KEXP" / "Tune into KEXP"

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
2. This session's default player, if one was set by voice
3. The `default_player` skill setting

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

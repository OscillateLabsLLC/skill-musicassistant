# skill-musicassistant

Mike Gray/Oscillate Labs
[mike@oscillatelabs.net](mailto:mike@oscillatelabs.net)
Apache-2.0

An OVOS/Neon skill to control media through Music Assistant.

OCP _must_ be disabled for this skill to work.

## Configuration

The skill requires the following configuration:

- `music_assistant_url`: The URL of the Music Assistant server.
- `music_assistant_token`: The token for the Music Assistant server. _Required for version 2.7.2 and later._

The skill also accepts the following configuration:

- `default_player`: The default player to use for the skill.

These can be set in the skill settings or in the skill configuration file.

## Example Configuration

```json
{
  "music_assistant_url": "http://localhost:8095",
  "music_assistant_token": "MUSIC_ASSISTANT_TOKEN",
  "default_player": "Living Room Speaker"
}
```

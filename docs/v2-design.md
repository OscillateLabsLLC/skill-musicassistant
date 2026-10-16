# v2 design: parser-centric request handling

Status: accepted. Supersedes the phase plan in `plan-minimy-ideas.md`, whose
features all shipped on the 1.x line and carry forward unchanged in scope.

## Why a redesign

The 1.x line grew by adding one Padatious intent file per request shape. By
1.0 there were 23 intent files, and the live trial on a Neon Hub showed the
cost of that approach:

- Type-word intents claim each other's utterances. "play a radio station in
  french" matches the named-station intent; "play beatles music" matches the
  genre intent; "play some music" is a genre intent with an empty genre.
  Each mis-claim was patched inside the winning handler, so parsing rules now
  live in six handlers instead of one place.
- Every play handler repeats the same five steps: read slots, find the
  player, resolve against the catalog, play, speak. The order and the error
  dialogs drift between copies. `__init__.py` is 1,244 lines.
- The en-us Padatious training set is held under a 600-line budget by a
  test, and the Hub already logs "Took too long to train". More alternations
  are not affordable.
- Unit tests mock the Music Assistant client by hand, so they encode what the
  author believed the server returns. Three live defects (unranked genre
  search, radio names carrying slogans, browse listings starting with a
  ".." folder) were invisible to the suite.
- Spoken feedback is chosen inside handlers, so "playing X by Y instead of Z"
  and "found several albums" are available to some paths and not others.

v2 keeps the feature set and the Music Assistant dependency, and changes how
an utterance becomes a playback request.

## Goals

1. One deterministic parser turns an utterance into a typed `MediaRequest`.
   It has no backend knowledge and is covered by table tests that double as
   the grammar specification.
2. One catalog adapter turns a `MediaRequest` into something playable. It is
   covered by contract tests that replay recorded Music Assistant responses.
3. One play pipeline and one feedback policy. Handlers only call them.
4. A small intent surface: one play intent plus control intents, well under
   the Padatious budget.
5. An optional entity-extraction layer (GLiNER) only if a benchmark shows it
   improves type and artist detection on free-form requests.
6. Unchanged compatibility: ovos-workshop 0.1.x (Neon) and 9.x, Python 3.10,
   skill settings keys and locale file names preserved where they still apply.

## Non-goals

- No ovos-media MediaProvider in this release. `catalog.py` stays shaped so a
  provider can wrap it later.
- No change to the `ma-http-client` package beyond what the recorder needs.
- No new backends. The parser and feedback policy stay backend-neutral so a
  sibling skill can reuse them, but nothing is built for one here.
- No machine-learned entity extraction (see the benchmark below).

## Architecture

```
utterance
   |  intents: play.intent (single {query} slot), control intents, fallback
   v
parser.parse(utterance, lexicon, is_player) -> MediaRequest
   |  deterministic rules; optional GLiNER hints when no type word is present
   v
catalog.resolve(client, request) -> Resolution
   |  Music Assistant lookups, ranking, fallbacks
   v
skill._play(resolution, player_id); feedback.dialog_for(request, resolution)
```

### Intents

- `play.intent`: `(play|listen to|put on|...) {query}`. The verb list comes
  from `play_verbs.list` so the intent file and the fallback stay in sync.
- The generic-play fallback stays as the safety net for utterances Padatious
  does not claim. Both routes call the same `handle_play_request`.
- Control intents keep their own files because their structure is
  distinctive and short: pause/resume, next, previous, volume, shuffle,
  repeat, now playing, like, set default player, and the six playlist
  management intents.
- Removed: `play_artist`, `play_album`, `play_track`, `play_playlist`,
  `play_genre`, `play_random`, `play_radio`, `play_radio_category`. Their
  phrasings become parser test cases.

### `MediaRequest` and the parser

```python
@dataclass(frozen=True)
class MediaRequest:
    kind: Kind            # TRACK, ALBUM, ARTIST, PLAYLIST, GENRE, RADIO,
                          # RADIO_CATEGORY, RANDOM, UNKNOWN
    name: str = ""        # what to look up, type words and filler removed
    artist: str = ""      # from a "by X" clause
    location: str = ""    # trailing player name, already matched to a player
    shuffle: bool = False # the verb was "shuffle"
    radio_mode: bool = False  # "... with radio mode"
    raw: str = ""         # the utterance as heard, for logging and dialogs
```

`parser.parse` applies rules in a fixed order, each rule consuming words.
`request.py` keeps the shared string helpers it already has:

1. Trailing location. Split at the last location prefix whose remainder
   matches a known player (callback supplied by the skill).
2. Random. The remaining words are only random words and media nouns.
3. Radio category. "radio from X", "X radio stations", "a radio station in X".
4. Explicit type words. Leading ("the album X", "the song X", "artist X",
   "playlist X", "radio X", "station X") and trailing ("X album", "X radio").
5. "by" split. Everything after the last " by " is the artist. With no type
   word the kind stays UNKNOWN and the catalog decides track versus album.
6. Artist only. "songs by X" and "music by X" leave nothing but filler
   before the separator, so the request is for the artist.
7. Genre by media noun. A trailing media noun ("jazz music", "beatles
   songs") marks a genre request. The parser does not know which names are
   genres; the catalog tries the genre list first and falls back to a name
   lookup, which is how "play beatles music" still plays the band.
8. Otherwise UNKNOWN with the whole remainder as the name.

Lexicon words come from the locale `.list` and `.voc` files, so a second
language adds files, not code. The parser is a pure function and its tests
are a table of `(utterance, MediaRequest)` rows. That table is the grammar.

### Optional entity extraction: benchmarked, not adopted

A `MediaRequest` with kind UNKNOWN and no artist is the case the catalog
handles worst, because it has to try every type. GLiNER (zero-shot named
entity recognition) was benchmarked as a hint layer for exactly that case.

Benchmark (Apple Silicon, PyTorch CPU, threshold 0.3, labels artist, album,
song, playlist, genre, radio station, speaker):

| model | typed rows agreeing with the parser | bare names labelled correctly | median latency |
|---|---|---|---|
| gliner_small-v2.1 | 14 of 26 | 3 of 16 | 21 ms |
| gliner_medium-v2.1 | not run | 7 of 16 | 37 ms |

Typical errors: "daft punk" labelled genre (0.8), "abbey road" labelled
song (0.86), "radiohead" labelled radio station, "kexp" and "art of
concentration" not labelled at all. Telling an album from an artist needs
knowledge of the catalog, which a zero-shot model does not have and the
server's by-name lookup does: the recorded scenarios resolve all 16 of these
bare names correctly without any hint.

Decision: no GLiNER dependency, not even as an optional extra. The UNKNOWN
path stays as it is (server by-name lookup with a ranked free-text search
in front). A Hub-CPU latency figure was not measured because the accuracy
result alone decides it.

### Catalog adapter and contract tests

`catalog.resolve(client, request)` returns a `Resolution`:

```python
@dataclass(frozen=True)
class Resolution:
    item: Optional[ResolvedItem]   # one thing to play, with matched names
    uris: List[str]                # or a list to shuffle (genre, random, radio category)
    kind: Kind                     # what was actually found
    alternatives: List[ResolvedItem]  # for "found several albums"
    requested_artist: str          # for "by Y instead of Z"
```

Ranking and fallback rules that today sit in handlers move here: genre with
album fallback, by-name lookups falling back to free-text search, slogan
tolerant station matching, folder entries filtered from radio categories.

Contract tests replace hand-written mocks:

- `scripts/record_ma_fixtures.py` runs a fixed list of client calls against a
  live Music Assistant server and writes each `(method, params) -> response`
  pair to `test/fixtures/ma/<name>.json`. Tokens and host names are stripped.
- `ReplayClient` serves recorded responses and fails loudly on an unrecorded
  call, so a new catalog code path forces a new recording.
- Tests assert catalog decisions ("daft punk" resolves to the artist, not the
  genre Punk; "bbc radio 1" picks the station whose name carries a slogan).
- Fixtures are re-recorded when the server changes; the diff shows what
  moved. The server is a moving target and this makes that visible.
- Recordings also pin the client's wire format. A `ma-http-client` upgrade
  that changes an argument (the 0.2.1 random-order fix moves `sort_field`
  to `order_by`) means re-recording the affected scenarios with the new pin.
- The first recording session already paid for itself: the radio-browser
  provider lists language folders under a capitalised path that it serves
  empty, and only the lowercase path returns stations. Country codes were
  lowercase already, which is why the 1.0 trial never saw it.

### Play pipeline and feedback policy

`handle_play_request(request, message)` is the only place that plays:

1. Resolve the player (session default, then settings default, then the
   first available player; unavailable players produce `player_unavailable`).
2. `catalog.resolve`.
3. Play: one item goes through `play_media` with queue option REPLACE and a
   shuffle flag derived from the kind; a uri list goes through the REPLACE
   plus background ADD pattern used today for radio categories.
4. `feedback.dialog_for(request, resolution)` returns `(dialog_name, data)`.
   This is the single place that knows about `playing_different_artist`,
   `found_several_albums`, `playing_radio_category`, and the not-found
   dialogs per kind.

Control handlers stay thin and keep their current dialogs. The settings
persistence fix (`_persist_setting`, merge with disk and atomic replace)
and the `stop` semantics from 1.0 carry over unchanged.

## Compatibility

- ovos-workshop 0.1.x and 9.x: the fallback base class selection and the two
  `can_answer` signatures stay. New code may not import anything that only
  one line provides without a guard.
- Python 3.10 syntax throughout (the Hub container).
- Settings keys `music_assistant_url`, `music_assistant_token`,
  `default_player`, `generic_play_fallback` are unchanged.
- fr-fr: the lexicon lists need French entries before the parser works in
  French. Until a reviewer supplies them, fr-fr keeps the control intents
  and falls back to UNKNOWN requests, which still play by name.

## Test strategy

| Layer | Test type | Depends on |
|---|---|---|
| parser | table of utterance to `MediaRequest` | nothing |
| feedback | table of (`MediaRequest`, `Resolution`) to dialog | nothing |
| catalog | contract tests on recorded responses | fixtures |
| skill | bus-level tests on both workshop lines | mocked catalog |

The current 209 tests are kept where they test behaviour that survives;
tests that encode handler-specific parsing move into the parser table.

## Release

- Single integration branch `v2`, one pull request, version 2.0.0 with a
  BREAKING CHANGE footer listing removed intent files.
- Live trial on the Hub from the branch pin before tagging, with the
  utterance list from the 1.0 trial as the acceptance script.
- After release the Hub configuration returns to the released package.

## Stages

1. `MediaRequest`, `Kind`, `request.parse`, lexicon loading, parser tables.
   Pure code, no skill changes. Gate: every phrasing from the removed intent
   files parses to the expected request.
2. Fixture recorder, `ReplayClient`, `catalog.resolve`, contract tests.
   Gate: the three live defects from the 1.0 trial are reproduced by
   fixtures and fixed.
3. `handle_play_request`, `feedback.py`, intent pruning, handler
   consolidation. Gate: bus tests green on both workshop lines, Padatious
   training set well under budget.
4. GLiNER benchmark in a throwaway environment, not in the skills container.
   Gate: latency and accuracy numbers recorded in this document; go or no-go.
   Done: no-go, see "Optional entity extraction".
5. Hub trial, release 2.0.0, configuration restored.

## Related OVOS work

The OCP stack has assets that bear on this design; they were checked against
the parser after stage 4.

- `ovos-media-classifier` (used by `ovos-ocp-pipeline-plugin`) classifies
  medium, playback type, structure, genres and qualifiers from an utterance.
  `Signals.title` carries the raw query by design; it does not separate
  artist from album or track. Its entity side is Aho-Corasick exact matching
  over the user's own library lists (`ner_list`), plus a capped gazetteer.
  That is the same answer this skill gets from the server's by-name lookup,
  so there is nothing to borrow for the UNKNOWN case, and the medium
  decision is not needed while the skill only plays music.
- `Jarbas/music_queries_*` on Hugging Face: synthetic requests with slot
  labels (artist, track, album, genre, country, location, theme) and the
  template each came from. Running the parser over 1,035 rows limited to
  the slots this skill handles gives 95 agreements. 697 of the rows have no
  leading play verb ("I want to listen to X", "give me a few tracks from X",
  "start a X mix", "queue up some X"), which neither the play intent nor the
  fallback would claim today. The dataset is the obvious benchmark for
  widening the grammar through the lexicon lists (lead-in phrases, "X's
  songs", "X mix") without adding intent files.
- `Jarbas/WikidataMediaEntities`: a 1.6M-row typed gazetteer (299k artists,
  207k albums, 3k songs). Not needed while the catalog is the gazetteer.
- `TigreGotico/search-term-extraction`: token-classification data for
  pulling the search term out of a request, in eleven languages including
  French. A candidate source for French lead-in phrases.

## Open questions

- Whether to widen the grammar to the verbless phrasings in the
  `music_queries` corpus. It is lexicon work, not code, but every lead-in
  added to `play.intent` also widens what the intent claims from other
  skills.

- A single `{query}` slot may let Padatious claim unrelated "play" requests
  (games, podcasts from other skills). The fallback already handles
  confidence by returning False when nothing resolves; the intent route needs
  the same escape, which may mean converse-style re-emission or a
  confidence check on the match.
- Whether the catalog should try the genre list for UNKNOWN requests before
  or after the by-name lookups. Recorded fixtures will show which order
  produces fewer wrong matches on the trial utterances.
- Queue policy for a named artist: shuffle all tracks (current) or play top
  tracks. Music Assistant exposes both; the trial should decide.

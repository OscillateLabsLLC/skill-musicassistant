"""Guardrails for intent file size and matching.

Padatious expands every (a|b|c) group into separate training samples and uses
other intents' samples as negatives, so training cost grows superlinearly with
total sample count. These tests keep the expansion budget from creeping back up
(see issue #30) and verify the kept phrasings still match their intents.
"""

from pathlib import Path

import pytest
from ovos_utils.bracket_expansion import expand_template
from padacioso import IntentContainer


LOCALE_DIR = Path(__file__).parent.parent / "skill_musicassistant" / "locale"

# Hard ceilings from issue #30 - raise these only with a measured justification
MAX_SAMPLES_PER_LOCALE = 600
MAX_SAMPLES_PER_FILE = 200


def _intent_lines(path: Path):
    return [
        line.strip() for line in path.read_text().splitlines() if line.strip() and not line.strip().startswith("#")
    ]


def _expansion_counts(lang: str):
    intent_dir = LOCALE_DIR / lang / "intents"
    return {
        f.name: sum(len(expand_template(line)) for line in _intent_lines(f))
        for f in sorted(intent_dir.glob("*.intent"))
    }


class TestExpansionBudget:
    @pytest.mark.parametrize("lang", ["en-us", "fr-fr"])
    def test_locale_total_under_budget(self, lang):
        counts = _expansion_counts(lang)
        total = sum(counts.values())
        assert total <= MAX_SAMPLES_PER_LOCALE, (
            f"{lang} intents expand to {total} Padatious samples (budget {MAX_SAMPLES_PER_LOCALE}): {counts}"
        )

    @pytest.mark.parametrize("lang", ["en-us", "fr-fr"])
    def test_no_single_file_dominates(self, lang):
        for name, count in _expansion_counts(lang).items():
            assert count <= MAX_SAMPLES_PER_FILE, (
                f"{lang}/{name} expands to {count} samples (budget {MAX_SAMPLES_PER_FILE}) "
                "- prune alternation groups instead of enumerating combinations"
            )


class TestIntentMatching:
    """Exact-pattern matching for the phrasings the intent files keep.

    Uses padacioso (regex, deterministic). Padatious additionally generalizes
    beyond these patterns at runtime; this suite covers the guaranteed floor.
    """

    @pytest.fixture(scope="class")
    def container(self):
        container = IntentContainer()
        intent_dir = LOCALE_DIR / "en-us" / "intents"
        for f in sorted(intent_dir.glob("*.intent")):
            container.add_intent(f.stem, _intent_lines(f))
        return container

    @pytest.mark.parametrize(
        "utterance,intent",
        [
            ("play the album abbey road", "play_album"),
            ("shuffle the album abbey road", "play_album"),
            ("play the album abbey road by the beatles", "play_album"),
            ("play the album abbey road by the beatles in the kitchen", "play_album"),
            ("play the album abbey road with radio mode", "play_album"),
            ("play the track yellow submarine", "play_track"),
            ("play the song yellow submarine by the beatles", "play_track"),
            ("play the song yellow submarine in the kitchen", "play_track"),
            ("play the artist caravan palace", "play_artist"),
            ("shuffle music by daft punk", "play_artist"),
            ("play the band caravan palace on the office speaker", "play_artist"),
            ("play the playlist focus", "play_playlist"),
            ("play the playlist focus in the kitchen", "play_playlist"),
            ("tune into kexp", "play_radio"),
            ("tune in to bbc radio 1", "play_radio"),
            ("play the radio station kexp", "play_radio"),
            ("play kexp radio", "play_radio"),
            ("pause the music", "pause"),
            ("resume the music", "pause"),
            ("pause the music in the kitchen", "pause"),
            ("next track", "next"),
            ("skip this song", "next"),
            ("previous track", "previous"),
            ("go back", "previous"),
            ("make the office speaker my default speaker", "set_default_player"),
            ("change my default player to the kitchen display", "set_default_player"),
            ("set the music volume to 50", "volume"),
            ("what's playing", "now_playing"),
            ("what song is this", "now_playing"),
            ("who is this", "now_playing"),
            ("what's playing in the kitchen", "now_playing"),
            ("what is playing right now", "now_playing"),
            ("like this song", "like"),
            ("i love this song", "like"),
            ("add this song to my favorites", "like"),
            ("play some jazz music", "play_genre"),
            ("play the genre jazz", "play_genre"),
            ("play jazz music in the kitchen", "play_genre"),
            ("play anything", "play_random"),
            ("shuffle my library", "play_random"),
            ("shuffle on", "shuffle"),
            ("stop shuffling", "shuffle"),
            ("repeat this song", "repeat"),
            ("repeat all", "repeat"),
            ("repeat off", "repeat"),
            ("create a playlist called workout", "create_playlist"),
            ("make a new playlist road trip", "create_playlist"),
            ("add this song to my workout playlist", "add_to_playlist"),
            ("add this to the playlist workout", "add_to_playlist"),
            ("remove this from my workout playlist", "remove_from_playlist"),
            ("save this queue as tonight", "save_queue"),
            ("what playlists do i have", "list_playlists"),
            ("list my playlists", "list_playlists"),
            ("what's on my workout playlist", "playlist_contents"),
            ("mute", "volume"),
            ("unmute the music in the kitchen", "volume"),
        ],
    )
    def test_utterance_matches_intent(self, container, utterance, intent):
        result = container.calc_intent(utterance)
        assert result.get("name") == intent, f"{utterance!r} -> {result}"

    def test_slots_extracted(self, container):
        result = container.calc_intent("play the album abbey road by the beatles in the kitchen")
        assert result["entities"].get("album") == "abbey road"
        assert result["entities"].get("artist") == "the beatles"
        assert result["entities"].get("location") == "kitchen"

    def test_playlist_slots(self, container):
        result = container.calc_intent("add this song to my workout playlist")
        assert result["entities"].get("playlist") == "workout"
        result = container.calc_intent("save this queue as a playlist called tonight")
        assert result["entities"].get("playlist") == "tonight"

    def test_now_playing_location_slot(self, container):
        result = container.calc_intent("what's playing on the office speaker")
        assert result.get("name") == "now_playing"
        assert result["entities"].get("location") == "office speaker"

    def test_play_some_music_lands_on_a_handler_that_plays_random(self, container):
        """Both patterns can match; the genre handler redirects "some" to random at runtime."""
        assert container.calc_intent("play some music").get("name") in {"play_random", "play_genre"}

    def test_bare_play_is_not_an_intent(self, container):
        """Bare "play X" belongs to the fallback handler, never to a Padatious intent."""
        assert container.calc_intent("play abbey road").get("name") is None


class TestLocaleParity:
    @pytest.mark.parametrize("kind", ["intents", "dialog"])
    def test_fr_fr_has_every_en_us_resource(self, kind):
        en = {p.name for p in (LOCALE_DIR / "en-us" / kind).iterdir()}
        fr = {p.name for p in (LOCALE_DIR / "fr-fr" / kind).iterdir()}
        assert en - fr == set(), f"fr-fr is missing {kind}: {sorted(en - fr)}"

    @pytest.mark.parametrize("name", ["play_verbs.list", "location_prefixes.list"])
    def test_word_lists_exist_in_both_locales(self, name):
        for lang in ("en-us", "fr-fr"):
            assert (LOCALE_DIR / lang / name).read_text().strip(), f"{lang}/{name} is empty"

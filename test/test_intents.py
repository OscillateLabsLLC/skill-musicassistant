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
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
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
            f"{lang} intents expand to {total} Padatious samples "
            f"(budget {MAX_SAMPLES_PER_LOCALE}): {counts}"
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

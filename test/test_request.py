"""Tests for the backend-neutral request parsing helpers."""

from skill_musicassistant.request import (
    name_similarity,
    radio_similarity,
    same_artist,
    split_trailing_location,
    strip_leading_verb,
)


VERBS = ["play", "listen to", "put on", "shuffle"]
PREFIXES = ["on the", "in the", "on", "in"]


class TestStripLeadingVerb:
    def test_single_word_verb(self):
        assert strip_leading_verb("play abbey road", VERBS) == "abbey road"

    def test_longest_verb_wins(self):
        assert strip_leading_verb("listen to abbey road", VERBS) == "abbey road"

    def test_case_and_whitespace(self):
        assert strip_leading_verb("  Play Abbey Road ", VERBS) == "abbey road"

    def test_verb_alone_gives_empty_query(self):
        assert strip_leading_verb("play", VERBS) == ""

    def test_no_verb_returns_none(self):
        assert strip_leading_verb("what time is it", VERBS) is None

    def test_verb_must_be_a_whole_word(self):
        assert strip_leading_verb("playlist focus", VERBS) is None


class TestSplitTrailingLocation:
    def test_on_the(self):
        assert ("abbey road", "kitchen speaker") in split_trailing_location(
            "abbey road on the kitchen speaker", PREFIXES
        )

    def test_bare_preposition_is_also_offered(self):
        splits = split_trailing_location("abbey road in kitchen", PREFIXES)
        assert ("abbey road", "kitchen") in splits

    def test_uses_last_occurrence(self):
        splits = split_trailing_location("lights on the hill on the office speaker", PREFIXES)
        assert splits[0] == ("lights on the hill", "office speaker")

    def test_no_location_phrase(self):
        assert split_trailing_location("abbey road", PREFIXES) == []

    def test_prefix_at_start_is_not_a_location(self):
        assert split_trailing_location("on the road", PREFIXES) == []


class TestNameSimilarity:
    def test_articles_do_not_matter(self):
        assert name_similarity("beatles", "The Beatles") == 100

    def test_partial_matches_are_not_rewarded(self):
        assert name_similarity("daft punk", "Punk") < 70
        assert name_similarity("discovery", "Disco") < 80
        assert name_similarity("hallelujah", "104.3 Hallelujah FM") < 70

    def test_close_spelling_passes(self):
        assert name_similarity("greatest hits", "Greatest Hits") == 100
        assert name_similarity("hip hop", "Hip-Hop") >= 85


class TestRadioSimilarity:
    def test_slogan_does_not_hurt(self):
        assert radio_similarity("bbc radio 1", "BBC RADIO 1 - The biggest new pop and all-day vibes") == 100

    def test_word_order_does_not_matter(self):
        assert radio_similarity("bbc 1 radio", "BBC Radio 1") == 100

    def test_other_station_scores_lower(self):
        assert radio_similarity("bbc 1 radio", "bbc 1 tv") < radio_similarity("bbc 1 radio", "BBC Radio 1 - news")


class TestSameArtist:
    def test_exact(self):
        assert same_artist("Daft Punk", "Daft Punk")

    def test_tolerates_articles_and_case(self):
        assert same_artist("the beatles", "Beatles")

    def test_different_people(self):
        assert not same_artist("Daft Punk", "Justice")

    def test_missing_side_is_not_a_mismatch(self):
        assert same_artist(None, "Daft Punk")
        assert same_artist("Daft Punk", None)

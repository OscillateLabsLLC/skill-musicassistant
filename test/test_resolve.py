"""Unit tests for the resolver's failure accounting; the behaviour tests are the contract tests."""

# pylint: disable=missing-docstring

from unittest.mock import Mock

from skill_musicassistant.parser import Kind, MediaRequest
from skill_musicassistant.resolve import resolve


def _failing_client():
    client = Mock()
    client.search_media.side_effect = Exception("HTTP 500")
    client.get_item_by_name.side_effect = Exception("HTTP 500")
    client.get_track_by_name.side_effect = Exception("HTTP 500")
    return client


def test_failed_lookups_are_counted_not_hidden():
    found = resolve(_failing_client(), MediaRequest(kind=Kind.UNKNOWN, name="discovery"))

    assert not found.found
    assert found.failed_lookups == 1


def test_every_fallback_rule_that_fails_is_counted():
    found = resolve(_failing_client(), MediaRequest(kind=Kind.UNKNOWN, name="discovery", artist="daft punk"))

    assert not found.found
    assert found.failed_lookups == 3


def test_a_success_after_a_failure_still_plays():
    client = _failing_client()
    client.get_track_by_name.side_effect = None
    client.get_track_by_name.return_value = {"name": "Get Lucky", "uri": "library://track/1", "media_type": "track"}

    found = resolve(client, MediaRequest(kind=Kind.TRACK, name="get lucky"))

    assert found.found
    assert found.failed_lookups == 0


def test_nothing_found_without_errors_has_no_failures():
    client = Mock()
    client.search_media.return_value = {}
    client.get_item_by_name.return_value = None

    found = resolve(client, MediaRequest(kind=Kind.UNKNOWN, name="zorblax"))

    assert not found.found
    assert found.failed_lookups == 0

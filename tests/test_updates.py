"""Tests for update checking (no network access)."""

from __future__ import annotations

import urllib.error

import pytest

from midisuite.updates import (
    CHECK_INTERVALS,
    UpdateError,
    check_for_update,
    interval_seconds,
    is_newer,
    parse_version,
)


def test_parse_version():
    assert parse_version("v1.2.3") == ((1, 2, 3), False)
    assert parse_version("1.2.3-beta") == ((1, 2, 3), True)
    assert parse_version("2026.10") == ((2026, 10), False)


def test_is_newer():
    assert is_newer("1.0.0", "1.0.1")
    assert is_newer("1.0", "1.0.1")
    assert is_newer("1.9.9", "2.0.0")
    assert is_newer("1.0.0-beta", "1.0.0")
    assert not is_newer("1.0.1", "1.0.0")
    assert not is_newer("1.0.0", "1.0.0")
    assert not is_newer("1.0.0", "1.0.0-beta")
    assert not is_newer("2.0.0", "2.0")


def test_interval_seconds():
    assert interval_seconds("hourly") == 3600
    assert interval_seconds("daily") == CHECK_INTERVALS["daily"]
    assert interval_seconds("weekly") == 7 * 24 * 3600
    assert interval_seconds("monthly") == 30 * 24 * 3600
    assert interval_seconds("never") is None
    assert interval_seconds("unknown") == CHECK_INTERVALS["daily"]


def _release(version="1.2.0"):
    return {
        "tag_name": f"v{version}",
        "body": "changes",
        "html_url": "https://example.invalid/release",
    }


def test_check_for_update_finds_newer_release():
    release = check_for_update("owner/repo", "1.1.0", fetch=lambda url: _release())
    assert release is not None
    assert release.version == "1.2.0"
    assert release.notes == "changes"
    assert release.page_url == "https://example.invalid/release"


def test_check_for_update_up_to_date():
    assert check_for_update("owner/repo", "1.2.0", fetch=lambda url: _release()) is None
    assert check_for_update("owner/repo", "9.0", fetch=lambda url: _release()) is None


def test_check_for_update_requires_repository():
    with pytest.raises(UpdateError):
        check_for_update("", "1.0")


def test_check_for_update_requires_tag():
    with pytest.raises(UpdateError):
        check_for_update("owner/repo", "1.0", fetch=lambda url: {"tag_name": ""})


def _http_error(code):
    def fetch(url):
        raise urllib.error.HTTPError(url, code, "error", {}, None)

    return fetch


def test_check_for_update_handles_missing_repository():
    with pytest.raises(UpdateError, match="no releases"):
        check_for_update("owner/repo", "1.0", fetch=_http_error(404))


def test_check_for_update_handles_rate_limit():
    with pytest.raises(UpdateError, match="rate limit"):
        check_for_update("owner/repo", "1.0", fetch=_http_error(403))

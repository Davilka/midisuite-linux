"""Update checking through GitHub Releases.

The application only *checks* for a newer release and points to its page; it
never downloads or installs anything.  The check interval is configurable in
the preferences (hourly, daily, weekly, monthly or never).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

try:  # written by scripts/build-bundle.sh in CI
    from ._build_info import REPO as _BUILD_REPO
except Exception:  # pragma: no cover - normal source checkout
    _BUILD_REPO = ""

DEFAULT_REPO = os.environ.get("MIDISUITE_UPDATE_REPO", "") or _BUILD_REPO
API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
USER_AGENT = "midisuite-linux"

DEFAULT_INTERVAL = "daily"
CHECK_INTERVALS: dict[str, int] = {
    "hourly": 60 * 60,
    "daily": 24 * 60 * 60,
    "weekly": 7 * 24 * 60 * 60,
    "monthly": 30 * 24 * 60 * 60,
}
INTERVAL_LABELS: list[tuple[str, str]] = [
    ("hourly", "Every hour"),
    ("daily", "Once a day"),
    ("weekly", "Once a week"),
    ("monthly", "Once a month"),
    ("never", "Never"),
]


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    notes: str
    page_url: str


# --------------------------------------------------------------------------
# Version handling
# --------------------------------------------------------------------------
def parse_version(text: str) -> tuple[tuple[int, ...], bool]:
    """Return ``(numeric parts, is_prerelease)`` for a version string."""
    text = text.strip().lstrip("vV")
    core, _, prerelease = text.partition("-")
    if "#" in core:
        core = core.split("#", 1)[0]
    parts = tuple(int(part) for part in re.findall(r"\d+", core))
    return (parts or (0,)), bool(prerelease)


def is_newer(current: str, candidate: str) -> bool:
    current_parts, current_pre = parse_version(current)
    candidate_parts, candidate_pre = parse_version(candidate)
    size = max(len(current_parts), len(candidate_parts))
    left = current_parts + (0,) * (size - len(current_parts))
    right = candidate_parts + (0,) * (size - len(candidate_parts))
    if left != right:
        return right > left
    return current_pre and not candidate_pre


def interval_seconds(key: str) -> int | None:
    """Return the interval in seconds, or ``None`` for “never”."""
    if key == "never":
        return None
    return CHECK_INTERVALS.get(key, CHECK_INTERVALS[DEFAULT_INTERVAL])


# --------------------------------------------------------------------------
# GitHub
# --------------------------------------------------------------------------
def fetch_json(url: str, timeout: float = 10.0) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def check_for_update(
    repo: str,
    current: str,
    fetch: Callable[[str], dict] = fetch_json,
) -> Release | None:
    """Return the latest release when it is newer than ``current``."""
    if not repo:
        raise UpdateError("update repository is not configured")
    try:
        data = fetch(API_LATEST.format(repo=repo))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError(f"no releases found for {repo}") from exc
        if exc.code == 403:
            raise UpdateError("GitHub API rate limit reached; try again later") from exc
        raise UpdateError(f"GitHub API error: HTTP {exc.code}") from exc
    except Exception as exc:
        raise UpdateError(f"cannot reach GitHub: {exc}") from exc

    tag = str(data.get("tag_name") or "")
    version = tag.lstrip("vV")
    if not version:
        raise UpdateError("the latest release has no tag")
    if not is_newer(current, version):
        return None
    return Release(
        version=version,
        tag=tag,
        notes=str(data.get("body") or "").strip(),
        page_url=str(data.get("html_url") or ""),
    )

"""Every manifest version has release notes, so a version bump can't be forgotten."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "custom_components" / "racktivity_dcmu" / "manifest.json"
CHANGELOG = ROOT / "CHANGELOG.md"


def test_changelog_has_current_version() -> None:
    version = json.loads(MANIFEST.read_text())["version"]
    heading = f"## [{version}]"
    assert heading in CHANGELOG.read_text(), (
        f"manifest.json says {version} but CHANGELOG.md has no '{heading}' section"
    )


def test_changelog_versions_are_tagged_format() -> None:
    headings = re.findall(r"^## \[([^\]]+)\]", CHANGELOG.read_text(), re.MULTILINE)
    assert headings, "CHANGELOG.md has no version sections"
    for version in headings:
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"bad version heading: {version}"

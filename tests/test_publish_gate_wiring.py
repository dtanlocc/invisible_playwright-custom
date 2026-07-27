"""This package must not be publishable without the gate.

Until 2026-07-27 it was. A release here was a bare `twine upload` of whatever
happened to be in a directory, and on that day invisible-playwright 0.4.4
reached the index built from a tree that predated the fix it was meant to carry.
A PyPI filename is never re-uploaded, so that artifact is wrong forever and the
only remedy was another version.

The gate lives in `invisible_core.release` - one implementation for all three
packages, importable because this package pins the core exactly. What makes it
work is not the digests or the ledger: it is that `publish` builds and uploads
WHAT IT JUST BUILT, so a stale directory cannot be the thing that ships.

These assert the wiring, not the gate. The gate's own known-bad inputs are
`invisible_core/tests/test_release_gate.py`, 73 cases.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

_REPO = pathlib.Path(__file__).resolve().parents[1]
_HOOK = _REPO / ".githooks" / "pre-push"


def test_the_gate_is_importable_from_the_pinned_core():
    """If this fails, the hook below refuses every release tag with a
    ModuleNotFoundError rather than a verdict."""
    from invisible_core import release

    assert hasattr(release, "main")
    assert hasattr(release, "resolve_project_identity")


def test_the_gate_recognises_THIS_project_and_not_the_core():
    """One gate, three projects: the identity comes from our pyproject. Reading
    the core's would gate the wrong package and pass every time."""
    from invisible_core.release import resolve_project_identity

    dist, pkg = resolve_project_identity(_REPO)
    assert dist.replace("-", "_") == _REPO.name
    assert (_REPO / "src" / pkg).is_dir()


@pytest.mark.skipif(not _HOOK.exists(), reason="not a source checkout")
def test_the_pre_push_hook_gates_release_tags():
    text = _HOOK.read_text(encoding="utf-8")
    assert "invisible_core.release" in text, (
        "the pre-push hook does not run the publish gate, so a release tag can "
        "be pushed - and published - with no check at all")
    # The slashes are escaped inside the awk pattern, so strip backslashes
    # before looking. Asserting the raw form failed against a hook that was
    # perfectly correct - a test reading the implementation's punctuation.
    assert "/tags/v" in text.replace("\\", ""), (
        "the hook does not recognise a release tag")


@pytest.mark.skipif(not (_REPO / "PUBLISHED.json").exists(),
                    reason="not a source checkout")
def test_the_ledger_records_what_actually_shipped():
    """The gate compares against this. An absent or empty one is how a content
    change waves itself through as 'release 1'."""
    import json

    led = json.loads((_REPO / "PUBLISHED.json").read_text(encoding="utf-8"))
    released = led.get("released") or []
    assert released, "the ledger is empty; the gate has no memory to compare against"
    for entry in released:
        assert entry["version"] in entry["wheel_filename"].replace("_", "-") or \
               entry["version"] in entry["wheel_filename"], (
            f"entry {entry['version']} names a wheel from another version: "
            f"{entry['wheel_filename']}")
        assert entry["wheel"]["files"], f"{entry['version']}: no file table"

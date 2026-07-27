"""This suite tests the wrapper. Coverage for the core belongs to the core.

WHAT WENT WRONG. Ten modules here are four-line back-compat shims that alias a
module in `invisible_core` - `prefs`, `download`, `constants`, `_geo`, `_proxy`,
`_headless`, `_webgl_personas`, `config`, `sync_api`, `__main__`. Because
importing them works, 198 tests covering core behaviour ended up in this suite,
and the core's own suite never grew them.

That was not academic. Measured 2026-07-27, one realistic one-line break per
module, run against each suite separately:

    cloak_prefs() -> {}                         core SURVIVED   wrapper CAUGHT
    SOCKS scheme detection -> always False      core SURVIVED   wrapper CAUGHT
    the scheme never stripped from a server     core SURVIVED   wrapper CAUGHT
    _proxy_is_set -> always True                core SURVIVED   wrapper CAUGHT
    the locale -> always en-US                  core SURVIVED   wrapper CAUGHT
    get_default_args() -> ["-headless"]         core SURVIVED   wrapper CAUGHT

Six ways to publish a broken invisible-core with its pre-push gate green and its
publish gate green, because the only suite that could see the break belonged to
a different package on a different release cadence.

The 198 tests are in `invisible_core/tests/` now. This gate is what stops the
next one from landing here: a test that reaches core code through a shim is
testing the core, wherever the file happens to sit.

WHAT IS STILL ALLOWED. `test_backcompat.py`, whose entire job is proving the
shims still resolve - that IS wrapper behaviour, and the day it stops being
allowed here is the day the shims can be deleted.

The shim list is DERIVED, not written down: a shim is a module in this package
whose source rebinds `sys.modules[__name__]`. A hand-kept list is a shorter list
that drifts from the real one, which is the same failure this file exists for.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "invisible_playwright"
_TESTS = pathlib.Path(__file__).resolve().parent

#: Its job is the shims themselves.
_ALLOWED = {"test_backcompat.py"}


def _is_shim(path: pathlib.Path) -> bool:
    """True when the module hands its own name over to another module."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Attribute)
                    and target.value.attr == "modules"):
                return True
    return False


def shim_modules() -> set[str]:
    names = set()
    if not _SRC.is_dir():
        return names
    for path in _SRC.iterdir():
        if path.suffix == ".py" and _is_shim(path):
            names.add(path.stem)
        elif path.is_dir() and _is_shim(path / "__init__.py"):
            names.add(path.name)
    return names


def _imported_shims(path: pathlib.Path, shims: set[str]) -> set[str]:
    """Which shims this test file imports, however it spells the import."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if parts[0] == "invisible_playwright":
                if len(parts) > 1 and parts[1] in shims:
                    found.add(parts[1])
                elif len(parts) == 1:
                    found |= {a.name for a in node.names} & shims
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "invisible_playwright" and len(parts) > 1 \
                        and parts[1] in shims:
                    found.add(parts[1])
    return found


def test_the_package_still_has_shims_to_guard():
    """A gate whose subject vanished passes vacuously. If the shims are ever
    deleted, this file has no job and should go with them - loudly, not by
    quietly passing over an empty set."""
    assert shim_modules(), (
        "no back-compat shims found in invisible_playwright. Either they were "
        "removed - in which case delete this file and test_backcompat.py - or "
        "_is_shim() no longer recognises one, and every check below is vacuous.")


def test_no_test_reaches_the_core_through_a_shim():
    shims = shim_modules()
    offenders = {}
    # rglob, not glob. The first cut used glob and passed over `tests/unit/`,
    # which is where the one file covering `config.get_default_args` sat - so
    # the gate reported a clean suite while the exact class of misplacement it
    # exists to find was one directory down. A scan that only looks where you
    # remembered to put things is the shape this whole file is about.
    for path in sorted(_TESTS.rglob("test_*.py")):
        if path.name in _ALLOWED or "playwright-upstream" in path.parts:
            continue
        hit = _imported_shims(path, shims)
        if hit:
            offenders[str(path.relative_to(_TESTS))] = sorted(hit)

    assert not offenders, (
        "these test files reach invisible_core through a back-compat shim, so "
        "they are covering the core from the wrong suite:\n  " +
        "\n  ".join(f"{f}: {', '.join(m)}" for f, m in offenders.items()) +
        "\n\nMove them to invisible_core/tests/ and import invisible_core.<mod> "
        "directly. If a test genuinely covers how THIS package uses the core, "
        "import the wrapper module that does the using (launcher, _session, "
        "cli, _engine), not the aliased core module.")


def test_the_gate_sees_an_import_however_it_is_spelled(tmp_path):
    """Its own known-bad input. Three spellings, because a scan that only knew
    one of them would pass over the other two and read exactly like a clean
    suite - which is the shape of every defect this pass has been closing."""
    shims = {"prefs", "download"}
    for source in (
        "from invisible_playwright.prefs import translate\n",
        "from invisible_playwright import prefs\n",
        "import invisible_playwright.download as dl\n",
    ):
        probe = tmp_path / "test_probe.py"
        probe.write_text(source, encoding="utf-8")
        assert _imported_shims(probe, shims), f"missed: {source!r}"

    probe = tmp_path / "test_probe.py"
    probe.write_text("from invisible_playwright.launcher import "
                     "InvisiblePlaywright\n", encoding="utf-8")
    assert not _imported_shims(probe, shims), "a real wrapper import was flagged"

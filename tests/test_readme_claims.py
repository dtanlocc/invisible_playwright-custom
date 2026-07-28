"""The README is the first thing a stranger runs. It has to be runnable.

Four of the five lines in its CLI block were `command not found`: they used
`invisible_playwright` with an underscore, while the installed console script is
`invisible-playwright` with a hyphen. The Install section two hundred lines
above was correct (`python -m invisible_playwright ...`), which is how the CLI
block survived - anybody testing the quickstart never reached it.

Nothing here reads prose. These check the claims that are mechanically
checkable: that a documented subcommand exists, that a documented environment
variable is one the code reads, and that the download size is not the one from
two engines ago.
"""
from __future__ import annotations

import pathlib
import re
import tomllib

import pytest

pytestmark = pytest.mark.unit

_REPO = pathlib.Path(__file__).resolve().parents[1]
_README = _REPO / "README.md"


def _readme() -> str:
    return _README.read_text(encoding="utf-8")


def _declared_script() -> str:
    data = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"].get("scripts") or {}
    assert scripts, "the package declares no console script"
    return sorted(scripts)[0]


def test_the_readme_never_invokes_a_command_that_is_not_installed():
    """The exact failure: `invisible_playwright fetch` at a shell prompt.

    Only the module form takes an underscore. Any bare invocation must use the
    name pip actually puts on PATH.
    """
    script = _declared_script()
    bad = [
        line.strip()
        for line in _readme().splitlines()
        # a shell line starting with the underscored name, but NOT `python -m`
        if re.match(r"^\s*invisible_playwright\s+\w", line)
    ]
    assert not bad, (
        f"these README lines invoke a command that is not installed - the "
        f"console script is {script!r}:\n  " + "\n  ".join(bad))


def test_every_subcommand_the_readme_shows_actually_exists():
    """A documented subcommand that argparse rejects sends a reader looking for
    their own mistake."""
    from invisible_playwright import cli

    parser = cli.build_parser()
    known = set()
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices:
            known |= set(action.choices)
    shown = set(re.findall(r"^\s*invisible-playwright\s+([a-z-]+)", _readme(), re.M))
    unknown = sorted(shown - known)
    assert not unknown, (
        f"the README documents subcommands the CLI does not have: {unknown}. "
        f"It accepts {sorted(known)}")


def test_the_readme_does_not_hide_a_subcommand_the_cli_offers():
    """`doctor` existed and appeared nowhere. It is the command whose output a
    bug report needs, so leaving it undocumented costs twice."""
    from invisible_playwright import cli

    parser = cli.build_parser()
    known = set()
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices:
            known |= set(action.choices)
    text = _readme()
    missing = sorted(name for name in known if name not in text)
    assert not missing, f"these CLI subcommands are undocumented: {missing}"


def test_the_stated_download_size_matches_the_sealed_assets():
    """It said ~100 MB. The largest sealed asset is 238 MB, and unpacking is
    544 MB - a 2.4x understatement on the one number a user checks against
    their disk and their patience before starting.
    """
    import json

    import invisible_core

    seal = json.loads(
        (pathlib.Path(invisible_core.__file__).with_name("seal.json"))
        .read_text(encoding="utf-8"))
    largest_mb = max(a["size"] for a in seal["assets"].values()) / (1024 * 1024)
    text = _readme()
    stated = [int(n) for n in re.findall(r"~?(\d{2,4})\s*MB", text)]
    assert stated, "the README no longer states a download size at all"
    # EVERY figure must be plausible, not merely one of them. The first version
    # of this test accepted the set if ANY value was close, so changing one of
    # the two occurrences back to the old ~100 MB left it green - a check that
    # tolerates a wrong number beside a right one.
    #
    # The band spans the smallest sealed asset to the unpacked size, because the
    # page legitimately quotes both.
    smallest_mb = min(a["size"] for a in seal["assets"].values()) / (1024 * 1024)
    lo, hi = smallest_mb * 0.85, largest_mb * 2.6
    wrong = sorted(n for n in stated if not (lo <= n <= hi))
    assert not wrong, (
        f"the README quotes {wrong} MB, outside the {lo:.0f}-{hi:.0f} MB the "
        f"seal supports (assets {smallest_mb:.0f}-{largest_mb:.0f} MB, ~544 MB "
        f"unpacked). A size wrong by more than a rounding error is worse than "
        f"no size")


#: Where the environment variables are documented for a reader. NOT the README:
#: the "Environment variables" table was removed from it on 2026-07-28, because
#: every row described something the package does by itself - it downloads,
#: verifies a sha256, caches, picks a cursor engine - and none of it is a step
#: anybody takes. The table was also a THIRD copy, after docs/configuration.md and
#: docs/installation.md.
_ENV_DOC = "docs/configuration.md"

#: Prefixes that make a name ours. A knob belonging to Playwright or to the OS is
#: not this project's to document or to read.
_ENV_PREFIXES = ("INVISIBLE_PLAYWRIGHT_", "INVPW_", "STEALTHFOX_", "INVISIBLE_CORE_")


def _documented_env_names() -> list:
    """Read the list out of the doc page instead of hardcoding it.

    The hardcoded version named four, and there are more than four - so a fifth
    knob could be documented and read by nothing without this noticing. Deriving
    it also means the test follows the page rather than having to be edited
    alongside it, which is how the four came to be about the README after the
    README stopped mentioning them.
    """
    import re

    path = _REPO / _ENV_DOC
    assert path.is_file(), f"{_ENV_DOC} is gone; this test has lost its subject"
    text = path.read_text(encoding="utf-8")
    names = sorted({m for m in re.findall("[A-Z][A-Z0-9_]{4,}", text)
                    if m.startswith(_ENV_PREFIXES)})
    assert len(names) >= 5, (
        f"only {len(names)} environment variables found in {_ENV_DOC}: {names}. "
        f"Either the page stopped documenting them - in which case this test is "
        f"passing over an empty set - or the prefixes above no longer match.")
    return names


@pytest.mark.parametrize("name", _documented_env_names())
def test_documented_environment_variables_are_read_somewhere(name):
    """A documented knob that nothing reads is worse than an undocumented one:
    the reader sets it, sees no effect, and distrusts the rest of the page."""
    # Some of these are read by the CORE, not by this package. The first version
    # looked for them in `_REPO.parent / "invisible_core" / "src"` - a SIBLING
    # CHECKOUT, which exists on the workbench and nowhere else. On CI, where only
    # this repo is checked out and the core arrives as a wheel, that path is
    # missing, the comprehension yields nothing, and the test reported that a
    # documented variable is read by no module. It was reading the developer's
    # directory layout.
    #
    # The INSTALLED package is the right thing to ask either way: it is what a
    # user's environment actually contains, editable checkout or wheel.
    import invisible_core

    roots = [_REPO / "src", pathlib.Path(invisible_core.__file__).parent]
    hits = [
        path
        for root in roots
        for path in root.rglob("*.py")
        if "__pycache__" not in path.as_posix()
        and name in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits, (
        f"{_ENV_DOC} documents {name}, which no shipped module reads. Either wire "
        f"it up or take the row out - a knob with no effect makes a reader "
        f"distrust the whole page.")

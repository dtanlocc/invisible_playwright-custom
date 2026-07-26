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


@pytest.mark.parametrize("name", [
    "INVISIBLE_PLAYWRIGHT_CACHE_DIR",
    "INVPW_BINARY_PATH",
    "STEALTHFOX_GITHUB_TOKEN",
    "INVPW_CURSOR_ENGINE",
])
def test_documented_environment_variables_are_read_somewhere(name):
    """A documented knob that nothing reads is worse than an undocumented one:
    the reader sets it, sees no effect, and distrusts the rest of the page."""
    assert name in _readme(), f"{name} is no longer documented"
    hits = [
        path
        for path in (_REPO / "src").rglob("*.py")
        if name in path.read_text(encoding="utf-8", errors="ignore")
    ] + [
        path
        for path in (_REPO.parent / "invisible_core" / "src").rglob("*.py")
        if (_REPO.parent / "invisible_core").is_dir()
        and name in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits, f"the README documents {name}, which no shipped module reads"

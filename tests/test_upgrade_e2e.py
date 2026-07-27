"""What happens to somebody who ALREADY has this installed.

Every install test next door starts from an empty venv, which is the path a new
user takes exactly once. Every existing user takes a different one - `pip
install -U`, or an environment that has drifted - and none of it was covered.

That matters more here than in most packages, because of the shape of the
coupling: the wrapper declares an EXACT `invisible-core==X.Y.Z`, so an upgrade
has to move two distributions in step, and a half-moved environment is repaired
IN PROCESS at import rather than raising. A repair that silently does the wrong
thing therefore looks identical to one that worked - from the outside, the
import simply returns.

The failures these are aimed at:

  * `pip install -U invisible-playwright` leaves the OLD core behind, so the
    wrapper drives an engine configured by a core it was never tested against;
  * the repair runs when the core is already imported, swapping it underneath
    objects the caller holds - two versions alive in one process;
  * a user who pins an old core by hand gets a green `pip check` and a broken
    session, which is the failure mode the exact specifier was adopted to make
    loud in the first place.

Marked `e2e`: builds venvs and talks to the index.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from invisible_core.testing import make_venv, run_checked, venv_python

pytestmark = pytest.mark.e2e

WRAPPER = "invisible-playwright"
CORE = "invisible-core"


# The venv mechanics live in invisible_core.testing - see the note in
# test_release_e2e.py. This file needs several venvs inside ONE workspace (it
# installs an old release into one and upgrades it), which is why it builds them
# individually rather than through `throwaway_venv`.
_run = run_checked
_venv_python = venv_python


def _fresh_venv(root: Path, name: str) -> Path:
    return make_venv(root / name)


def _versions(py: Path) -> dict:
    out = _run([str(py), "-c",
                "import json; from importlib.metadata import version; "
                f"print(json.dumps({{'wrapper': version({WRAPPER!r}), "
                f"'core': version({CORE!r})}}))"], timeout=60).stdout
    return json.loads(out.strip().splitlines()[-1])


def _released_versions(py: Path, dist: str) -> list[str]:
    """Versions the index will serve, newest last. Read from pip itself so the
    test does not carry a hardcoded list that goes stale on the next release."""
    r = _run([str(py), "-m", "pip", "index", "versions", dist],
             timeout=180, check=False)
    text = r.stdout + r.stderr
    for line in text.splitlines():
        if "Available versions:" in line:
            return [v.strip() for v in
                    line.split("Available versions:", 1)[1].split(",")][::-1]
    pytest.skip(f"pip could not list versions for {dist}: {text[-500:]}")


@pytest.fixture(scope="module")
def workspace():
    root = Path(tempfile.mkdtemp(prefix="invpw-upgrade-"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_upgrading_from_the_previous_release_moves_the_core_too(workspace: Path):
    """The one every existing user will run.

    Installs the PREVIOUS published wrapper, then upgrades. Both distributions
    must end up where the new wrapper's pin says, and pip must agree. Before
    the pin was an exact specifier this was the failure: a wrapper that moved
    while its core stayed put, reported clean by `pip check` because a direct
    URL has no version to compare.
    """
    py = _fresh_venv(workspace, "upgrade")
    released = _released_versions(py, WRAPPER)
    if len(released) < 2:
        pytest.skip("only one release on the index; nothing to upgrade FROM")
    previous = released[-2]

    _run([str(py), "-m", "pip", "install", "--no-cache-dir",
          f"{WRAPPER}=={previous}"], timeout=900)
    before = _versions(py)
    assert before["wrapper"] == previous

    _run([str(py), "-m", "pip", "install", "--no-cache-dir", "--upgrade",
          WRAPPER], timeout=900)
    after = _versions(py)

    assert after["wrapper"] != previous, "the upgrade did not move the wrapper"
    _run([str(py), "-m", "pip", "check"], timeout=180)

    declared = _run([str(py), "-c",
                     "from importlib.metadata import requires; "
                     f"print([r for r in requires({WRAPPER!r}) "
                     "if r.startswith('invisible')][0])"], timeout=60).stdout.strip()
    assert after["core"] in declared, (
        f"after upgrading, the wrapper declares {declared!r} and the "
        f"environment holds {CORE} {after['core']} - the two moved out of step")


def test_the_upgraded_environment_imports_and_reports_one_core(workspace: Path):
    """An import that repairs must leave ONE core in sys.modules.

    The dangerous outcome is not an exception - it is a swap performed under
    objects the caller already holds, which leaves two versions alive and shows
    up much later as behaviour that does not match the version anybody reports.
    """
    py = _venv_python(workspace / "upgrade")
    if not py.exists():
        pytest.skip("the upgrade fixture did not run")
    out = _run([str(py), "-c",
                "import invisible_playwright, sys, invisible_core; "
                "from importlib.metadata import version; "
                "mods = sorted({m.split('.')[0] for m in sys.modules "
                "               if m.startswith('invisible_core')}); "
                "print(mods); print(version('invisible-core')); "
                "print(invisible_core.__file__)"], timeout=180).stdout.strip()
    mods, reported, path = out.splitlines()[:3]
    assert mods == "['invisible_core']", f"more than one core root: {mods}"
    # The imported module must be the INSTALLED one, not a checkout that
    # happened to be on the path - a venv test that silently read the
    # developer's working tree would pass everywhere and mean nothing.
    assert "site-packages" in path, (
        f"the core was imported from {path}, which is not the install under "
        f"test")
    # And the version the metadata reports must be the one that module derives
    # from its own packaged seal: if a swap left a stale module object behind,
    # these disagree.
    derived = _run([str(py), "-c",
                    "import invisible_core; print(invisible_core.__version__)"],
                   timeout=120).stdout.strip()
    assert derived == reported, (
        f"metadata says {CORE} {reported} but the imported module derives "
        f"{derived} - two versions are alive in one process")


def test_a_hand_pinned_old_core_is_reported_by_pip_check(workspace: Path):
    """The failure the exact specifier exists to expose.

    A user pins an old core by hand - a lockfile, a constraints file, a
    `--no-deps` install. With a direct-URL dependency there is no version for
    pip to compare and `pip check` reports clean on a broken environment; with
    a real specifier it exits 1 and names both sides.
    """
    py = _fresh_venv(workspace, "pinned")
    _run([str(py), "-m", "pip", "install", "--no-cache-dir", WRAPPER],
         timeout=900)
    cores = _released_versions(py, CORE)
    if len(cores) < 2:
        pytest.skip("only one core release on the index")
    older = cores[-2]

    _run([str(py), "-m", "pip", "install", "--no-cache-dir", "--no-deps",
          "--force-reinstall", f"{CORE}=={older}"], timeout=600)

    checked = _run([str(py), "-m", "pip", "check"], timeout=180, check=False)
    assert checked.returncode != 0, (
        "pip check reported a deliberately mismatched environment as clean. "
        "That is the exact blindness the direct-URL dependency had, and it "
        "means the pin has stopped being a real specifier")
    assert CORE in (checked.stdout + checked.stderr)


def test_the_mismatch_repairs_itself_at_import_without_a_restart(workspace: Path):
    """Auto-repair, driven end to end rather than argued about.

    The environment above is genuinely broken. Importing the wrapper must fix
    it in the SAME process - that is the documented behaviour, and the reason
    the repair is worth its complexity. Asserted on the version afterwards,
    not on the absence of an exception, because "no exception" is also what a
    repair that did nothing looks like.
    """
    py = _venv_python(workspace / "pinned")
    if not py.exists():
        pytest.skip("the pinned fixture did not run")
    before = _versions(py)["core"]

    out = _run([str(py), "-c",
                "import invisible_playwright; "
                "from importlib.metadata import version; "
                "print('AFTER', version('invisible-core'))"],
               timeout=900)
    after = out.stdout.strip().splitlines()[-1].split()[-1]
    assert after != before, (
        f"the core is still {before} after importing the wrapper - the repair "
        f"did not run, or ran and changed nothing.\n{out.stdout[-2000:]}")
    _run([str(py), "-m", "pip", "check"], timeout=180)

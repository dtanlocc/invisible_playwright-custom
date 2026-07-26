"""The naming guard: no shipped file may carry a name we do not publish.

WHY THIS FILE EXISTS AND WHY IT FAILS CLOSED
--------------------------------------------
Naming a commercial protection product, a proxy vendor or a target site in a
public repo is a legal and credibility problem, and it is the one rule in this
package that no other test covers. The previous version of this check had two
holes, and both of them made it useless in exactly the situation it exists for:

  * it called ``pytest.skip`` when the word list was not configured, and a skip
    is GREEN. On any machine that had not exported the variable - which is
    every machine by default, including a fresh clone and CI - the guard
    checked nothing and the suite still said OK. A check that quietly checks
    nothing is worse than no check at all, because it buys confidence it has
    not earned. So: an unconfigured guard is a FAILURE that names what to set;
  * it scanned exactly one module, the one it happened to live next to. A
    forbidden name in any of the other sixty-odd shipped files walked straight
    through. So: the scan enumerates everything this package ships, derived
    from the packaging config rather than from a list written here that would
    go stale the first time a directory is added.

WHY THE WORD LIST IS NOT WRITTEN HERE
-------------------------------------
A scanner that carries its own tokens publishes exactly what it exists to keep
out. That mistake has already been made once in this project: a public
validator shipped a compiled regex containing the very site name it was meant
to stop. The list therefore lives outside every public repo and is loaded from
the path in ``STEALTH_EXTRA_LEAK_PATTERNS`` - the same variable the release
validator consumes, so there is one word list and one place to update it.

Nothing here launches a browser, opens a socket, or reads anything outside the
repository and that one file.
"""
from __future__ import annotations

import os
import pathlib
import tomllib

import pytest

pytestmark = pytest.mark.unit


_ENV = "STEALTH_EXTRA_LEAK_PATTERNS"

_UNCONFIGURED = (
    f"{_ENV} does not point at a readable word list, so this guard checked "
    f"NOTHING. That is a failure, not a pass. Export {_ENV} with the path of "
    "the word list (one token per line, blank lines and '#' comments ignored) "
    "and re-run. The list is deliberately not carried in this repository: a "
    "scanner that ships its own tokens publishes what it exists to keep out."
)

_REPO = pathlib.Path(__file__).resolve().parents[1]

# Files that are never text and would only add decode noise to the scan.
_BINARY_SUFFIXES = {".pyc", ".pyd", ".so", ".png", ".jpg", ".gif", ".ico",
                    ".zip", ".gz", ".whl", ".mmdb", ".woff", ".woff2", ".ttf"}


# ──────────────────────────────────────────────────────────────────────
# what "shipped" means, taken from the packaging config, not from memory
# ──────────────────────────────────────────────────────────────────────

def _packaging() -> dict:
    with (_REPO / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def _ship_spec() -> tuple[list[str], list[str]]:
    """(roots, excluded prefixes) exactly as pyproject declares them.

    Read from the build config so that adding a directory to the wheel or the
    sdist automatically puts it inside the guard. A hand-written list here
    would be one more thing to remember, and the whole failure mode this file
    is fixing is a guard whose reach was decided once and never revisited.
    """
    cfg = _packaging().get("tool", {}).get("hatch", {}).get("build", {})
    targets = cfg.get("targets", {})
    roots: list[str] = []
    excludes: list[str] = []
    for target in ("wheel", "sdist"):
        spec = targets.get(target, {})
        roots.extend(spec.get("packages", ()))
        roots.extend(spec.get("include", ()))
        excludes.extend(spec.get("exclude", ()))
    # Order-preserving dedupe; the paths are few and the message is nicer.
    return list(dict.fromkeys(roots)), list(dict.fromkeys(excludes))


def _excluded(rel: str, excludes: list[str]) -> bool:
    for pattern in excludes:
        pat = pattern.replace("\\", "/").strip("/")
        if pat.startswith("*"):
            if rel.endswith(pat[1:]):
                return True
        elif rel == pat or rel.startswith(pat + "/"):
            return True
    return False


def shipped_files() -> list[pathlib.Path]:
    """Every text file this package puts inside a wheel or an sdist."""
    roots, excludes = _ship_spec()
    out: list[pathlib.Path] = []
    for root in roots:
        base = _REPO / root
        candidates = [base] if base.is_file() else sorted(base.rglob("*"))
        for path in candidates:
            if not path.is_file():
                continue
            rel = path.relative_to(_REPO).as_posix()
            if "__pycache__" in rel or path.suffix in _BINARY_SUFFIXES:
                continue
            if _excluded(rel, excludes):
                continue
            out.append(path)
    return sorted(set(out))


# ──────────────────────────────────────────────────────────────────────
# the word list
# ──────────────────────────────────────────────────────────────────────

def load_tokens() -> list[str]:
    """The forbidden tokens, or a hard failure saying how to supply them."""
    raw = os.environ.get(_ENV)
    if not raw:
        pytest.fail(_UNCONFIGURED)
    path = pathlib.Path(raw)
    if not path.is_file():
        pytest.fail(_UNCONFIGURED + f" (configured path is not a file: {raw})")
    tokens = [
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not tokens:
        pytest.fail(_UNCONFIGURED + " (the configured file has no tokens in it)")
    return tokens


def scan(text: str, tokens: list[str]) -> list[str]:
    """Tokens present in ``text``. Case-insensitive, literal, substring."""
    low = text.lower()
    return [t for t in tokens if t in low]


# ──────────────────────────────────────────────────────────────────────
# the guard
# ──────────────────────────────────────────────────────────────────────

def test_the_word_list_is_configured():
    """Absent configuration is red, never green and never a skip.

    Stated as its own test so the reason the suite is red is the first thing
    the report says, instead of being buried in the scan's failure.
    """
    tokens = load_tokens()
    assert len(tokens) >= 5, (
        f"only {len(tokens)} token(s) loaded - that is not the real list"
    )


def test_the_scan_reaches_every_shipped_file():
    """The second hole: a guard that scans one module proves nothing.

    Anchors on both ends of the package - a module, a test, and the readme -
    so that a packaging change which quietly drops a directory out of the scan
    fails here rather than going unnoticed.
    """
    files = {p.relative_to(_REPO).as_posix() for p in shipped_files()}
    for anchor in (
        "src/invisible_playwright/_motion.py",
        "src/invisible_playwright/_behaviour.py",
        "src/invisible_playwright/_cursor.py",
        "src/invisible_playwright/launcher.py",
        "tests/test_behaviour.py",
        "tests/test_cursor_wiring.py",
        # NOT this file. It is excluded from the sdist on purpose: it fails
        # closed without STEALTH_EXTRA_LEAK_PATTERNS, and that word list lives
        # outside every public repo, so shipping it would hand every user three
        # red tests about our release hygiene that they cannot make green. The
        # anchors below still prove the scan reaches src/, tests/ and the root.
        "README.md",
        "pyproject.toml",
    ):
        assert anchor in files, f"{anchor} is shipped but not scanned"
    # Every module in the package, not just the ones named above.
    on_disk = {
        p.relative_to(_REPO).as_posix()
        for p in (_REPO / "src" / "invisible_playwright").rglob("*.py")
        if "__pycache__" not in p.as_posix()
    }
    assert on_disk <= files, sorted(on_disk - files)
    assert len(files) > 40, f"only {len(files)} shipped files found"


def test_no_shipped_file_carries_a_forbidden_name():
    """The check itself. Runs over everything, reports counts, never tokens."""
    tokens = load_tokens()
    offenders: list[str] = []
    for path in shipped_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits = scan(text, tokens)
        if hits:
            rel = path.relative_to(_REPO).as_posix()
            offenders.append(f"{rel}: {len(hits)} token(s)")
    assert not offenders, (
        "forbidden name(s) in shipped files (tokens deliberately not printed - "
        "grep the file against the word list locally):\n  "
        + "\n  ".join(offenders)
    )


def test_the_guard_rejects_a_known_bad_input():
    """A gate that has only ever printed PASS is not a gate.

    The known-bad input is built from a token taken out of the loaded list at
    runtime, so this test proves the matcher fires without any forbidden name
    being written into a file that ships.
    """
    tokens = load_tokens()
    token = max(tokens, key=len)  # the longest token: least likely to be a
    # substring of ordinary prose, so the assertion below is about the matcher
    # rather than about an accidental hit.
    for sample in (
        f"# we tested against {token} last week\n",
        f"URL = 'https://www.{token.upper()}.com/checkout'\n",
        f"note: {token.capitalize()} blocks the old build\n",
    ):
        assert scan(sample, tokens), (
            "the scanner missed a token it was given verbatim - "
            "the guard is not matching at all"
        )
    assert not scan("a perfectly ordinary line of source code\n", ["zzqqxx"])

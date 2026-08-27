"""The Playwright fork holds, and it does not silently dissolve.

WHY THIS GATE IS NEEDED. The way this fork dies is not noisy: it is
someone writing ``from playwright.sync_api import ...`` in a new file. The
``playwright`` package stays installable and importable - we keep it on purpose
among the dev dependencies, so we can compare the two branches - so that
line WORKS. It's just that the code that runs is no longer ours, and no
error says so. With enough lines like that, the fork becomes a dead folder
that weighs 9 MB and does nothing.

The same checks also apply to the end user: a wheel missing
``_driver/`` or ``_pw/`` installs just fine and dies on first launch.
"""

import pathlib
import re

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "invisible_playwright"
TESTS = pathlib.Path(__file__).resolve().parent

#: The vendored client's own files import themselves under their full name,
#: so they are not violations. Same for Microsoft's upstream suite, which is a
#: reference copy and should be read as-is.
ESCLUSI = ("_pw", "_driver", "playwright-upstream", "vendor")

RIGA_VIETATA = re.compile(r"^\s*(from playwright[\s.]|import playwright[\s.])")


def _files_to_check():
    for root in (SRC, TESTS):
        for f in root.rglob("*.py"):
            if any(p in ESCLUSI for p in f.parts):
                continue
            yield f


def test_no_one_imports_the_installed_playwright():
    """The line that dissolves the fork, and that raises no error."""
    violators = []
    for f in _files_to_check():
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if RIGA_VIETATA.match(line):
                violators.append("%s:%d  %s" % (f.name, n, line.strip()))
    assert not violators, (
        "these files import the INSTALLED playwright package instead of the "
        "vendored client in _pw/. It works, and that is exactly why it's a "
        "defect: the code that runs is not the one we think we are shipping.\n  "
        + "\n  ".join(violators))


def test_the_vendored_client_is_the_one_imported():
    from invisible_playwright._pw.sync_api import sync_playwright
    module = pathlib.Path(sync_playwright.__module__.replace(".", "/"))
    import invisible_playwright._pw as pw
    assert "invisible_playwright" in str(pathlib.Path(pw.__file__).resolve()), (
        "the imported client is not the one inside our package")


def test_the_driver_points_inside_us():
    from invisible_playwright._pw._impl._driver import driver_root
    r = driver_root()
    assert r.name == "_driver"
    assert "invisible_playwright" in str(r)
    assert (r / "package" / "cli.js").is_file(), (
        "missing %s: without cli.js the browser does not start" % (r / "package" / "cli.js"))


def test_the_bundle_we_want_to_modify_exists():
    """The fork exists so this file can be changed. If it disappears, the fork doesn't exist."""
    from invisible_playwright._pw._impl._driver import driver_root
    core = driver_root() / "package" / "lib" / "coreBundle.js"
    assert core.is_file(), "missing coreBundle.js, which is the whole reason for the fork"
    assert core.stat().st_size > 1_000_000


def test_utils_bundle_exists():
    """Measured: removed, the driver dies with 'Connection closed while reading'."""
    from invisible_playwright._pw._impl._driver import driver_root
    u = driver_root() / "package" / "lib" / "utilsBundle.js"
    assert u.is_file(), "utilsBundle.js is genuinely needed, it is not dead weight"


@pytest.mark.parametrize("name", ["LICENSE", "NOTICE", "ThirdPartyNotices.txt"])
def test_the_forks_license_files_exist(name):
    """Apache-2.0 is not a formality: it is the condition for redistributing.

    The pyproject declares ``MIT AND Apache-2.0`` precisely for this folder.
    """
    from invisible_playwright._pw._impl._driver import driver_root
    assert (driver_root() / "package" / name).is_file()


def test_the_node_version_is_declared_exactly_once():
    from invisible_playwright import _node
    assert _node.NODE_VERSION.startswith("v")
    elsewhere = [f.name for f in _files_to_check()
                 if f.name != "_node.py" and f.name != "test_fork.py"
                 and _node.NODE_VERSION in f.read_text(encoding="utf-8")]
    assert not elsewhere, (
        "the Node version also appears in %s: a number written twice "
        "drifts" % elsewhere)


def _injected_sources():
    """The strings the bundle injects into the page, one per physical line.

    They are declared as ``sourceN = '...'`` with SINGLE quotes and with newlines
    written as two characters, so each one occupies a single line of the file.
    """
    from invisible_playwright._pw._impl._driver import driver_root
    text = (driver_root() / "package" / "lib" / "coreBundle.js").read_text(
        encoding="utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*(source\d*) = '", line)
        if m:
            yield number, m.group(1), line




def _unprotected_quote(line):
    """Where the single-quoted string closes before the end, or None.

    Returns the text that follows the closing quote, so whoever reads the
    failure immediately sees what was left outside the string.
    """
    backslash = chr(92)
    body = line[line.index("'") + 1:]
    k = 0
    while k < len(body):
        if body[k] == backslash:
            k += 2
            continue
        if body[k] == "'":
            rest = body[k + 1:].strip()
            return None if rest in (";", "", ");") else rest[:80]
        k += 1
    return "the string never closes at all"


def test_the_injected_sources_have_balanced_quotes():
    """An apostrophe in a comment closes the string and breaks the whole bundle.

    Happened on 2026-08-24: an Italian comment added inside ``source4``
    contained ``piu'`` and ``cioe'``. The string closed right there, the file
    became invalid JavaScript and the driver stopped starting at all.

    The defect is not visible to the eye - those lines are hundreds of
    thousands of characters long - and no test that only imports the Python
    package sees it. No Node required: it holds even where the runtime has not
    been downloaded yet.
    """
    found = list(_injected_sources())
    assert found, "no injected source found: the check would go silent"
    for number, name, line in found:
        rest = _unprotected_quote(line)
        assert rest is None, (
            "coreBundle.js:%d, %s: the injected string closes too early, "
            "what remains after it is %r - almost always an apostrophe inside a "
            "comment" % (number, name, rest))


def test_the_quote_check_sees_a_real_apostrophe():
    """The known-bad mutation, on the exact form that broke the bundle.

    ⛔ THE ITALIAN IN THE THREE FIXTURES BELOW IS DELIBERATE AND MUST NOT BE
    TRANSLATED. The defect IS an Italian word written with a trailing
    apostrophe - `piu'` - inside a JavaScript comment: that apostrophe closes
    the single-quoted string the comment lives in, and the rest of the bundle
    becomes invalid JavaScript. Replace it with English and the mutation stops
    reproducing the bug, so this test would go green on an input that can no
    longer fail - a gate that checks nothing while still printing PASS.

    This is why `scripts/check_english_only.py` names this one file in its
    exclusion list. The exemption is one path, never a folder: a sibling test
    written in Italian by accident is still caught.
    """
    good = "    source4 = '\nmarkTargetElements() {\n  // non dispatcha niente\n}';"
    assert _unprotected_quote(good) is None
    bad = "    source4 = '\nmarkTargetElements() {\n  // non dispatcha piu' niente\n}';"
    assert _unprotected_quote(bad) is not None
    never_closed = "    source4 = '\nqualcosa senza fine"
    assert _unprotected_quote(never_closed) == "the string never closes at all"

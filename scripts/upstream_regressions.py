"""No test that passes today may fail tomorrow.

⛔ THIS IS THE NET A REFACTOR NEEDS, and "the suite stays green" is not
available as one: of the 698 sync tests, 163 pass. Most of the red is either a
decision this package took on purpose - `perimeter.py` refuses 77 names - or a
hole nobody has filled yet. A gate that asked for green would be red forever
and would teach people to skip it.

So the question is narrower, and answerable without any green: **did anything
that worked stop working?**

⛔ READ FROM A JUNIT XML, AND THE FIRST VERSION READ THE PROGRESS LINE INSTEAD.
That looked cheap - pytest prints one character per test as it goes, in
collection order, so zipping it against `--collect-only` seemed to give the
same map without re-running anything. It is wrong, and by a margin a spot check
would have missed: on the real report there are **711 characters for 698
collected tests**. A test that fails and then errors in teardown prints TWO.
Pairing them would have attributed every outcome after the thirteenth
double-printing test to the wrong test, and the map would have looked
plausible. The length check refused it, which is the only reason it was caught.

A JUnit XML has one entry per test with its outcome. It costs a flag.

    python scripts/upstream_baseline.py <binary> --junit-xml out.xml
    python scripts/upstream_regressions.py --record out.xml
    python scripts/upstream_regressions.py --check  out.xml
    python scripts/upstream_regressions.py --selftest
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parent.parent
#: Where the reference lives. Committed on purpose: a net kept out of the
#: repository is a net that disagrees with the branch it is protecting.
REFERENCE = ROOT / "tests" / "gates" / "upstream_baseline.json"


def outcomes(xml_text: str) -> dict:
    """test id -> "passed" | "failed" | "error" | "skipped".

    ⛔ A `<testcase>` WITH NO CHILD IS THE ONLY PASS. JUnit says what went
    wrong by adding a child element - `failure`, `error`, `skipped` - and says
    a pass by adding nothing. Reading it the other way round, looking for a
    positive marker, silently turns every pass into an unknown.
    """
    root = ET.fromstring(xml_text)
    out = {}
    for case in root.iter("testcase"):
        name = "%s::%s" % (case.get("classname", ""), case.get("name", ""))
        esito = "passed"
        for child in case:
            tag = child.tag
            if tag in ("failure", "error", "skipped"):
                esito = tag if tag != "failure" else "failed"
                break
        # ⛔ A test can be recorded twice - a failure in the call phase and an
        # error in teardown. The WORSE outcome wins, so a teardown error can
        # never mask a passing call phase.
        if out.get(name, "passed") == "passed":
            out[name] = esito
    return out


def compare(before: dict, after: dict) -> tuple:
    """(regressions, repairs, disappeared). Only the first fails the gate."""
    regressions, repairs, gone = [], [], []
    for test, was in sorted(before.items()):
        now = after.get(test)
        if now is None:
            gone.append(test)
        elif was == "passed" and now != "passed":
            regressions.append((test, was, now))
        elif was != "passed" and now == "passed":
            repairs.append((test, was, now))
    return regressions, repairs, gone


def _xml(*cases: tuple) -> str:
    parts = ['<testsuites><testsuite name="p">']
    for classname, name, child in cases:
        parts.append('<testcase classname="%s" name="%s">' % (classname, name))
        if child:
            parts.append("<%s message='x'/>" % child)
        parts.append("</testcase>")
    parts.append("</testsuite></testsuites>")
    return "".join(parts)


def _selftest() -> int:
    before = outcomes(_xml(("a", "t1", None), ("a", "t2", None),
                           ("b", "t3", "failure")))
    cases = [
        ("identical", _xml(("a", "t1", None), ("a", "t2", None),
                           ("b", "t3", "failure")), 0),
        ("a passing test turns red", _xml(("a", "t1", None), ("a", "t2", "failure"),
                                          ("b", "t3", "failure")), 1),
        ("a passing test turns into an error",
         _xml(("a", "t1", None), ("a", "t2", "error"), ("b", "t3", "failure")), 1),
        ("a red one heals: NOT a regression",
         _xml(("a", "t1", None), ("a", "t2", None), ("b", "t3", None)), 0),
        ("a passing test turns into a skip: IS a regression",
         _xml(("a", "t1", None), ("a", "t2", "skipped"), ("b", "t3", "failure")), 1),
    ]
    broken = 0
    for label, xml, expected in cases:
        found, _, _ = compare(before, outcomes(xml))
        if len(found) != expected:
            broken += 1
        print("  %-50s %s (%d regressions, expected %d)"
              % (label, "ok" if len(found) == expected else "BROKEN",
                 len(found), expected))

    # ⛔ the case the progress-line version got wrong: one test recorded twice,
    # a failing call phase and an erroring teardown. It must not read as a pass.
    twice = _xml(("a", "t1", "failure"), ("a", "t1", "error"))
    read_back = outcomes(twice)
    ok = read_back.get("a::t1") == "failed"
    if not ok:
        broken += 1
    print("  %-50s %s (read %r)"
          % ("a test recorded twice is not a pass", "ok" if ok else "BROKEN",
             read_back.get("a::t1")))

    # and a test the reference knows that is no longer collected must not be
    # silently counted as fine.
    _, _, gone = compare(before, outcomes(_xml(("a", "t1", None))))
    ok2 = len(gone) == 2
    if not ok2:
        broken += 1
    print("  %-50s %s (%d)" % ("tests that vanished are reported",
                               "ok" if ok2 else "BROKEN", len(gone)))
    print("selftest: %d cases, %d broken" % (len(cases) + 2, broken))
    return 1 if broken else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("report", nargs="?", help="a JUnit XML from the baseline")
    p.add_argument("--record", action="store_true")
    p.add_argument("--check", action="store_true")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()
    if a.selftest:
        return _selftest()
    if not a.report:
        p.error("a JUnit XML is needed")

    now = outcomes(pathlib.Path(a.report).read_text(encoding="utf-8",
                                                    errors="replace"))
    if a.record:
        REFERENCE.parent.mkdir(parents=True, exist_ok=True)
        REFERENCE.write_bytes(json.dumps(now, indent=1, sort_keys=True)
                              .encode("utf-8"))
        counts: dict = {}
        for v in now.values():
            counts[v] = counts.get(v, 0) + 1
        print("recorded %d tests in %s" % (len(now), REFERENCE.name))
        print("  " + "  ".join("%s=%d" % kv for kv in sorted(counts.items())))
        return 0

    if not REFERENCE.exists():
        print("no reference recorded yet: run with --record first")
        return 2
    before = json.loads(REFERENCE.read_text(encoding="utf-8"))
    regressions, repairs, gone = compare(before, now)

    for test, was, is_now in regressions:
        print("REGRESSION  %s: %s -> %s" % (test, was, is_now))
    if repairs:
        print("(%d test(s) got BETTER, which this gate does not refuse)"
              % len(repairs))
    if gone:
        print("(%d recorded test(s) were not collected this time)" % len(gone))
    if regressions:
        print()
        print("UPSTREAM REGRESSIONS: %d test(s) that passed no longer do."
              % len(regressions))
        return 1
    print("UPSTREAM REGRESSIONS: none. %d recorded, %d of them passing."
          % (len(before), sum(1 for v in before.values() if v == "passed")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

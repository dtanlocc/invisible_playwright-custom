"""Turn a wall of upstream failures into a handful of causes.

⛔ A BASELINE THAT SAYS "412 FAILED" IS NOT A BASELINE. The number decides
nothing on its own: the same 412 could be one missing method reached from four
hundred tests, or four hundred separate defects, and those two answers lead to
completely different work. What is needed is the ERROR, grouped, with a count
and one example each.

⛔ AND THE GROUPS ARE NOT SEVERITY, THEY ARE PROVENANCE. A failure because the
suite asks for a feature this package refuses by name is not a defect - the
perimeter is a decision, written down, with `perimeter.py` as its source. A
failure because a method exists and answers wrongly is. Mixing them produces a
number that overstates the work and that nobody trusts twice.

    python scripts/upstream_triage.py <output-of-upstream_baseline>
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

#: The shapes a line can take, most specific first. ⛔ ORDER MATTERS: a message
#: naming the perimeter also contains the word "not", so a looser pattern above
#: a stricter one would swallow it and report a decision as a defect.
KINDS = [
    ("outside the perimeter (a decision, in perimeter.py)",
     re.compile(r"is part of .+, which invisible_playwright does not implement")),
    ("removed with the Node driver (a decision)",
     re.compile(r"does not exist in invisible_playwright")),
    ("no such method on the channel (a hole)",
     re.compile(r"has no method|no attribute '(\w+)'")),
    ("protocol refused the call (closed-world checkScheme)",
     re.compile(r"failed to call method|Expected .+ to be")),
    ("timed out waiting", re.compile(r"Timeout .*exceeded|no response in")),
    ("assertion on a value", re.compile(r"^E\s+assert|AssertionError")),
]


def classify(block: str) -> str:
    for name, pattern in KINDS:
        if pattern.search(block):
            return name
    return "other"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("report")
    p.add_argument("--examples", type=int, default=1)
    a = p.parse_args()

    text = pathlib.Path(a.report).read_text(encoding="utf-8", errors="replace")

    # The per-test blocks pytest prints under FAILURES, split on its own rule.
    blocks = re.split(r"^_{10,} (.+?) _{10,}$", text, flags=re.M)
    pairs = list(zip(blocks[1::2], blocks[2::2]))

    per_kind = collections.Counter()
    per_file = collections.Counter()
    examples: dict = {}
    for name, body in pairs:
        kind = classify(body)
        per_kind[kind] += 1
        per_file[name.split("::")[0] if "::" in name else name] += 1
        if kind not in examples:
            righe = [l for l in body.splitlines() if l.startswith("E ")]
            examples[kind] = (name, righe[-1].strip() if righe else "(no E line)")

    coda = text[-800:]
    print("=== what pytest counted ===")
    for l in coda.splitlines():
        if re.search(r"\d+ (passed|failed|error|skipped)", l):
            print("  " + l.strip())
    print()
    print("=== %d failure blocks, by CAUSE ===" % sum(per_kind.values()))
    for kind, n in per_kind.most_common():
        print("  %-52s %4d" % (kind, n))
        name, riga = examples[kind]
        print("        e.g. %s" % name)
        print("            %s" % riga[:150])
    print()
    print("=== the ten tests that carry the most ===")
    for f, n in per_file.most_common(10):
        print("  %-56s %4d" % (f, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())

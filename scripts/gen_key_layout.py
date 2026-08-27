"""Extracts the US keyboard layout from the driver bundle into `_juggler/keylayout.py`.

⛔ NEVER HAND-EDIT THIS. `Page.dispatchKeyEvent` expects `key`, `code`,
`keyCode` and `location` together, and there are ~230 entries: a
hand-copied table has two ways to go wrong that no test catches. The
first is a wrong `keyCode`, which the page reads back in
`event.keyCode` without the action failing. The second, worse one, is
an INCOMPLETE table: a missing key raises no error, it produces
`keyCode: 0` for a key that on every real Firefox has a number, and
that is a tell that lives in a field nobody looks at.

It has the same shape as `gen_juggler_protocol.py` and
`gen_injected_source.py`: a single source, generated, never two
numbers for the same thing (rule 16).

    python scripts/gen_key_layout.py            # regenerates _juggler/keylayout.py
    python scripts/gen_key_layout.py --check    # 1 if the tree file is stale
    python scripts/gen_key_layout.py --selftest # 6 mutations, plus 2 that must NOT trigger
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "src/invisible_playwright/_driver/package/lib/coreBundle.js"
OUTPUT = ROOT / "src/invisible_playwright/_juggler/keylayout.py"

#: The literal starts here. ⛔ It anchors on the variable NAME, not on
#: a table entry: anchoring on `"KeyA"` would tie the extraction to a
#: key that could move to a different line someday.
START = re.compile(r"USKeyboardLayout\s*=\s*\{")


#: The escapes the bundle actually uses. Whatever is not here is
#: passed through as-is, which is the right behavior for `\'` and
#: `\"`: the escape disappears and the character remains.
ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
           "0": "\0", chr(92): chr(92)}


class ExtractionFailed(RuntimeError):
    pass


def _literal(text: str) -> str:
    """The balanced `{...}` body that follows `USKeyboardLayout =`.

    ⛔ Counts braces instead of looking for the first `};`: the value
    contains strings with braces inside (`"key": "{"` really exists,
    it is BracketLeft with shift) and a naive search would cut the
    table in half with no error.
    """
    m = START.search(text)
    if not m:
        raise ExtractionFailed(
            "`USKeyboardLayout = {` does not appear in the bundle. If "
            "the bundler renamed the variable, the anchor should be "
            "changed here, not worked around.")
    i = m.end() - 1
    depth, j, in_str, quote, escape = 0, i, False, "", False
    while j < len(text):
        c = text[j]
        if in_str:
            if escape:
                escape = False
            elif c == chr(92):
                escape = True
            elif c == quote:
                in_str = False
        elif c in "\"'":
            in_str, quote = True, c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
        j += 1
    raise ExtractionFailed("unbalanced braces starting at USKeyboardLayout")


def _to_json(literal: str) -> str:
    """From JS literal to JSON, in a single pass that SCANS.

    Three things a regex cannot do well, and all three show up in the
    real bundle:

    1. ⛔ **Single quotes.** `"Quote": { "shiftKey": '"' }` is valid JS
       and JSON does not accept it. They must be rewritten as JSON
       strings, not substituted character by character: the content
       can contain a double quote, which is exactly this case.
    2. ⛔ **Comments.** Stripping them with `//[^\\n]*` also deletes a
       `//` INSIDE a string. It does not happen here, but the failure
       mode is silent - it shortens a value instead of raising an
       error - and it is not worth keeping.
    3. Trailing commas before a brace, which JS accepts and JSON does
       not.
    """
    out, i = [], 0
    while i < len(literal):
        c = literal[i]
        if c == "/" and literal[i + 1:i + 2] == "/":
            i = literal.find("\n", i)
            if i < 0:
                break
            continue
        if c in "\"'":
            quote, j, inside = c, i + 1, []
            while j < len(literal):
                d = literal[j]
                if d == chr(92):
                    # ⛔ It gets DECODED here instead of re-quoting the
                    # raw text. Re-quoting it would double an already
                    # escaped `\"`, and the character the bundle
                    # writes with a single quote is exactly the double
                    # quote.
                    seg = literal[j + 1:j + 2]
                    if seg == "u":
                        inside.append(chr(int(literal[j + 2:j + 6], 16)))
                        j += 6
                    else:
                        inside.append(ESCAPES.get(seg, seg))
                        j += 2
                    continue
                if d == quote:
                    break
                inside.append(d)
                j += 1
            out.append(json.dumps("".join(inside)))
            i = j + 1
            continue
        out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def extract(text: str) -> dict:
    data = json.loads(_to_json(_literal(text)))
    if not isinstance(data, dict) or not data:
        raise ExtractionFailed("the table is empty")
    # ⛔ The SANITY check is here and not in the caller: a table that
    # extracts but does not contain the keys every layout has is an
    # extraction that got lucky with the braces.
    missing = [k for k in ("KeyA", "Enter", "Backspace", "Digit0", "Space",
                           "ShiftLeft", "ArrowLeft", "Tab", "Escape")
               if k not in data]
    if missing:
        raise ExtractionFailed(
            "extracted but incomplete: missing %s. It is not the US "
            "layout." % ", ".join(missing))
    return data


def render(data: dict) -> str:
    body = json.dumps(data, indent=4, sort_keys=True, ensure_ascii=False)
    body = body.replace("true", "True").replace("false", "False") \
               .replace(": null", ": None")
    return (
        '"""The US keyboard layout, EXTRACTED from the driver bundle.\n'
        "\n"
        "GENERATED by `python scripts/gen_key_layout.py`. Do not\n"
        "hand-edit: the `--check` gate rejects a tree where this file\n"
        "and the bundle no longer agree, and a hand-fixed entry would\n"
        "be undone on the next regenerate.\n"
        "\n"
        "Each entry is indexed by `code` (the PHYSICAL key) and\n"
        "carries `keyCode`, the unshifted `key` and, where it exists,\n"
        "`shiftKey`. That is what `Page.dispatchKeyEvent` expects:\n"
        "four fields together, and a wrong one does not fail the\n"
        "action - it just lies in `event.keyCode`.\n"
        '"""\n'
        "from __future__ import annotations\n"
        "\n"
        "#: %d entries, indexed by `code`.\n" % len(data) +
        "LAYOUT = " + body + "\n"
        "\n"
        "#: unshifted `key` -> `code`. Used for `press(\"a\")` and for\n"
        "#: typing: a character is looked up here first, then among\n"
        "#: the shifted ones.\n"
        "BY_KEY = {v[\"key\"]: k for k, v in LAYOUT.items() if \"key\" in v}\n"
        "\n"
        "#: `shiftKey` -> `code`. `A`, `!`, `{` live here and NOT in\n"
        "#: BY_KEY.\n"
        "BY_SHIFTED_KEY = {v[\"shiftKey\"]: k for k, v in LAYOUT.items()\n"
        "                  if \"shiftKey\" in v}\n")


# ── the selftest ──────────────────────────────────────────────────────────
def selftest() -> int:
    good = ('var x = 1;\n'
            'USKeyboardLayout = {\n'
            '  // first line\n'
            '  "KeyA": { "keyCode": 65, "shiftKey": "A", "key": "a" },\n'
            '  "Digit0": { "keyCode": 48, "shiftKey": ")", "key": "0" },\n'
            '  "BracketLeft": { "keyCode": 219, "shiftKey": "{", "key": "[" },\n'
            '  "Enter": { "keyCode": 13, "key": "Enter", "text": "\\r" },\n'
            '  "Backspace": { "keyCode": 8, "key": "Backspace" },\n'
            '  "Space": { "keyCode": 32, "key": " " },\n'
            '  "ShiftLeft": { "keyCode": 16, "key": "Shift", "location": 1 },\n'
            '  "ArrowLeft": { "keyCode": 37, "key": "ArrowLeft" },\n'
            '  "Tab": { "keyCode": 9, "key": "Tab" },\n'
            '  "Escape": { "keyCode": 27, "key": "Escape" },\n'
            '};\nvar after = 2;\n')

    def try_case(name, text, should_raise=True):
        try:
            d = extract(text)
        except Exception as e:
            if should_raise:
                print("  killed: %s (%s)" % (name, str(e).splitlines()[0][:60]))
                return 0
            print("  FALSE POSITIVE: %s -> %s" % (name, e))
            return 1
        if should_raise:
            print("  SURVIVED: %s -> extracted %d entries" % (name, len(d)))
            return 1
        print("  silenced: %s (%d entries)" % (name, len(d)))
        return 0

    print("--- mutations that MUST trigger ---")
    bad = 0
    bad += try_case("the variable renamed by the bundler",
                    good.replace("USKeyboardLayout", "UsKbLayout"))
    bad += try_case("the table truncated: keys every layout has are missing",
                    'USKeyboardLayout = {\n  "KeyA": { "keyCode": 65, "key": "a" },\n};')
    bad += try_case("unbalanced braces",
                    good.replace('"Escape": { "keyCode": 27, "key": "Escape" },\n};',
                                  '"Escape": { "keyCode": 27, "key": "Escape" },\n'))
    bad += try_case("the empty table",
                    good[:good.index("{", good.index("USKeyboardLayout")) + 1] + "};")
    # ⛔ This is the mutation that justified counting braces: with a
    # search for the first `};` the table gets cut at BracketLeft,
    # which contains a brace INSIDE a string, and the extraction
    # half-succeeds.
    truncated = good.replace('"Enter": { "keyCode": 13, "key": "Enter", "text": "\\r" },\n', "")
    bad += try_case("Enter removed: incomplete but syntactically valid", truncated)
    bad += try_case("the literal replaced by an array",
                    good.replace("USKeyboardLayout = {", "USKeyboardLayout = ["))

    print("--- cases that must NOT trigger ---")
    bad += try_case("the good bundle", good, should_raise=False)
    bad += try_case("a brace inside a string does not close the table",
                    good.replace('"shiftKey": "{"', '"shiftKey": "}"'),
                    should_raise=False)
    print()
    print("selftest: %s" % ("ALL GOOD" if not bad else "%d PROBLEMS" % bad))
    return 1 if bad else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--check", action="store_true")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()
    if a.selftest:
        return selftest()
    if not BUNDLE.exists():
        print("the bundle is missing: %s" % BUNDLE)
        return 2
    try:
        data = extract(BUNDLE.read_text(encoding="utf-8", errors="replace"))
    except ExtractionFailed as failure:
        print("extraction failed: %s" % failure)
        return 2
    text = render(data)
    if a.check:
        current = OUTPUT.read_bytes().decode("utf-8") if OUTPUT.exists() else ""
        if current != text:
            print("keylayout.py does not match the bundle (%d entries "
                  "extracted). `python scripts/gen_key_layout.py`" % len(data))
            return 1
        print("keylayout.py matches: %d entries" % len(data))
        return 0
    # ⛔ `write_bytes`: `write_text` on Windows would translate every newline.
    OUTPUT.write_bytes(text.encode("utf-8"))
    print("wrote %s: %d entries" % (OUTPUT.name, len(data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

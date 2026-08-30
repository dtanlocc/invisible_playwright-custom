"""The keyboard: from a key name to the four fields Juggler demands.

⛔ THIS FILE EXISTS BECAUSE `Page.dispatchKeyEvent` DOES NOT FORGIVE A WRONG
FIELD SILENTLY - IT FORGIVES IT TOO MUCH. It wants `key`, `code`, `keyCode`
and `location` together, and if `code` is empty and `keyCode` is zero the
event still fires: the character shows up in the field, the action succeeds,
the tests pass, and the page reads `event.code === ""` on a key that on every
real Firefox has a physical name. It is a tell that lives in the fields
nobody looks at because the action worked.

The first draft of `_type` in `actions.py` sent exactly that:
`code: ""`, `keyCode: 0`, for every character.

**THREE DETAILS READ IN THE DRIVER'S CODE, not deduced** (`coreBundle.js`,
`RawKeyboardImpl3`), and each one changes the bytes that go out:

1. The `keyCode` field carries **`keyCodeWithoutLocation`**, not `keyCode`.
   They differ exactly on the keys that exist twice: `ShiftLeft` has
   `keyCode` 160 and `keyCodeWithoutLocation` 16, and 16 is what a real
   Firefox puts in the event.
2. For Enter, `text` must be set to an **empty string**, not to `"\\r"`:
   Gecko generates the character. Sending it explicitly inserts it twice.
3. `keyup` NEVER carries `text`. With `text` Juggler raises
   `keyup does not support text option` and typing dies halfway through.

**And the layout is not here**: it lives in `keylayout.py`, GENERATED from
the bundle by `scripts/gen_key_layout.py`. Here there is only how a name is
resolved, which is the algorithm of `buildLayoutClosure` read in the driver
and rewritten.
"""
from __future__ import annotations

from typing import Optional

from .keylayout import LAYOUT

#: The four that count as modifiers, in the driver's order.
MODIFIERS = ("Alt", "Control", "Meta", "Shift")

#: ⛔ Firefox's mask is NOT Gecko's and is NOT `1 << index`: read in
#: `toModifiersMask2` of the bundle. Juggler translates it itself into
#: `nsIDOMWindowUtils.MODIFIER_*`, so these are the numbers that belong here.
MODIFIER_MASK = {"Alt": 1, "Control": 2, "Shift": 4, "Meta": 8}

#: ⛔ And this is YET ANOTHER encoding, for the `buttons` field: read in
#: `toButtonsMask2`. **Right and middle are swapped** relative to the
#: button number (`button`: 0 left, 1 middle, 2 right). Writing
#: `1 << button` looks right, gives 1 for the left one - and gets the other
#: two wrong.
BUTTON_MASK = {0: 1, 1: 4, 2: 2}

#: The driver's aliases: a convenient name pointing at a physical key.
ALIASES = {"ShiftLeft": ["Shift"], "ControlLeft": ["Control"],
           "AltLeft": ["Alt"], "MetaLeft": ["Meta"], "Enter": ["\n", "\r"]}

#: ⛔ Three keys where Firefox disagrees with the generic layout. Read in
#: `kFirefoxKeyOverrides`: without this, `AudioVolumeMute` comes out with the
#: wrong `code`.
FIREFOX_OVERRIDES = {
    "AudioVolumeMute": {"code": "VolumeMute", "keyCodeWithoutLocation": 181},
    "AudioVolumeDown": {"code": "VolumeDown", "keyCodeWithoutLocation": 182},
    "AudioVolumeUp": {"code": "VolumeUp", "keyCodeWithoutLocation": 183},
}


class UnknownKey(ValueError):
    """The name is not in the layout. ⛔ It is REJECTED instead of inventing
    an empty event: a `keyCode: 0` does not fail, it lies."""


def _build_closure() -> dict:
    """The name -> description dict, in the same shape as the driver.

    A key is reachable by `code` (`KeyA`), by `key` if it is a single
    character (`a`), by its shifted form (`A`), and by aliases (`Shift`).
    ⛔ A key with `location` does NOT get entered by `key`: `NumpadEnter`
    must not respond to the name `Enter`, or `press("Enter")` would end up
    on the numpad.
    """
    out: dict = {}
    for code, d in LAYOUT.items():
        key = d.get("key") or ""
        descr = {
            "key": key,
            "keyCode": d.get("keyCode") or 0,
            "keyCodeWithoutLocation": d.get("keyCodeWithoutLocation")
                                      or d.get("keyCode") or 0,
            "code": code,
            "text": d.get("text") or "",
            "location": d.get("location") or 0,
        }
        if len(key) == 1:
            descr["text"] = key
        shifted = None
        if d.get("shiftKey"):
            shifted = dict(descr)
            shifted["key"] = d["shiftKey"]
            shifted["text"] = d["shiftKey"]
            if d.get("shiftKeyCode"):
                shifted["keyCode"] = d["shiftKeyCode"]
        out[code] = dict(descr, shifted=shifted)
        for alias in ALIASES.get(code, []):
            out[alias] = descr
        if d.get("location"):
            continue
        if len(descr["key"]) == 1:
            out.setdefault(descr["key"], descr)
        if shifted:
            out.setdefault(shifted["key"], dict(shifted, shifted=None))
    return out


LAYOUT_CLOSURE = _build_closure()


class Keyboard:
    """The state of modifiers and pressed keys, plus the four verbs.

    STATE is the reason this is a class and not three functions:
    `press("Shift+a")` must send `A` and not `a`, and to know that it must
    remember that Shift is down between Shift's keydown and `a`'s.
    """

    def __init__(self, connection, session: str):
        self.c = connection
        self.session = session
        self.modifiers: set = set()
        self.pressed: set = set()

    # ── the resolution ──────────────────────────────────────────────────────
    def describe(self, key: str) -> dict:
        name = "Control" if key == "ControlOrMeta" else key
        d = LAYOUT_CLOSURE.get(name)
        if d is None:
            raise UnknownKey(
                "unknown key: %r. Valid names are the layout's `code` "
                "values (KeyA, Digit1, Enter), a single character, or an "
                "alias (Shift, Control, Alt, Meta)." % key)
        if "Shift" in self.modifiers and d.get("shifted"):
            d = d["shifted"]
        d = dict(d)
        # ⛔ With a modifier other than Shift held down, `text` does NOT
        # come out: `Control+a` does not write an "a" into the field. Read
        # in the driver, and without this line a `press("Control+a")` would
        # insert the character.
        if len(self.modifiers) > 1 or \
                (len(self.modifiers) == 1 and "Shift" not in self.modifiers):
            d["text"] = ""
        d.update(FIREFOX_OVERRIDES.get(d["key"], {}))
        return d

    def modifier_mask(self) -> int:
        m = 0
        for name in self.modifiers:
            m |= MODIFIER_MASK.get(name, 0)
        return m

    # ── the verbs ────────────────────────────────────────────────────────────
    def down(self, key: str) -> None:
        d = self.describe(key)
        repeat = d["code"] in self.pressed
        self.pressed.add(d["code"])
        if d["key"] in MODIFIERS:
            self.modifiers.add(d["key"])
        text = d["text"]
        # ⛔ Enter: Gecko generates the text. Sending it explicitly inserts
        # it twice. Read in `RawKeyboardImpl3.keydown`.
        if text == "\r":
            text = ""
        self.c.send("Page.dispatchKeyEvent",
                     {"type": "keydown", "key": d["key"], "code": d["code"],
                      "keyCode": d["keyCodeWithoutLocation"],
                      "location": d["location"], "repeat": repeat,
                      "text": text},
                     session=self.session, timeout=10)

    def up(self, key: str) -> None:
        d = self.describe(key)
        if d["key"] in MODIFIERS:
            self.modifiers.discard(d["key"])
        self.pressed.discard(d["code"])
        # ⛔ NO `text` here: Juggler raises `keyup does not support text
        # option` and typing dies halfway through.
        self.c.send("Page.dispatchKeyEvent",
                     {"type": "keyup", "key": d["key"], "code": d["code"],
                      "keyCode": d["keyCodeWithoutLocation"],
                      "location": d["location"], "repeat": False},
                     session=self.session, timeout=10)

    def press(self, key: str) -> None:
        """`press("a")`, `press("Enter")`, `press("Control+Shift+KeyA")`.

        The modifiers are held down for the whole final key and released
        in reverse order, the way a hand would.
        """
        pieces = key.split("+")
        final, held = pieces[-1], pieces[:-1]
        # ⛔ A trailing `+` is the plus key, not a separator: `press("+")`
        # must work. `"+".split("+")` gives `["", ""]`, so the empty piece
        # has to be put back in place instead of raising
        # "unknown key: ''".
        if final == "" and held:
            final, held = "+", held[:-1]
        for m in held:
            self.down(m)
        try:
            self.down(final)
            self.up(final)
        finally:
            for m in reversed(held):
                self.up(m)

    def type(self, text: str, *, delay: float = 0.0) -> None:
        """One key per character, the way a hand would.

        ⛔ This is NOT `insert_text`: a character the layout does not know
        (an ideogram, an emoji) has no key, so here it is REJECTED and
        deferred to `insert_text`. Typing something with no key would mean
        sending `code: ""`, which is exactly the defect this file exists
        to not have.
        """
        import time as _t
        for ch in text:
            if ch not in LAYOUT_CLOSURE:
                raise UnknownKey(
                    "%r has no key on the US layout: use `insert_text`, "
                    "which goes through `Page.insertText` and does not "
                    "fake a keypress." % ch)
            self.press(ch)
            if delay:
                _t.sleep(delay)

    def insert_text(self, text: str) -> None:
        """The text goes in without key events. This is what is needed for
        a character that is not on the layout."""
        self.c.send("Page.insertText", {"text": text},
                     session=self.session, timeout=10)

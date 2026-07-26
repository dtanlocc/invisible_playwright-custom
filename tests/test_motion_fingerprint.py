"""The paths themselves must not move, ever, without somebody deciding they should.

Seed-reproducibility is a documented property callers rely on
(``InvisiblePlaywright(seed=42)``), and it is not something the statistical
tests next door can see: they check distributions, and a refactor that shifts
every coordinate by a bit-width leaves every distribution intact.

This is a fingerprint of 576 cases - twelve seeds crossed with eight geometries,
both jitter settings and three target widths - covering 16135 waypoints. It is
NOT a style check. It exists because extracting the planner into stages looked
completely safe and changed the output twice:

  * `axis.at(dist * u, ...)` computes `ux * (dist * u)` where the original wrote
    `ux * dist * u`, i.e. `(ux * dist) * u`. Float multiplication is not
    associative, so those differ in the last bit - enough to change a rounded
    pixel and, through it, every draw downstream of it;
  * returning `amp * w` from the overshoot and multiplying by the unit vector at
    the call site regrouped the same product the same way.

Neither was visible in any other test. If this one goes red, the question is not
"which assertion do I update" - it is "did I mean to change every path of every
session", and the answer is almost always no.
"""
from __future__ import annotations

import hashlib
import json
import random

import pytest

from invisible_playwright import _motion

pytestmark = pytest.mark.unit

CASES = [(0, 0, 50, 20), (0, 0, 600, 400), (100, 100, 105, 102), (0, 0, 3, 1),
         (800, 600, 20, 40), (0, 0, 1200, 20), (500, 500, 500, 500), (0, 0, 0, 900)]

#: sha256 of the recorded output. Regenerate ONLY with a deliberate decision.
FINGERPRINT = "d231f767506932106bbd1da977e3cdb8408e04a748c1cb177d8686732cd215d6"


def _fingerprint() -> tuple[str, int, int]:
    out = []
    for seed in range(12):
        st = _motion.style_for_seed(seed)
        for (ax, ay, bx, by) in CASES:
            for jitter in (True, False):
                for tw in (None, 20.0, 220.0):
                    rng = random.Random(seed * 7919 + 13)
                    wps = _motion._plan(rng, ax, ay, bx, by, st,
                                        with_jitter=jitter, target_w=tw)
                    out.append([seed, ax, ay, bx, by, jitter, tw,
                                [[round(w.x, 10), round(w.y, 10),
                                  round(w.dt_ms, 10), round(w.t_ms, 10)]
                                 for w in wps]])
    blob = json.dumps(out, sort_keys=True)
    return (hashlib.sha256(blob.encode()).hexdigest(), len(out),
            sum(len(r[7]) for r in out))


def test_the_planned_paths_are_byte_identical_to_the_recorded_ones():
    digest, cases, points = _fingerprint()
    assert (cases, points) == (576, 16135), (
        f"the case grid itself changed: {cases} cases / {points} waypoints")
    assert digest == FINGERPRINT, (
        "every planned path moved. If that was deliberate, re-record the "
        "fingerprint IN THE SAME COMMIT as the change that caused it and say "
        "which change; if it was not, something regrouped an arithmetic "
        "expression or reordered a draw from the rng."
    )


def test_the_fingerprint_is_actually_sensitive():
    """A fingerprint that would survive a real change is decoration.

    Perturbs one style field by one part in ten thousand and requires the
    digest to move. Without this the test above could be passing because the
    grid collapsed to nothing.
    """
    original = _motion.style_for_seed

    def nudged(seed):
        st = original(seed)
        return st.__class__(**{**st.__dict__,
                               "bow_frac": st.bow_frac * 1.0001})

    _motion.style_for_seed = nudged
    try:
        digest, _, _ = _fingerprint()
    finally:
        _motion.style_for_seed = original
    assert digest != FINGERPRINT, (
        "a 0.01% change to the bow fraction left the fingerprint identical - "
        "it is not measuring the paths")

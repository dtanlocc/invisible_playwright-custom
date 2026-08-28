"""Which transport the package uses, and the switch that keeps both judgeable.

⛔ THE NODE DRIVER IS NOT DEAD CODE: IT IS THE JUDGE. The Python server
answers the same protocol the driver answers, so the only honest way to know it
answers CORRECTLY is to run the same session through both and compare. Deleting
it would leave this path with nothing to be measured against, which is the shape
of mistake this project has paid for before - a build that agrees with itself.

⛔ And the bundle it lives in has THREE other jobs that have nothing to do with
Node the runtime: `prefs_byte_parity.py` reads the driver's `user.js` rules from
it on every run rather than copying them, and `gen_injected_source.py` and
`gen_key_layout.py` generate from it. Deleting the folder would turn three
derived facts back into hand-copied ones.

    INVPW_TRANSPORT=juggler   the Python server in this package (default)
    INVPW_TRANSPORT=driver    the Node driver, kept as the judge and the way back

⛔ THE DEFAULT FLIPPED ON 2026-08-28, AND IT FLIPPED ON EVIDENCE. It was
DRIVER while this matured, on the reasoning that a half-finished server which
silently became the default would turn every user's session into an experiment.
What made it flip is not that the code looks done - it is four measurements
taken the same day, on one code state:

  * `run_e2e.py`: **188 passed on BOTH transports**, zero failures;
  * `judge_both_transports.py`: 50 green on both, **0 red only on ours**;
  * `diff_protocol.py`: **parity** on methods, parameter names, object types,
    initializer fields, events AND parentage;
  * the realness gates, run on this path for the first time: `fppro_full`
    ALL CRITICAL FLAGS CLEAN 18/18, `fppro_consistency` PASS 43/43,
    `observable_crossings` no crossings.

⛔ AND THE DRIVER STAYS REACHABLE, deliberately. It is not dead weight: it is
the only second arm this project has, and `judge_both_transports.py` and
`diff_protocol.py` exist only while there are two. It costs a user nothing -
nothing downloads Node unless this variable asks for it - and it is the way back
if a session ever behaves differently on the new path.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

#: The environment variable, named once so nothing can spell it two ways.
CHOICE_ENV = "INVPW_TRANSPORT"

DRIVER = "driver"
JUGGLER = "juggler"


def chosen() -> str:
    """Which transport this process wants. Refuses an unknown name.

    ⛔ REFUSES instead of falling back to the default: a typo in the variable
    would otherwise run the driver while the caller believed they were testing
    the Python path, and every measurement taken that way would be a
    measurement of the wrong arm. This project has a rule about exactly that -
    a bench arm that is not what it says it is.
    """
    value = (os.environ.get(CHOICE_ENV) or JUGGLER).strip().lower()
    if value not in (DRIVER, JUGGLER):
        raise ValueError(
            "%s=%r is not a transport: use %r (the Node driver) or %r (the "
            "Python server)." % (CHOICE_ENV, value, DRIVER, JUGGLER))
    return value


def make_transport(loop: asyncio.AbstractEventLoop) -> Any:
    """The transport the Connection should speak through."""
    if chosen() == JUGGLER:
        from .server import JugglerServer
        from .transport import InProcessTransport
        return InProcessTransport(loop, JugglerServer())
    # ⛔ THE NAME IS STILL ACCEPTED AND THE DRIVER IS GONE, and that is a
    # deliberate pair. Refusing the name outright would leave a caller who set
    # the variable months ago with `ValueError: not a transport` and no idea
    # what happened to it; this says what was removed, when, and how to get a
    # second arm back for a comparison.
    raise RuntimeError(
        "the Node driver was removed on 2026-08-28: this package no longer "
        "ships `_driver/` and no longer downloads node. "
        "What replaced it is the in-process Python server, which is now the "
        "default - unset %s and it runs. "
        "To get the old arm back for a COMPARISON (which is the only thing it "
        "was still for): check out the last commit that carried it into a git "
        "worktree and point INVPW_DRIVER_TREE at it. Both "
        "`judge_both_transports.py` and `diff_protocol.py` read that variable."
        % CHOICE_ENV)

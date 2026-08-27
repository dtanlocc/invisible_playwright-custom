"""Which transport the package uses, and the switch that keeps both judgeable.

⛔ THE NODE DRIVER IS NOT DEAD CODE WHILE THIS IS BEING BUILT: IT IS THE JUDGE.
The Python server answers the same protocol the driver answers, so the only
honest way to know it answers CORRECTLY is to run the same session through both
and compare. Deleting the driver first would leave the new path with nothing to
be measured against, which is the shape of mistake this project has paid for
before - a build that agrees with itself.

    INVPW_TRANSPORT=driver    the Node driver (default while this matures)
    INVPW_TRANSPORT=juggler   the Python server in this package

⛔ The default is DRIVER on purpose. A half-finished server that silently became
the default would turn every user's session into an experiment, and the failures
would arrive as "invisible_playwright broke" rather than as a gate going red
here. It flips when the judgement says it can, not when the code looks done.
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
    value = (os.environ.get(CHOICE_ENV) or DRIVER).strip().lower()
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
    from invisible_playwright._pw._impl._transport import PipeTransport
    return PipeTransport(loop)

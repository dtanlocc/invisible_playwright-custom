# Copyright (c) Microsoft Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""⛔ FUSED, 2026-08-29: no `__create__`, no guid, no channel.

Until this date `Dialog` was a `ChannelOwner`, built by `_object_factory.py`
from a `{parent, type, guid, initializer}` the server announced over the
wire, and `accept`/`dismiss` sent a message back the same way. That round
trip earned its keep when the other end was a real process; it no longer
does when the other end is `_juggler`, in the same process.

⛔ IT IS STILL A PLAIN CLASS AND NOT A `ChannelOwner` on purpose, not by
omission: nothing in this codebase ever passes a `Dialog` back INTO a Juggler
call as a parameter (checked against the 2026-08-29 channel-call inventory of
all 351 sites in `_impl`), and `ImplToApiMapping.from_maybe_impl` wraps by
Python TYPE, not by `ChannelOwner`-ness - `mapping.register(Dialog,
sync_api.Dialog)` keeps working unchanged as long as this stays importable
from here under the same name.

⛔ AND THE TWO WAYS THIS GETS CONSTRUCTED ARE NOT SYMMETRIC ANY MORE.
`_juggler/server.py`'s `PageDispatcher._emit_fused_dialog` builds one on the
connection's read-loop thread - never via `_object_factory.py`, whose `if
type == "Dialog":` branch is dead code kept only because deleting it would
make this file's constructor signature and that branch silently disagree if
anything ever revived it.

⛔ AND DELIVERING IT IS TWO HOPS, NOT ONE, found by an actual dialog hanging
with no exception. `Server.call_soon` gets to the asyncio loop thread from
the read loop; once there, `Server.deliver` (not a bare call) runs
`BrowserContext._on_dialog` under `Connection.deliver_event`'s rules - which
wraps it in its own `EventGreenlet` under the sync facade, exactly as
`dispatch` wraps every wire event. Skipping that second hop is invisible
right up until a handler calls an async method (`dialog.accept()`): it
suspends into a fiber with nobody on the other end of the switch.

`accept`/`dismiss` cross back into `_juggler` through
`PageDispatcher.send_async`, which runs the call on the SAME worker pool
every other Juggler operation blocks on, and translates a `_juggler`-side
exception into this fork's own exception classes before it reaches
`is_target_closed_error` below - skipping that translation would silently
un-fix the exact regression closed in `Page.close()` earlier the same day.
"""
from typing import TYPE_CHECKING, Optional

from invisible_playwright._pw._impl._errors import is_target_closed_error

if TYPE_CHECKING:  # pragma: no cover
    from invisible_playwright._pw._impl._page import Page
    from invisible_playwright._juggler.server import PageDispatcher


class Dialog:
    def __init__(self, page_dispatcher: "PageDispatcher", page: "Page",
                dialog_id: str, kind: str, message: str,
                default_value: str) -> None:
        self._page_dispatcher = page_dispatcher
        #: ⛔ RESOLVED ONCE, AT CONSTRUCTION, not looked up again on every
        #: `.page` access. The caller (`_emit_fused_dialog`) already has it in
        #: hand - it is how it found where to deliver this dialog in the
        #: first place - so asking the twin registry a second time would be
        #: the reach-through chain this refactor spent the day removing,
        #: reintroduced in the one file it just added.
        self._page = page
        #: ⛔ NOT OPTIONAL, AND NOT OBVIOUS FROM THE PUBLIC API THIS CLASS
        #: OFFERS: `SyncBase.__init__`/`AsyncBase.__init__` - the generated
        #: `sync_api`/`async_api` wrapper this object is handed to on its way
        #: to a listener - read `impl_obj._loop` unconditionally, and the sync
        #: side also reads `impl_obj._dispatcher_fiber` to know which greenlet
        #: to switch back to. A `ChannelOwner` gets both from its PARENT
        #: (`self._loop = parent._loop`, in `_connection.py`); Dialog's old
        #: parent was always its Page, so copying them from the same `page`
        #: reproduces exactly the value a `ChannelOwner`-based Dialog would
        #: have had. Missing this is not a slow failure: the very first
        #: `page.on("dialog", ...)` callback raises `AttributeError` while
        #: wrapping the object, before user code ever runs - found by an
        #: actual dialog, not by the unit suite, which stubs this path out
        #: entirely.
        self._loop = page._loop
        self._dispatcher_fiber = page._dispatcher_fiber
        self._dialog_id = dialog_id
        self._type = kind
        self._message = message
        self._default_value = default_value or ""

    def __repr__(self) -> str:
        return (f"<Dialog type={self.type} message={self.message} "
                f"default_value={self.default_value}>")

    @property
    def type(self) -> str:
        return self._type

    @property
    def message(self) -> str:
        return self._message

    @property
    def default_value(self) -> str:
        return self._default_value

    @property
    def page(self) -> Optional["Page"]:
        return self._page

    async def accept(self, promptText: str = None) -> None:
        params = {"dialogId": self._dialog_id, "accept": True}
        if promptText is not None:
            params["promptText"] = promptText
        await self._page_dispatcher.send_async("Page.handleDialog", params)

    async def dismiss(self) -> None:
        try:
            await self._page_dispatcher.send_async(
                "Page.handleDialog",
                {"dialogId": self._dialog_id, "accept": False})
        except Exception as e:
            if is_target_closed_error(e):
                return
            raise

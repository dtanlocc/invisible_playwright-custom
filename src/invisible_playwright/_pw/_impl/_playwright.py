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

from typing import Dict

from invisible_playwright._pw._impl._browser_type import BrowserType
from invisible_playwright._pw._impl._connection import ChannelOwner, from_channel
from invisible_playwright._pw._impl._fetch import APIRequest
from invisible_playwright._pw._impl._selectors import Selectors


class Playwright(ChannelOwner):
    devices: Dict
    selectors: Selectors
    firefox: BrowserType
    request: APIRequest

    def __init__(
        self, parent: ChannelOwner, type: str, guid: str, initializer: Dict
    ) -> None:
        super().__init__(parent, type, guid, initializer)
        self.request = APIRequest(self)
        self.firefox = from_channel(initializer["firefox"])
        self.firefox._playwright = self

        self.selectors = Selectors(self._loop, self._dispatcher_fiber)

        self.devices = self._connection.local_utils.devices

    def __getitem__(self, value: str) -> "BrowserType":
        if value == "firefox":
            return self.firefox
        # MODIFICATO da invisible_playwright: chromium e webkit non esistono
        # piu' in questo fork - i loro moduli sono stati tolti dal driver
        # vendorizzato. Il messaggio lo dice, invece di lasciare un
        # AttributeError su un campo che nessuno ha piu' impostato.
        if value in ("chromium", "webkit"):
            raise ValueError(
                "invisible_playwright pilota SOLO Firefox: il supporto a "
                "%s e' stato rimosso dal driver, non e' disabilitato." % value)
        raise ValueError("Invalid browser " + value)

    def _set_selectors(self, selectors: Selectors) -> None:
        self.selectors = selectors

    async def stop(self) -> None:
        pass

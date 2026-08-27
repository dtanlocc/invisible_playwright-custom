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

#
# ---------------------------------------------------------------------------
# MODIFIED by invisible_playwright relative to the original Playwright
# 1.61.0. Apache-2.0 requires that changes be declared: this is the
# declaration.
#
# The original forwarded `sys.argv[1:]` to the vendored `cli.js` WITHOUT
# filtering it, that is it exposed the entire Playwright CLI - `codegen`, `open`,
# `install`, the dashboard - from a package that in its own documents declares
# that it is not a dev-tool ("Is there an MCP server for this project? No, and
# there does not need to be").
#
# It is not just extra surface: `open`/`codegen` reach `open4()`, which
# calls `_exposeConsoleApi()` UNCONDITIONALLY, and that puts
# `window.playwright` - enumerable - on the page. It is exactly the tell that
# the fork disables elsewhere by hardwiring `debugMode()` to "" (see `packages/utils/
# debug.ts` in the bundle), a defense that this service door bypassed.
#
# Only `show-trace` remains allowed, the only subcommand that the package's
# documents actually teach (record-playwright-trace-debug-scraper.md).

import subprocess
import sys

from invisible_playwright._pw._impl._driver import compute_driver_executable, get_driver_env

#: Il solo sottocomando del driver Node che questo pacchetto espone. Aggiungerne
#: uno significa riaprire una superficie che il prodotto dichiara di non avere:
#: si fa solo se un documento pubblico lo insegna.
_ALLOWED = ("show-trace",)


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] not in _ALLOWED:
        chiesto = argv[0] if argv else "(nessun comando)"
        print(
            f"invisible-playwright: '{chiesto}' non e' disponibile.\n"
            f"Questo pacchetto serve a PILOTARE un browser, non a svilupparci "
            f"sopra: della CLI del driver espone solo {', '.join(_ALLOWED)}.\n"
            f"Per automatizzare, usa l'API Python "
            f"(`from invisible_playwright import InvisiblePlaywright`).",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        driver_executable, driver_cli = compute_driver_executable()
        completed_process = subprocess.run(
            [driver_executable, driver_cli, *argv], env=get_driver_env()
        )
        sys.exit(completed_process.returncode)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()

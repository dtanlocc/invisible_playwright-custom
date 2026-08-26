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
# MODIFICATO da invisible_playwright rispetto all'originale di Playwright
# 1.61.0. Apache-2.0 chiede che le modifiche siano dichiarate: questa e' la
# dichiarazione.
#
# L'originale inoltrava `sys.argv[1:]` al `cli.js` vendorizzato SENZA
# filtrarlo, cioe' esponeva l'intera CLI di Playwright - `codegen`, `open`,
# `install`, la dashboard - da un pacchetto che nei propri documenti dichiara
# di non essere un dev-tool ("Is there an MCP server for this project? No, and
# there does not need to be").
#
# Non e' solo superficie in piu': `open`/`codegen` arrivano a `open4()`, che
# chiama `_exposeConsoleApi()` in modo INCONDIZIONATO, e quello mette
# `window.playwright` - enumerabile - sulla pagina. E' esattamente il tell che
# il fork spegne altrove cablando `debugMode()` a "" (vedi `packages/utils/
# debug.ts` nel bundle), difesa che questa porta di servizio scavalcava.
#
# Resta permesso solo `show-trace`, l'unico sottocomando che i documenti del
# pacchetto insegnano davvero (record-playwright-trace-debug-scraper.md).

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

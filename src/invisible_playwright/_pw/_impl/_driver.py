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
# MODIFIED by invisible_playwright compared to the original Playwright
# 1.61.0. Apache-2.0 requires that changes be declared: this is the
# declaration.
#
# This line used to say "the only file in the vendored client where
# BEHAVIOR was changed". That is no longer true since 2026-08-24, and a count
# written by hand in a file that nobody rereads goes stale in days: the client
# files with changed behavior are found by searching for the marker
# `MODIFIED by invisible_playwright` inside `_pw/`, which is the real list.
#
# What changes, and why:
#
#   1. The ``cli.js`` is ours, in ``invisible_playwright/_driver/``, not
#      the one inside ``site-packages/playwright/``. This is why the fork
#      exists: the serializer that Playwright injects into the page queries
#      the constructors of the SITE - sixteen reads handed to the page were
#      measured for each object returned by an evaluate call - and no option
#      turns them off. To change them you have to own the file.
#
#   2. The ``node`` comes from ``invisible_playwright._node``, which downloads it on
#      first use and verifies its checksum, instead of being a 92.3 MB
#      binary inside our distribution.
#
# The original computed both from ``inspect.getfile(playwright)``, which after
# vendoring would point to ``_pw/driver/``: a folder that does not exist.
# ---------------------------------------------------------------------------

import os
import sys
from pathlib import Path
from typing import Tuple

from invisible_playwright._pw._repo_version import version


def driver_root() -> Path:
    """La cartella del driver biforcato, accanto al pacchetto che lo usa.

    ``__file__`` sta in ``invisible_playwright/_pw/_impl/``: due livelli sopra
    c'e' ``invisible_playwright/``, e li' dentro ``_driver/``.
    """
    return Path(__file__).resolve().parents[2] / "_driver"


def compute_driver_executable() -> Tuple[str, str]:
    cli = driver_root() / "package" / "cli.js"
    if not cli.is_file():
        raise RuntimeError(
            "il driver biforcato non e' al suo posto: %s non esiste. Se stai "
            "lavorando da un checkout, _driver/ non e' stato copiato; se e' "
            "un'installazione, il wheel e' incompleto." % cli)
    from invisible_playwright._node import node_path
    return (node_path(), str(cli))


#: Variabili che l'ambiente di CHI CI USA non deve poter passare al driver Node.
#: Non sono nostre e non le imposta questo pacchetto: arrivano dalla shell di un
#: utente che le ha messe per un altro progetto, e cambiano cosa fa il driver.
#:
#: - ``DEBUG``/``DEBUG_FILE``: il pacchetto ``debug`` di Node e' una convenzione
#:   di mezzo ecosistema, non solo di Playwright. Un ``DEBUG=*`` (o ``pw:*``)
#:   lasciato nella shell fa scrivere al driver l'INTERO traffico di protocollo
#:   su stderr, e ``DEBUG_FILE`` lo specchia su un percorso che decide
#:   l'ambiente. Vive in ``utilsBundle.js``, un modulo DIVERSO da quello dove il
#:   fork ha gia' cablato ``debugMode()`` a "": quella patch non lo copriva.
#: - ``NODE_OPTIONS``: la consuma ``node`` stesso PRIMA che una riga del bundle
#:   giri, quindi non e' neutralizzabile lato JS. ``--require`` o ``--inspect``
#:   nella shell si applicherebbero in silenzio al nostro driver.
#: - ``PWDEBUG``/``PWDEBUGIMPL``/``PWTEST_UNDER_TEST``: le prime due sono gia'
#:   spente nel bundle, ma toglierle qui costa zero ed e' la stessa difesa in
#:   un punto che non dipende dal fatto che il bundle resti patchato.
#:
#: NON contiene ``PLAYWRIGHT_NODEJS_PATH``: quella e' onorata di proposito
#: (``_node.py``), ed e' una scelta dichiarata, non una svista.
_ENV_DA_NON_EREDITARE = (
    "DEBUG",
    "DEBUG_FILE",
    "NODE_OPTIONS",
    "PWDEBUG",
    "PWDEBUGIMPL",
    "PWTEST_UNDER_TEST",
)


#: La via d'uscita dichiarata. Serve a NOI: il traffico di protocollo si legge
#: con ``DEBUG=pw:protocol``, ed e' come e' stato misurato che un `goto()` costa
#: 16 messaggi. Chiudere la porta accidentale senza lasciarne una deliberata
#: avrebbe tolto uno strumento di misura invece che una fuga.
_ENV_SBLOCCO = "INVPW_ALLOW_DRIVER_DEBUG"


def get_driver_env() -> dict:
    env = os.environ.copy()
    if env.get(_ENV_SBLOCCO) != "1":
        for _nome in _ENV_DA_NON_EREDITARE:
            env.pop(_nome, None)
    env["PW_LANG_NAME"] = "python"
    env["PW_LANG_NAME_VERSION"] = f"{sys.version_info.major}.{sys.version_info.minor}"
    env["PW_CLI_DISPLAY_VERSION"] = version
    return env

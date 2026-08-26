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
# Questa riga diceva "l'unico file del client vendorizzato in cui e' stato
# cambiato del COMPORTAMENTO". Non e' piu' vero dal 2026-08-24, e un conteggio
# scritto a mano in un file che nessuno rilegge invecchia in giorni: i file del
# client con comportamento cambiato si trovano cercando il marcatore
# `MODIFICATO da invisible_playwright` dentro `_pw/`, che e' l'elenco vero.
#
# Cosa cambia, e perche':
#
#   1. Il ``cli.js`` e' quello nostro, in ``invisible_playwright/_driver/``, non
#      quello dentro ``site-packages/playwright/``. E' il motivo per cui il fork
#      esiste: il serializzatore che Playwright inietta nella pagina interroga i
#      costruttori DEL SITO - misurate sedici letture regalate alla pagina per
#      ogni oggetto restituito da una evaluate - e nessuna opzione le spegne.
#      Per cambiarle bisogna possedere il file.
#
#   2. Il ``node`` arriva da ``invisible_playwright._node``, che lo scarica al
#      primo uso e ne verifica il checksum, invece di essere un binario da
#      92,3 MB dentro la nostra distribuzione.
#
# L'originale calcolava entrambi da ``inspect.getfile(playwright)``, che dopo la
# vendorizzazione punterebbe a ``_pw/driver/``: una cartella che non esiste.
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

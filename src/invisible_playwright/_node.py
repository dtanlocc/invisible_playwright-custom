"""Procura il Node che esegue il driver biforcato.

PERCHE' NON LO SPEDIAMO. Il driver Playwright pesa 105 MB, di cui 92,3 sono
``node.exe``. Committarlo vorrebbe dire un binario da 92 MB nella storia di git
per sempre, contro un limite GitHub di 100 MB per file, moltiplicato per quattro
piattaforme. Quindi il codice lo versioniamo (``_pw/`` e ``_driver/``, 9 MB in
tutto) e il runtime lo scarichiamo al primo uso, come fa Playwright stesso con i
browser.

UNA FONTE SOLA. Il download, il checksum e la cartella di cache sono quelli di
``invisible_core.download``: sono gia' scritti, gia' provati, e averne un
secondo esemplare qui sarebbe lo stesso fatto in due posti. Sono nomi privati
di un pacchetto che scriviamo noi e che questo wrapper pinna a una versione
ESATTA (il numero sta nel ``pyproject.toml`` e in nessun altro posto: scriverlo
due volte e' la deriva che ``tests/test_core_pin.py`` esiste per impedire, e
questo modulo l'ha violata al primo tentativo). E' quel pin a rendere lecito
appoggiarsi a nomi privati, ed e' stato verificato che esistano nel wheel
PUBBLICATO e non solo nell'albero di lavoro: un consumatore puo' usare solo
cio' che l'indice ha.

⛔ NIENTE RIPIEGO SUL NODE DI QUALCUN ALTRO. La tentazione e' riusare il
``node.exe`` del pacchetto ``playwright``, se per caso e' installato: gratis, e
gia' su disco. E' esattamente il ripiego verso la macchina che la regola 7
vieta, in piccolo: due utenti finirebbero per eseguire due Node diversi a
seconda di cosa hanno installato per altri motivi, e nessun gate se ne
accorgerebbe. Una versione dichiarata, uguale per tutti.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

#: La versione che Playwright 1.61.0 imbarca nel suo driver. Il driver e' un
#: programma Node come un altro: gira su qualunque runtime abbastanza recente,
#: ma dichiararne UNA e' cio' che rende la stessa sessione la stessa sessione su
#: due macchine diverse.
NODE_VERSION = "v24.17.0"

BASE = "https://nodejs.org/dist/" + NODE_VERSION


class NodeError(RuntimeError):
    """Node non e' disponibile e non si e' potuto procurarlo."""


def _bersaglio() -> tuple[str, str, str]:
    """(nome archivio, percorso del binario dentro l'archivio, nome del file)."""
    macchina = platform.machine().lower()
    arm = macchina in ("arm64", "aarch64")
    if sys.platform == "win32":
        arco = "win-arm64" if arm else "win-x64"
        return ("node-%s-%s.zip" % (NODE_VERSION, arco),
                "node-%s-%s/node.exe" % (NODE_VERSION, arco), "node.exe")
    if sys.platform == "darwin":
        arco = "darwin-arm64" if arm else "darwin-x64"
        return ("node-%s-%s.tar.gz" % (NODE_VERSION, arco),
                "node-%s-%s/bin/node" % (NODE_VERSION, arco), "node")
    arco = "linux-arm64" if arm else "linux-x64"
    return ("node-%s-%s.tar.xz" % (NODE_VERSION, arco),
            "node-%s-%s/bin/node" % (NODE_VERSION, arco), "node")


def cartella() -> Path:
    """Dove finisce il Node scaricato. Sotto la stessa radice del motore."""
    from invisible_core.download import cache_root
    return cache_root() / "node" / NODE_VERSION


def _estrai(archivio: Path, interno: str, dest: Path) -> None:
    """Tira fuori UN file dall'archivio. Non srotola l'intero pacchetto Node.

    Sono 50 MB di headers, npm e documentazione che non eseguiamo mai; a noi
    serve un eseguibile solo.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if archivio.suffix == ".zip":
        with zipfile.ZipFile(archivio) as z, open(dest, "wb") as out:
            with z.open(interno) as src:
                shutil.copyfileobj(src, out)
    else:
        with tarfile.open(archivio) as t:
            src = t.extractfile(interno)
            if src is None:
                raise NodeError("%s non contiene %s" % (archivio.name, interno))
            with open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    if sys.platform != "win32":
        dest.chmod(0o755)


def _scarica(progress=None) -> Path:
    from invisible_core.download import (_download_file, _parse_checksums,
                                         _sha256_file)

    nome_archivio, interno, nome_bin = _bersaglio()
    dst = cartella() / nome_bin
    d = cartella()
    d.mkdir(parents=True, exist_ok=True)

    # I checksum PRIMA dell'archivio: se la lista non si scarica, non si scarica
    # nemmeno un archivio che poi non si potrebbe verificare. Un download non
    # verificato non e' un download riuscito a meta', e' un rischio in piu'.
    somme = d / "SHASUMS256.txt"
    _download_file(BASE + "/SHASUMS256.txt", somme)
    attesi = _parse_checksums(somme.read_text(encoding="utf-8", errors="replace"))
    atteso = attesi.get(nome_archivio)
    if not atteso:
        raise NodeError(
            "SHASUMS256.txt di %s non elenca %s. O la versione dichiarata non "
            "esiste piu' su nodejs.org, o questa piattaforma non ha una build "
            "ufficiale." % (NODE_VERSION, nome_archivio))

    archivio = d / nome_archivio
    _download_file(BASE + "/" + nome_archivio, archivio, progress=progress)
    avuto = _sha256_file(archivio)
    if avuto.lower() != atteso.lower():
        archivio.unlink(missing_ok=True)
        somme.unlink(missing_ok=True)
        raise NodeError(
            "il checksum di %s non torna: atteso %s, ottenuto %s. L'archivio e' "
            "stato buttato." % (nome_archivio, atteso[:16], avuto[:16]))

    try:
        _estrai(archivio, interno, dst)
    finally:
        # Anche quando va male: un archivio a meta' e una lista di checksum
        # orfana sono 30 MB di spazzatura che il prossimo giro riscarica
        # comunque. Misurato scrivendo il braccio noto-cattivo di questo
        # modulo, che lasciava indietro SHASUMS256.txt a ogni rifiuto.
        archivio.unlink(missing_ok=True)
        somme.unlink(missing_ok=True)
    return dst


def node_path(progress=None) -> str:
    """Il Node da usare. Lo scarica se manca.

    L'ordine e' dichiarato apposta, e le due variabili non sono la stessa cosa:
    ``INVPW_NODE_PATH`` e' la nostra, ``PLAYWRIGHT_NODEJS_PATH`` esiste perche'
    chi arriva da Playwright la conosce gia' e sarebbe crudele ignorarla.
    """
    for var in ("INVPW_NODE_PATH", "PLAYWRIGHT_NODEJS_PATH"):
        scelto = os.environ.get(var)
        if scelto:
            if not Path(scelto).is_file():
                raise NodeError("%s punta a %s, che non e' un file." % (var, scelto))
            return scelto

    _, _, nome_bin = _bersaglio()
    gia = cartella() / nome_bin
    if gia.is_file():
        return str(gia)
    return str(_scarica(progress=progress))

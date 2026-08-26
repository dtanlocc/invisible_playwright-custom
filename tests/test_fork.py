"""Il fork di Playwright regge, e non si scioglie senza dirlo.

PERCHE' SERVE UN GATE. Il modo in cui questo fork muore non e' rumoroso: e'
qualcuno che scrive ``from playwright.sync_api import ...`` in un file nuovo. Il
pacchetto ``playwright`` resta installabile e importabile - lo teniamo apposta
fra le dipendenze di sviluppo, per poter confrontare i due bracci - quindi quella
riga FUNZIONA. Semplicemente il codice che esegue non e' piu' il nostro, e nessun
errore lo dice. Con abbastanza righe cosi', il fork diventa una cartella morta
che pesa 9 MB e non serve a niente.

Gli stessi controlli valgono anche per l'utente finale: un wheel a cui manca
``_driver/`` o ``_pw/`` si installa benissimo e muore al primo lancio.
"""

import pathlib
import re

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "invisible_playwright"
TESTS = pathlib.Path(__file__).resolve().parent

#: I file del client vendorizzato importano se stessi con il loro nome completo,
#: quindi non sono violazioni. Idem la suite upstream di Microsoft, che e' una
#: copia di riferimento e va letta com'e'.
ESCLUSI = ("_pw", "_driver", "playwright-upstream", "vendor")

RIGA_VIETATA = re.compile(r"^\s*(from playwright[\s.]|import playwright[\s.])")


def _file_da_controllare():
    for radice in (SRC, TESTS):
        for f in radice.rglob("*.py"):
            if any(p in ESCLUSI for p in f.parts):
                continue
            yield f


def test_nessuno_importa_il_playwright_installato():
    """La riga che scioglie il fork, e che non da' nessun errore."""
    colpevoli = []
    for f in _file_da_controllare():
        for n, riga in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if RIGA_VIETATA.match(riga):
                colpevoli.append("%s:%d  %s" % (f.name, n, riga.strip()))
    assert not colpevoli, (
        "questi file importano il pacchetto playwright INSTALLATO invece del "
        "client vendorizzato in _pw/. Funziona, e proprio per questo e' un "
        "difetto: il codice eseguito non e' quello che crediamo di spedire.\n  "
        + "\n  ".join(colpevoli))


def test_il_client_vendorizzato_e_quello_che_si_importa():
    from invisible_playwright._pw.sync_api import sync_playwright
    modulo = pathlib.Path(sync_playwright.__module__.replace(".", "/"))
    import invisible_playwright._pw as pw
    assert "invisible_playwright" in str(pathlib.Path(pw.__file__).resolve()), (
        "il client importato non e' quello dentro il nostro pacchetto")


def test_il_driver_punta_dentro_di_noi():
    from invisible_playwright._pw._impl._driver import driver_root
    r = driver_root()
    assert r.name == "_driver"
    assert "invisible_playwright" in str(r)
    assert (r / "package" / "cli.js").is_file(), (
        "manca %s: senza il cli.js il browser non parte" % (r / "package" / "cli.js"))


def test_il_bundle_che_vogliamo_modificare_c_e():
    """Il fork esiste per poter cambiare questo file. Se sparisce, non esiste."""
    from invisible_playwright._pw._impl._driver import driver_root
    core = driver_root() / "package" / "lib" / "coreBundle.js"
    assert core.is_file(), "manca coreBundle.js, che e' il motivo del fork"
    assert core.stat().st_size > 1_000_000


def test_utils_bundle_c_e():
    """Misurato: tolto, il driver muore con 'Connection closed while reading'."""
    from invisible_playwright._pw._impl._driver import driver_root
    u = driver_root() / "package" / "lib" / "utilsBundle.js"
    assert u.is_file(), "utilsBundle.js serve davvero, non e' peso morto"


@pytest.mark.parametrize("nome", ["LICENSE", "NOTICE", "ThirdPartyNotices.txt"])
def test_i_file_di_licenza_del_fork_ci_sono(nome):
    """Apache-2.0 non e' una formalita': e' la condizione per ridistribuire.

    Il pyproject dichiara ``MIT AND Apache-2.0`` proprio per questa cartella.
    """
    from invisible_playwright._pw._impl._driver import driver_root
    assert (driver_root() / "package" / nome).is_file()


def test_la_versione_di_node_e_dichiarata_una_volta_sola():
    from invisible_playwright import _node
    assert _node.NODE_VERSION.startswith("v")
    altrove = [f.name for f in _file_da_controllare()
               if f.name != "_node.py" and f.name != "test_fork.py"
               and _node.NODE_VERSION in f.read_text(encoding="utf-8")]
    assert not altrove, (
        "la versione di Node compare anche in %s: un numero scritto due volte "
        "diverge" % altrove)


def _sorgenti_iniettate():
    """Le stringhe che il bundle inietta dentro la pagina, una per riga fisica.

    Sono dichiarate come ``sourceN = '...'`` con apici SINGOLI e con gli a capo
    scritti come due caratteri, quindi ognuna occupa una riga sola del file.
    """
    from invisible_playwright._pw._impl._driver import driver_root
    testo = (driver_root() / "package" / "lib" / "coreBundle.js").read_text(
        encoding="utf-8", errors="replace")
    for numero, riga in enumerate(testo.splitlines(), 1):
        m = re.match(r"^\s*(source\d*) = '", riga)
        if m:
            yield numero, m.group(1), riga




def _apice_non_protetto(riga):
    """Dove la stringa a apici singoli si chiude prima della fine, o None.

    Restituisce il testo che segue la chiusura, cosi' chi legge il fallimento
    vede subito cosa e' rimasto fuori dalla stringa.
    """
    barra = chr(92)
    corpo = riga[riga.index("'") + 1:]
    k = 0
    while k < len(corpo):
        if corpo[k] == barra:
            k += 2
            continue
        if corpo[k] == "'":
            resto = corpo[k + 1:].strip()
            return None if resto in (";", "", ");") else resto[:80]
        k += 1
    return "la stringa non si chiude affatto"


def test_le_sorgenti_iniettate_hanno_gli_apici_bilanciati():
    """Un apostrofo in un commento chiude la stringa e rompe tutto il bundle.

    Successo il 2026-08-24: un commento italiano aggiunto dentro ``source4``
    conteneva ``piu'`` e ``cioe'``. La stringa si e' chiusa li', il file e'
    diventato JavaScript non valido e il driver non e' piu' partito affatto.

    Il difetto non si vede a occhio - quelle righe sono lunghe centinaia di
    migliaia di caratteri - e non lo vede nessun test che importi soltanto il
    pacchetto Python. Nessun Node richiesto: vale anche dove il runtime non e'
    ancora stato scaricato.
    """
    trovate = list(_sorgenti_iniettate())
    assert trovate, "nessuna sorgente iniettata trovata: il controllo tacerebbe"
    for numero, nome, riga in trovate:
        resto = _apice_non_protetto(riga)
        assert resto is None, (
            "coreBundle.js:%d, %s: la stringa iniettata si chiude troppo presto, "
            "dopo di lei resta %r - quasi sempre e' un apostrofo dentro un "
            "commento" % (numero, nome, resto))


def test_il_controllo_degli_apici_vede_un_apostrofo_vero():
    """La mutazione noto-cattiva, sulla forma esatta che ha rotto il bundle."""
    buona = "    source4 = '\nmarkTargetElements() {\n  // non dispatcha niente\n}';"
    assert _apice_non_protetto(buona) is None
    cattiva = "    source4 = '\nmarkTargetElements() {\n  // non dispatcha piu' niente\n}';"
    assert _apice_non_protetto(cattiva) is not None
    mai_chiusa = "    source4 = '\nqualcosa senza fine"
    assert _apice_non_protetto(mai_chiusa) == "la stringa non si chiude affatto"

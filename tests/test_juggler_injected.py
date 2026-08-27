"""Lo script iniettato chiamato da Python: selettori, azionabilita', e la
verifica che conta - che il nostro client non attraversi nel realm della pagina.
"""
from __future__ import annotations

import http.server
import importlib.util
import pathlib
import socketserver
import tempfile
import threading
import time

import pytest

from invisible_playwright._juggler import injected as ini

PAGINA = b"""<!doctype html><html><head><title>azionabile</title></head><body>
<h1 id=titolo>ciao mondo</h1>
<button id=ok>premi</button>
<button id=spento disabled>spento</button>
<div id=invisibile style="display:none">non mi vedi</div>
<input id=campo placeholder=scrivi>
<div data-testid=marchiato>col testid</div>
<p class=tre>a</p><p class=tre>b</p><p class=tre>c</p>
</body></html>"""


def _servi(corpo):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *a):
            pass

    return H


def _apri(binario, corpo):
    """Lancia, naviga, e torna (connessione, ciclo, iniettato, frame, chiudi)."""
    from invisible_core.launch import build_launch_plan
    from invisible_playwright._juggler import connection as conn
    from invisible_playwright._juggler.lifecycle import CicloDiVita

    profilo = tempfile.mkdtemp(prefix="inj_test_")
    piano = build_launch_plan(5, profile_dir=profilo, timezone="UTC", locale="en-US")
    srv = socketserver.TCPServer(("127.0.0.1", 0), _servi(corpo))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    c = conn.avvia(binario, profilo, headless=True, ambiente=piano.env)
    sessioni: dict = {}
    c.su_evento = lambda m, p, s: (
        sessioni.__setitem__(p["targetInfo"]["targetId"], p["sessionId"])
        if m == "Browser.attachedToTarget" else None)
    c.manda("Browser.enable", {"attachToDefaultContext": True})
    ctx = c.manda("Browser.createBrowserContext", {"removeOnDetach": True})
    pag = c.manda("Browser.newPage", {"browserContextId": ctx["browserContextId"]})
    fine = time.time() + 20
    while pag["targetId"] not in sessioni and time.time() < fine:
        time.sleep(0.02)
    sess = sessioni[pag["targetId"]]
    ciclo = CicloDiVita(c, sess)
    inj = ini.ScriptIniettato(c, sess)
    inj.prepara()
    time.sleep(0.4)
    ciclo.naviga("http://127.0.0.1:%d/" % srv.server_address[1],
                 aspetta="load", timeout=30)

    def chiudi():
        c.chiudi()
        srv.shutdown()

    return c, ciclo, inj, ciclo.frame_principale, chiudi


# ── senza browser ───────────────────────────────────────────────────────────

def test_il_nome_del_mondo_e_quello_del_NOSTRO_fork():
    """⛔ Upstream lo chiama diversamente: il nostro fork lo ha rinominato
    perche' viaggiava sul window della pagina. Se questa costante e il driver
    divergono, l'aggancio si rompe in SILENZIO - il contesto nasce, ma con un
    altro nome, e nessuno lo riconosce."""
    assert ini.MONDO_UTILITA == "__ctx_aux__"


def test_lo_script_iniettato_e_il_NOSTRO_non_upstream():
    """Un blob estratto da un bundle upstream perderebbe tutte le correzioni di
    stealth senza che niente dia errore."""
    js = pathlib.Path(ini.__file__).with_name("injected.js").read_text(
        encoding="utf-8", errors="replace")
    assert "MODIFICATO da invisible_playwright" in js
    assert "InjectedScript" in js
    for motore in ("internal:role", "internal:testid", "internal:label"):
        assert motore in js, motore


def test_le_opzioni_dichiarano_il_mondo_di_utilita_e_NON_underTest():
    """Le due righe che tengono fuori i tell: `isUtilityWorld` vero (o il
    costruttore installa 13 listener sull'addEventListener della pagina) e
    `isUnderTest` falso (o pianta window.builtins ENUMERABILE)."""
    sorgente = pathlib.Path(ini.__file__).read_text(encoding="utf-8")
    assert '"isUtilityWorld": True' in sorgente
    assert '"isUnderTest": False' in sorgente


# ── col browser ─────────────────────────────────────────────────────────────

@pytest.mark.e2e
def test_i_motori_di_selettori_rispondono(firefox_binary):
    c, ciclo, inj, f, chiudi = _apri(firefox_binary, PAGINA)
    try:
        for sel in ("#titolo", "css=#ok", "text=ciao mondo",
                    "internal:testid=[data-testid='marchiato']",
                    "xpath=//button[@id='ok']"):
            oid = inj.risolvi(f, sel)
            assert oid, "il selettore %r non ha trovato niente" % sel
            inj.libera(f, oid)
        assert inj.risolvi(f, "#nonesiste") is None
        assert inj.quanti(f, ".tre") == 3
    finally:
        chiudi()


@pytest.mark.e2e
def test_l_azionabilita_DISTINGUE_invece_di_dire_sempre_si(firefox_binary):
    """⛔ L'INPUT NOTO-CATTIVO DI QUESTO FILE.

    `checkElementStates` e' ASINCRONA. Se la funzione che la chiama non
    l'aspettasse, tornerebbe una Promise, la Promise e' un oggetto vero, e OGNI
    elemento risulterebbe azionabile - compreso un bottone disabilitato e un
    div con `display:none`. Un'azionabilita' che dice sempre si' non e' un
    controllo, e il guasto sarebbe muto.

    Qui si pretende che DISTINGUA, e che dica QUALE stato manca.
    """
    c, ciclo, inj, f, chiudi = _apri(firefox_binary, PAGINA)
    try:
        pieni = ["visible", "stable", "enabled"]

        ok = inj.stati(f, inj.risolvi(f, "#ok"), pieni)
        assert ok == {"ok": True}, ok

        spento = inj.stati(f, inj.risolvi(f, "#spento"), pieni)
        assert spento["ok"] is False and spento["manca"] == "enabled", spento

        invisibile = inj.stati(f, inj.risolvi(f, "#invisibile"), ["visible"])
        assert invisibile["ok"] is False and invisibile["manca"] == "visible", invisibile

        campo = inj.stati(f, inj.risolvi(f, "#campo"),
                          ["visible", "stable", "enabled", "editable"])
        assert campo == {"ok": True}, campo
    finally:
        chiudi()


@pytest.mark.e2e
def test_il_testo_si_legge(firefox_binary):
    c, ciclo, inj, f, chiudi = _apri(firefox_binary, PAGINA)
    try:
        oid = inj.risolvi(f, "#titolo")
        assert inj.testo(f, oid) == "ciao mondo"
    finally:
        chiudi()


@pytest.mark.e2e
def test_un_javascript_che_LANCIA_arriva_come_errore_non_come_None(firefox_binary):
    """⛔ Un'eccezione della pagina NON torna come errore di protocollo: torna
    come `exceptionDetails` dentro una risposta RIUSCITA. Chi guarda solo il
    codice di ritorno legge `None` e prosegue con un valore che non esiste."""
    c, ciclo, inj, f, chiudi = _apri(firefox_binary, PAGINA)
    try:
        with pytest.raises(ini.ErroreValutazione) as e:
            inj.valuta(f, "(() => { throw new Error('rotto apposta'); })()")
        assert "rotto apposta" in str(e.value)
    finally:
        chiudi()


LETTURA = b"""<!doctype html><html><head><title>lettura</title></head><body>
<div id=t>ciao <b>mondo</b></div>
<input id=campo value=pippo>
<input id=spunta type=checkbox checked>
<button id=spento disabled>no</button>
<div id=nascosto style=display:none>x</div>
<a id=link href="/qui">vai</a>
</body></html>"""


@pytest.mark.e2e
def test_il_gruppo_LETTURA_DEL_DOM(firefox_binary):
    """Le operazioni della voce 6, gruppo "lettura del DOM" (§6.5)."""
    c, ciclo, inj, f, chiudi = _apri(firefox_binary, LETTURA)
    try:
        assert inj.titolo(f) == "lettura"
        assert inj.contenuto(f).startswith("<!DOCTYPE html>")

        t = inj.risolvi(f, "#t")
        assert inj.testo_interno(f, t) == "ciao mondo"
        assert inj.html_interno(f, t) == "ciao <b>mondo</b>"
        riq = inj.riquadro(f, t)
        assert riq and riq["width"] > 0 and riq["height"] > 0, riq

        assert inj.valore(f, inj.risolvi(f, "#campo")) == "pippo"

        link = inj.risolvi(f, "#link")
        assert inj.attributo(f, link, "href") == "/qui"
        # ⛔ Un attributo ASSENTE torna None, non la stringa vuota: sono due
        # cose diverse e chi legge deve poterle distinguere.
        assert inj.attributo(f, link, "nonesiste") is None

        # un elemento nascosto non ha quad: None, non un riquadro a zero
        assert inj.riquadro(f, inj.risolvi(f, "#nascosto")) is None
    finally:
        chiudi()


@pytest.mark.e2e
def test_gli_stati_DISTINGUONO_invece_di_dire_sempre_vero(firefox_binary):
    """⛔ IL SECONDO NOTO-CATTIVO DI QUESTO FILE.

    `injected.elementState` NON torna un booleano: torna
    `{matches, received}`. Leggerlo come un booleano darebbe `True` sempre,
    perche' un dizionario non vuoto e' vero - e ogni elemento risulterebbe
    visibile, abilitato e spuntato. Un controllo che dice sempre si' non e' un
    controllo.
    """
    c, ciclo, inj, f, chiudi = _apri(firefox_binary, LETTURA)
    try:
        assert inj.stato(f, inj.risolvi(f, "#t"), "visible") is True
        assert inj.stato(f, inj.risolvi(f, "#nascosto"), "visible") is False
        assert inj.stato(f, inj.risolvi(f, "#nascosto"), "hidden") is True
        assert inj.stato(f, inj.risolvi(f, "#spento"), "disabled") is True
        assert inj.stato(f, inj.risolvi(f, "#spento"), "enabled") is False
        assert inj.stato(f, inj.risolvi(f, "#spunta"), "checked") is True
        assert inj.stato(f, inj.risolvi(f, "#campo"), "editable") is True
    finally:
        chiudi()


@pytest.mark.e2e
def test_le_letture_che_non_hanno_senso_RIFIUTANO(firefox_binary):
    """Un `input_value` su un div e uno stato inventato tornerebbero
    `undefined` in silenzio. Un valore che non vuol dire niente e' peggio di
    un errore, perche' prosegue."""
    c, ciclo, inj, f, chiudi = _apri(firefox_binary, LETTURA)
    try:
        with pytest.raises(ini.ErroreValutazione) as e:
            inj.valore(f, inj.risolvi(f, "#t"))
        assert "input" in str(e.value)

        with pytest.raises(ValueError) as e2:
            inj.stato(f, inj.risolvi(f, "#t"), "quandoMiPare")
        assert "sconosciuto" in str(e2.value)
    finally:
        chiudi()


@pytest.mark.e2e
def test_IL_NOSTRO_CLIENT_NON_ATTRAVERSA_nel_realm_della_pagina(firefox_binary):
    """La verifica che conta piu' di tutte.

    Riusa la pagina-trappola del gate degli attraversamenti - venti trappole
    armate nel PRIMO script - ma la pilota con `_juggler` invece che con
    Playwright. Se il driver era pulito e il nostro client no, il difetto e'
    nostro e questo test e' l'unico posto che lo direbbe.
    """
    spec = importlib.util.spec_from_file_location(
        "oc", str(pathlib.Path(__file__).resolve().parents[3]
                  / "tests" / "gates" / "observable_crossings.py"))
    if spec is None or not pathlib.Path(spec.origin).is_file():
        pytest.skip("la pagina-trappola vive nel workbench, che qui non c'e'")
    oc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oc)

    c, ciclo, inj, f, chiudi = _apri(firefox_binary, oc.PAGINA)
    try:
        viva = inj.chiama(f, "(injected) => document.getElementById('spia')"
                             ".getAttribute('data-viva')")
        assert viva == "1", (
            "trappole NON agganciate (%s): uno zero non varrebbe niente" % viva)

        def leggi():
            time.sleep(0.15)
            g = inj.chiama(f, "(injected) => document.getElementById('spia')"
                              ".getAttribute('data-conta') || ''") or ""
            fuori = {}
            for x in g.split():
                k, _, v = x.partition("=")
                try:
                    fuori[k] = int(v)
                except ValueError:
                    pass
            return fuori

        prima = leggi()
        assert prima, "la pagina non ha pubblicato i contatori"

        for azione in (lambda: inj.risolvi(f, "#bersaglio"),
                       lambda: inj.quanti(f, "div"),
                       lambda: inj.risolvi(f, "text=cliccami"),
                       lambda: inj.stati(f, inj.risolvi(f, "#bersaglio"),
                                         ["visible", "stable", "enabled"]),
                       lambda: inj.testo(f, inj.risolvi(f, "#bersaglio")),
                       lambda: inj.valuta(f, "({a: 1, b: [1,2,3]})")):
            azione()
        dopo = leggi()

        mossi = {k: dopo[k] - prima.get(k, 0)
                 for k in dopo if dopo[k] - prima.get(k, 0)}
        assert not mossi, "il nostro client ha attraversato: %s" % mossi
    finally:
        chiudi()

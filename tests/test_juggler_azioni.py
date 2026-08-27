"""Il ciclo di ritentativo e le azioni.

⛔ E' il pezzo che sbaglia in silenzio: se una condizione si controlla UNA
volta e poi si agisce, fra il controllo e l'azione la pagina puo' essere
cambiata. Non si rompe, si rompe una volta su venti.
"""
from __future__ import annotations

import http.server
import socketserver
import tempfile
import threading
import time

import pytest

from invisible_playwright._juggler.azioni import Azioni, ElementoNonAzionabile

PAGINA = b"""<!doctype html><html><head><title>azioni</title></head><body>
<button id=ok onclick="this.dataset.clic=(+(this.dataset.clic||0)+1)">premi</button>
<input id=campo>
<input id=data type=date>
<div id=eventi data-conta="0" data-fidati=""></div>
<div id=tardi style="display:none"><button id=lento>tardivo</button></div>
<script>
  const c = document.getElementById('campo');
  const e = document.getElementById('eventi');
  let n = 0;
  const d = document.getElementById('data');
  for (const el of [c, d])
    for (const t of ['input','change']) el.addEventListener(t, ev => {
      n++; e.dataset.conta = n;
      e.dataset.fidati = (e.dataset.fidati || '') + (ev.isTrusted ? 'T' : 'F');
    });
  setTimeout(() => { document.getElementById('tardi').style.display = 'block'; }, 1200);
</script>
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
    from invisible_core.launch import build_launch_plan
    from invisible_playwright._juggler import connection as conn
    from invisible_playwright._juggler.injected import ScriptIniettato
    from invisible_playwright._juggler.lifecycle import CicloDiVita

    profilo = tempfile.mkdtemp(prefix="az_test_")
    piano = build_launch_plan(9, profile_dir=profilo, timezone="UTC", locale="en-US")
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
    inj = ScriptIniettato(c, sess)
    inj.prepara()
    time.sleep(0.4)
    ciclo.naviga("http://127.0.0.1:%d/" % srv.server_address[1],
                 aspetta="load", timeout=30)
    az = Azioni(c, sess, ciclo, inj)

    def chiudi():
        c.chiudi()
        srv.shutdown()

    return az, inj, ciclo.frame_principale, chiudi


def _dataset(inj, f, sel, attr):
    oid = inj.risolvi(f, sel)
    v = inj.chiama(f, "(injected, el, a) => el.dataset[a] || ''",
                   {"objectId": oid}, attr)
    inj.libera(f, oid)
    return v


# ── senza browser ───────────────────────────────────────────────────────────

def test_un_ciclo_senza_frame_lo_DICE_invece_di_scadere():
    class CicloFinto:
        frame_principale = None
    az = Azioni(None, "S", CicloFinto(), None)
    with pytest.raises(RuntimeError) as e:
        az.clicca("#x")
    assert "frame principale" in str(e.value)


def test_la_digitazione_NON_manda_keypress():
    """⛔ `_dispatchKeyEvent` di Juggler conosce solo `keydown` e `keyup`, e su
    tutto il resto alza `Unknown type`. Un `keypress` - che e' quello che
    verrebbe da scrivere per abitudine - fa fallire l'intera digitazione."""
    import inspect
    sorgente = inspect.getsource(Azioni._digita)
    assert "keypress" not in sorgente.split('"""')[2], (
        "il codice manda un keypress: Juggler lo rifiuta")
    assert '"keydown"' in sorgente and '"keyup"' in sorgente


# ── col browser ─────────────────────────────────────────────────────────────

@pytest.mark.e2e
def test_il_click_arriva_alla_pagina(firefox_binary):
    az, inj, f, chiudi = _apri(firefox_binary, PAGINA)
    try:
        az.clicca("#ok")
        assert _dataset(inj, f, "#ok", "clic") == "1"
        az.clicca("#ok")
        assert _dataset(inj, f, "#ok", "clic") == "2"
    finally:
        chiudi()


@pytest.mark.e2e
def test_gli_eventi_del_riempimento_sono_FIDATI(firefox_binary):
    """⛔ L'INPUT NOTO-CATTIVO DI QUESTO FILE.

    Dispatchare gli eventi dallo script iniettato produce `isTrusted: false`, e
    la mescolanza fra eventi fidati e non sullo stesso form e' un tell piu'
    economico di qualunque segnale singolo: nessuna API di enumerazione, un
    solo `addEventListener`. E' [B175], gia' pagato una volta.

    ⛔ E SERVONO DUE CAMPI, non uno, perche' i due percorsi sono diversi e la
    prima stesura di questo test ne provava uno solo. Su un input di TESTO
    `injected.fill` torna `needsinput` e il testo si DIGITA: quegli eventi sono
    fidati perche' nascono dai tasti, e una mutazione a
    `Page.dispatchTrustedInputEvents` **sopravviveva** perche' quella riga non
    veniva mai eseguita. Il percorso di [B175] e' l'altro: gli input il cui
    valore si IMPOSTA - `date`, `color`, `range`, `time` - dove `fill` torna
    `done` e gli eventi vanno chiesti al comando fidato.
    """
    az, inj, f, chiudi = _apri(firefox_binary, PAGINA)
    try:
        # percorso A: il testo si DIGITA
        az.riempi("#campo", "ciao")
        oid = inj.risolvi(f, "#campo")
        assert inj.chiama(f, "(injected, el) => el.value", {"objectId": oid}) == "ciao"
        inj.libera(f, oid)

        # percorso B: il valore si IMPOSTA, ed e' quello di [B175]
        az.riempi("#data", "2026-08-27")
        oid = inj.risolvi(f, "#data")
        assert inj.chiama(f, "(injected, el) => el.value",
                          {"objectId": oid}) == "2026-08-27"
        inj.libera(f, oid)

        fidati = _dataset(inj, f, "#eventi", "fidati")
        assert fidati, "la pagina non ha ricevuto nessun evento"
        assert len(fidati) >= 4, (
            "troppi pochi eventi (%r): uno dei due percorsi non ha sparato"
            % fidati)
        assert "F" not in fidati, (
            "eventi NON fidati fra quelli ricevuti: %r" % fidati)
    finally:
        chiudi()


@pytest.mark.e2e
def test_il_ciclo_ASPETTA_un_elemento_che_compare_dopo(firefox_binary):
    """La ragione per cui il ciclo esiste: senza, questo sarebbe un fallimento
    invece di un'attesa. L'elemento compare dopo 1,2 secondi."""
    az, inj, f, chiudi = _apri(firefox_binary, PAGINA)
    try:
        az.clicca("#lento", timeout=15)
    finally:
        chiudi()


@pytest.mark.e2e
def test_un_timeout_DICE_il_motivo_dell_ultimo_giro(firefox_binary):
    """⛔ Un `TimeoutError` nudo su un ciclo di ritentativi e' la cosa meno
    utile che si possa stampare: senza il motivo dell'ultimo giro, chi legge
    non sa se il selettore non trovava niente, se mancava uno stato, o se
    l'elemento non aveva quad."""
    az, inj, f, chiudi = _apri(firefox_binary, PAGINA)
    try:
        with pytest.raises(ElementoNonAzionabile) as e:
            az.clicca("#nonesistera", timeout=2)
        testo = str(e.value)
        assert "#nonesistera" in testo
        assert "tentativi" in testo
        assert "il selettore non trova niente" in testo, testo
    finally:
        chiudi()


@pytest.mark.e2e
def test_un_elemento_MAI_azionabile_dice_QUALE_stato_manca(firefox_binary):
    """Un bottone disabilitato non e' "non trovato": e' trovato e non
    azionabile, e il messaggio deve distinguere i due casi."""
    corpo = (b"<!doctype html><html><body>"
             b"<button id=spento disabled>no</button></body></html>")
    az, inj, f, chiudi = _apri(firefox_binary, corpo)
    try:
        with pytest.raises(ElementoNonAzionabile) as e:
            az.clicca("#spento", timeout=2)
        assert "manca enabled" in str(e.value), str(e.value)
    finally:
        chiudi()

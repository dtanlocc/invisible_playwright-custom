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
<input id=casella type=checkbox>
<input id=gia type=checkbox checked>
<select id=scelta><option value=a>A</option><option value=b>B</option></select>
<div id=tasti data-log=""></div>
<div id=dbl data-n="0" ondblclick="this.dataset.n=(+this.dataset.n+1)">doppio</div>
<div id=sorgente draggable=true style="width:60px;height:30px">trascina</div>
<div id=bersaglio data-drop="0" style="width:60px;height:30px">qui</div>
<script>
  const log = document.getElementById('tasti');
  document.addEventListener('keydown', ev => {
    log.dataset.log += ev.key + '|' + ev.code + '|' + ev.keyCode + '|'
      + (ev.shiftKey ? 'S' : '-') + (ev.ctrlKey ? 'C' : '-')
      + '|' + (ev.isTrusted ? 'T' : 'F') + ';';
  });
  const b = document.getElementById('bersaglio');
  b.addEventListener('mouseup', () => { b.dataset.drop = '1'; });
</script>
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
    verrebbe da scrivere per abitudine - fa fallire l'intera digitazione.

    ⛔ E adesso lo chiede agli EVENTI invece che al sorgente di `_digita`.
    Guardare il testo di una funzione lega il test a DOVE sta il codice: la
    digitazione e' passata in `tastiera.py` e questo test e' diventato rosso
    su una proprieta' che era ancora perfettamente vera. Un test che si rompe
    quando il codice trasloca insegna a essere cancellato.
    """
    from invisible_playwright._juggler.tastiera import Tastiera

    class Finta:
        def __init__(self):
            self.tipi = []

        def manda(self, metodo, params, **kw):
            self.tipi.append(params.get("type"))
            return {}

    c = Finta()
    Tastiera(c, "S").digita("ab")
    assert c.tipi, "nessun evento di tasto"
    assert set(c.tipi) == {"keydown", "keyup"}, (
        "tipi che Juggler rifiuta: %r" % sorted(set(c.tipi)))


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


# ── il gruppo "input e puntatore" ───────────────────────────────────────────

class _Finta:
    """Una connessione che registra invece di parlare col browser."""

    def __init__(self):
        self.eventi = []

    def manda(self, metodo, params, **kw):
        self.eventi.append(params)
        return {}


def test_la_maschera_dei_bottoni_NON_e_uno_spostato():
    """⛔ L'INPUT NOTO-CATTIVO DELLE MASCHERE, e nasce da un difetto vero che
    stava in questo file.

    `clicca` scriveva `premuti = 1 << bottone`, che da' 1 per il sinistro -
    quindi sembra giusto - e sbaglia gli altri due: 2 per il centrale e 4 per
    il destro. Firefox li vuole al contrario, letto in `toButtonsMask2` del
    bundle: sinistro 1, DESTRO 2, CENTRALE 4. Un click destro usciva dunque
    dichiarando premuto il centrale, con l'azione perfettamente riuscita e
    nessun test in grado di vederlo.

    La mutazione da rimettere per provare questo test: `MASCHERA_BOTTONI` a
    `{0: 1, 1: 2, 2: 4}`.
    """
    from invisible_playwright._juggler.tastiera import MASCHERA_BOTTONI
    assert MASCHERA_BOTTONI == {0: 1, 1: 4, 2: 2}, (
        "sinistro 1, destro 2, centrale 4 - non 1<<bottone")


def test_i_modificatori_hanno_la_maschera_di_FIREFOX():
    """⛔ Non e' `1 << indice` e non e' quella di Gecko: Alt 1, Control 2,
    Shift 4, Meta 8, letta in `toModifiersMask2`. Juggler la traduce lui nei
    `nsIDOMWindowUtils.MODIFIER_*`, quindi mandare le costanti di Gecko da qui
    darebbe modificatori sbagliati senza nessun errore."""
    from invisible_playwright._juggler.tastiera import MASCHERA_MODIFICATORI
    assert MASCHERA_MODIFICATORI == {"Alt": 1, "Control": 2, "Shift": 4,
                                     "Meta": 8}


def test_il_layout_porta_il_keycode_SENZA_location():
    """⛔ `Page.dispatchKeyEvent` vuole `keyCodeWithoutLocation`, non `keyCode`,
    e i due differiscono proprio sui tasti che esistono due volte: `ShiftLeft`
    ha 160 e 16. Un Firefox vero mette 16 nell'evento."""
    from invisible_playwright._juggler.tastiera import CHIUSURA
    s = CHIUSURA["ShiftLeft"]
    assert s["keyCode"] == 160 and s["keyCodeWithoutLocation"] == 16
    assert CHIUSURA["Shift"]["code"] == "ShiftLeft"


def test_un_tasto_che_non_esiste_si_RIFIUTA_invece_di_uscire_vuoto():
    """⛔ Il difetto che ha fatto nascere `tastiera.py`.

    La prima `_digita` mandava `code: ""` e `keyCode: 0` per ogni carattere:
    l'evento parte, il testo entra, l'azione riesce e i test passano, mentre la
    pagina legge un `event.code` vuoto su un tasto che ogni Firefox vero nomina.
    """
    from invisible_playwright._juggler.tastiera import Tastiera, TastoSconosciuto
    c = _Finta()
    t = Tastiera(c, "S")
    with pytest.raises(TastoSconosciuto):
        t.digita(chr(0x4E2D))
    assert not c.eventi, "ha mandato un evento per un tasto che non esiste"
    t.premi("a")
    assert all(e["code"] and e["keyCode"] for e in c.eventi), (
        "un evento e' uscito con code o keyCode vuoti: %r" % c.eventi)


def test_shift_cambia_il_tasto_e_control_toglie_il_testo():
    """Lo stato dei modificatori e' la ragione per cui la tastiera e' una
    classe. ⛔ E `Control+a` NON deve inserire una "a": con un modificatore
    diverso da Shift il `text` esce vuoto, letto nel driver."""
    from invisible_playwright._juggler.tastiera import Tastiera
    c = _Finta()
    t = Tastiera(c, "S")
    t.premi("Shift+KeyA")
    giu = [e for e in c.eventi if e["type"] == "keydown" and e["code"] == "KeyA"]
    assert giu[0]["key"] == "A" and giu[0]["text"] == "A"

    c.eventi.clear()
    t.premi("Control+KeyA")
    giu = [e for e in c.eventi if e["type"] == "keydown" and e["code"] == "KeyA"]
    assert giu[0]["key"] == "a" and giu[0]["text"] == "", (
        "Control+a ha inserito il carattere: %r" % giu[0])
    assert not t.modificatori, "un modificatore e' rimasto giu' dopo il press"


def test_il_keyup_non_porta_MAI_il_testo():
    """⛔ Juggler alza `keyup does not support text option` e la digitazione
    muore a meta'. Letto nel suo `_dispatchKeyEvent`, non dedotto."""
    from invisible_playwright._juggler.tastiera import Tastiera
    c = _Finta()
    Tastiera(c, "S").digita("aZ1")
    su = [e for e in c.eventi if e["type"] == "keyup"]
    assert su and all("text" not in e for e in su)


@pytest.mark.e2e
def test_i_tasti_arrivano_con_code_e_keycode_VERI(firefox_binary):
    """⛔ IL CASO CHE VALE: la pagina legge cosa e' arrivato davvero.

    Le asserzioni senza browser qui sopra provano la TABELLA; questa prova che
    cio' che Juggler consegna alla pagina porta gli stessi valori. Sono due
    domande diverse, e questo progetto ha gia' pagato per averne provata una
    sola: sette leve che il banco credeva impostate e che non arrivavano.
    """
    az, inj, f, chiudi = _apri(firefox_binary, PAGINA)
    try:
        az.metti_a_fuoco("#campo")
        az.tastiera.premi("a")
        az.tastiera.premi("Shift+KeyB")
        az.tastiera.premi("Enter")
        log = _dataset(inj, f, "#tasti", "log")
        voci = [v for v in log.split(";") if v]
        assert voci, "nessun keydown e' arrivato alla pagina"
        per_codice = {v.split("|")[1]: v.split("|") for v in voci}
        assert per_codice["KeyA"][0] == "a"
        assert per_codice["KeyA"][2] == "65", (
            "keyCode sbagliato: %r" % per_codice["KeyA"])
        assert per_codice["KeyB"][0] == "B" and "S" in per_codice["KeyB"][3]
        assert per_codice["Enter"][2] == "13"
        assert all(v.split("|")[4] == "T" for v in voci), (
            "un tasto e' arrivato NON fidato: %r" % log)
    finally:
        chiudi()


@pytest.mark.e2e
def test_spunta_e_togli_spunta_CONTROLLANO_invece_di_invertire(firefox_binary):
    """⛔ Cliccare senza guardare inverte una casella gia' giusta. E il
    RICONTROLLO dopo e' quello che conta: un elemento che intercetta il click,
    o un gestore che rimette il valore, fanno riuscire l'azione lasciando lo
    stato sbagliato."""
    az, inj, f, chiudi = _apri(firefox_binary, PAGINA)
    try:
        def spuntata(sel):
            oid = inj.risolvi(f, sel)
            v = inj.stato(f, oid, "checked")
            inj.libera(f, oid)
            return v

        assert not spuntata("#casella")
        az.spunta("#casella")
        assert spuntata("#casella")
        # ⛔ La seconda volta NON deve cliccare: se cliccasse, invertirebbe.
        az.spunta("#casella")
        assert spuntata("#casella"), "la seconda spunta l'ha invertita"
        assert spuntata("#gia")
        az.togli_spunta("#gia")
        assert not spuntata("#gia")
    finally:
        chiudi()


@pytest.mark.e2e
def test_il_doppio_clic_manda_clickcount_2(firefox_binary):
    """⛔ Due click con `clickCount: 1` producono due `click` e NESSUN
    `dblclick`: l'azione riesce e il gestore del sito non parte mai."""
    az, inj, f, chiudi = _apri(firefox_binary, PAGINA)
    try:
        az.doppio_clic("#dbl")
        assert _dataset(inj, f, "#dbl", "n") == "1", (
            "la pagina non ha visto nessun dblclick")
    finally:
        chiudi()


def test_una_stringa_nuda_NON_va_al_filtro_delle_opzioni():
    """⛔ L'INPUT NOTO-CATTIVO DELLE OPZIONI, e viene da un guasto misurato.

    Il filtro dello script iniettato parte da `matches = true` e lo restringe
    solo se il criterio porta `valueOrLabel`, `value`, `label` o `index`. Una
    stringa nuda non ne ha nessuno: ogni opzione corrisponde e viene scelta LA
    PRIMA. Misurato su un select con A/a e B/b, `["b"]` ha risposto `['a']` e
    lasciato il valore a `a` - riuscito, silenzioso, sbagliato.

    La mutazione da rimettere: passare `list(opzioni)` invece di
    `_normalizza_opzioni(opzioni)` in `scegli_opzioni`.
    """
    from invisible_playwright._juggler.azioni import _normalizza_opzioni
    assert _normalizza_opzioni(["b"]) == [{"valueOrLabel": "b"}]
    assert _normalizza_opzioni([{"value": "b"}]) == [{"value": "b"}]
    assert _normalizza_opzioni([{"index": 1}]) == [{"index": 1}]


@pytest.mark.e2e
def test_scegliere_unopzione_per_valore_o_etichetta(firefox_binary):
    """Il caso vero del noto-cattivo qui sopra: la stringa deve scegliere
    l'opzione GIUSTA, non la prima."""
    az, inj, f, chiudi = _apri(firefox_binary, PAGINA)
    try:
        def valore():
            oid = inj.risolvi(f, "#scelta")
            v = inj.chiama(f, "(injected, el) => el.value", {"objectId": oid})
            inj.libera(f, oid)
            return v

        assert valore() == "a"
        az.scegli_opzioni("#scelta", ["b"])
        assert valore() == "b", "la stringa nuda ha scelto la prima opzione"
        az.scegli_opzioni("#scelta", [{"index": 0}])
        assert valore() == "a"
        # E per ETICHETTA, che e' l'altra meta' di `valueOrLabel`.
        az.scegli_opzioni("#scelta", ["B"])
        assert valore() == "b"
    finally:
        chiudi()


@pytest.mark.e2e
def test_digitare_AGGIUNGE_dove_riempire_SOSTITUISCE(firefox_binary):
    """Scambiarli e' il modo piu' facile di scrivere due volte lo stesso
    testo in un campo."""
    az, inj, f, chiudi = _apri(firefox_binary, PAGINA)
    try:
        def valore():
            oid = inj.risolvi(f, "#campo")
            v = inj.chiama(f, "(injected, el) => el.value", {"objectId": oid})
            inj.libera(f, oid)
            return v

        az.riempi("#campo", "abc")
        az.digita_su("#campo", "de")
        assert valore() == "abcde"
        az.riempi("#campo", "z")
        assert valore() == "z", "riempi non ha sostituito"
    finally:
        chiudi()

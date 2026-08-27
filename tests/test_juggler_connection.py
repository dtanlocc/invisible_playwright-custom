"""La connessione Juggler in Python: parla al binario senza Node in mezzo.

⛔ E' marcato `e2e` perche' lancia un browser vero. Non ha senso provarlo
altrimenti: cio' che va dimostrato e' che la PIPE si collega e che il browser
risponde, e nessuna di quelle due cose si puo' simulare.
"""
from __future__ import annotations

import tempfile

import pytest

from invisible_playwright._juggler import connection as conn
from invisible_playwright._juggler.protocol import COMANDI, EVENTI


# ── senza browser ───────────────────────────────────────────────────────────

def test_il_protocollo_generato_ha_i_cinque_domini():
    """Se il generatore prende un Protocol.js sbagliato, il conto si muove."""
    domini = {n.split(".")[0] for n in COMANDI}
    assert domini == {"Browser", "Page", "Network", "Runtime", "Heap"}
    assert len(COMANDI) == 71, "comandi: %d" % len(COMANDI)
    assert len(EVENTI) == 34, "eventi: %d" % len(EVENTI)


def test_i_comandi_che_il_client_usera_sono_dichiarati():
    """Il browser applica lo schema a MONDO CHIUSO: un comando non dichiarato
    non degrada, RIFIUTA. Questi sono quelli del percorso minimo."""
    for nome in ("Browser.enable", "Browser.createBrowserContext",
                 "Browser.newPage", "Page.navigate", "Runtime.evaluate"):
        assert nome in COMANDI, nome


def test_ogni_tipo_usa_solo_gli_otto_combinatori_noti():
    """Un combinatore nuovo in Protocol.js deve far RIFIUTARE il generatore,
    non passare inosservato."""
    noti = {"String", "Number", "Boolean", "Any", "Enum",
            "Nullable", "Optional", "Array", "Object"}
    visti: set = set()

    def gira(t):
        if not isinstance(t, dict):
            return
        visti.add(t.get("k"))
        if "di" in t:
            gira(t["di"])
        for v in (t.get("campi") or {}).values():
            gira(v)

    for spec in COMANDI.values():
        gira(spec.get("params"))
        gira(spec.get("returns"))
    for spec in EVENTI.values():
        gira(spec)
    assert visti <= noti, "combinatori non previsti: %s" % (visti - noti)


# ── col browser ─────────────────────────────────────────────────────────────

@pytest.mark.e2e
def test_python_parla_a_juggler_senza_node(firefox_binary):
    """La prova su cui poggia lo stacco: pipe, prontezza, comandi, eventi.

    Non usa Playwright, non usa Node, non usa il driver: solo `connection.py`
    e il profilo che `invisible_core` sa preparare.
    """
    from invisible_core.launch import build_launch_plan

    profilo = tempfile.mkdtemp(prefix="juggler_pipe_")
    piano = build_launch_plan(42, profile_dir=profilo,
                              timezone="UTC", locale="en-US")

    c = conn.avvia(firefox_binary, profilo, headless=True,
                   ambiente=piano.env, attesa_prontezza=60.0)
    eventi: list = []
    c.su_evento = lambda metodo, params: eventi.append(metodo)
    try:
        assert c.prontezza_vista, (
            "la riga 'Juggler listening to the pipe' non e' arrivata. "
            "Esce da una dump() che una build MOZILLA_OFFICIAL spegne: "
            "vedi 30-upstream-playwright-patches.md")

        # Browser.enable non dichiara `returns`: la risposta e' None, e va bene.
        c.manda("Browser.enable", {"attachToDefaultContext": True}, timeout=30)

        ctx = c.manda("Browser.createBrowserContext", {"removeOnDetach": True})
        assert ctx and ctx.get("browserContextId"), ctx

        pagina = c.manda("Browser.newPage",
                         {"browserContextId": ctx["browserContextId"]})
        assert pagina and pagina.get("targetId"), pagina

        # Un evento e' arrivato: la pipe porta anche il traffico non richiesto,
        # non solo le risposte.
        assert "Browser.attachedToTarget" in eventi, eventi
    finally:
        c.chiudi()


@pytest.mark.e2e
def test_un_comando_inventato_viene_RIFIUTATO_non_ignorato(firefox_binary):
    """L'input noto-cattivo della connessione.

    `checkScheme` e' a mondo chiuso: se un comando inesistente tornasse un
    silenzio invece di un errore, ogni deriva del protocollo diventerebbe un
    timeout muto invece di una riga che nomina il problema.
    """
    from invisible_core.launch import build_launch_plan

    profilo = tempfile.mkdtemp(prefix="juggler_male_")
    piano = build_launch_plan(7, profile_dir=profilo,
                              timezone="UTC", locale="en-US")
    c = conn.avvia(firefox_binary, profilo, headless=True,
                   ambiente=piano.env, attesa_prontezza=60.0)
    try:
        c.manda("Browser.enable", {"attachToDefaultContext": True}, timeout=30)
        with pytest.raises(conn.ErroreProtocollo) as errore:
            c.manda("Browser.comandoInventato", {}, timeout=10)
        # Il messaggio deve venire dal BROWSER e nominare il comando, non
        # essere un nostro timeout generico.
        assert "comandoInventato" in str(errore.value)
        assert "nessuna risposta" not in str(errore.value), (
            "il browser ha taciuto invece di rifiutare: %s" % errore.value)
    finally:
        c.chiudi()

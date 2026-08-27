"""Il ciclo di vita: albero dei frame, navigazioni, i quattro load state.

⛔ La maggior parte di questi test NON lancia un browser, ed e' voluto: il
ciclo di vita e' una macchina a stati alimentata da eventi, e una macchina a
stati si prova dandole gli eventi. Il difetto che questo file esiste per
sorvegliare - gli stati del documento PRECEDENTE che soddisfano l'attesa del
successivo - si riproduce in tre righe qui e "quasi mai" con un browser vero.
"""
from __future__ import annotations

import tempfile
import threading
import time

import pytest

from invisible_playwright._juggler.lifecycle import (
    CicloDiVita, ErroreNavigazione, QUIETE)


class ConnessioneFinta:
    """Il minimo che `CicloDiVita` usa: un aggancio e un `manda`."""

    def __init__(self, risposte=None):
        self.su_evento = lambda m, p, s: None
        self.mandati = []
        self._risposte = risposte or {}

    def manda(self, metodo, params=None, sessione=None, timeout=30):
        self.mandati.append((metodo, params, sessione))
        return self._risposte.get(metodo)


def ciclo(risposte=None):
    c = ConnessioneFinta(risposte)
    return c, CicloDiVita(c, "S1")


def eventi(v, *coppie):
    for metodo, params in coppie:
        v.c.su_evento(metodo, params, "S1")


# ── l'albero ────────────────────────────────────────────────────────────────

def test_il_frame_senza_padre_e_il_principale():
    c, v = ciclo()
    eventi(v, ("Page.frameAttached", {"frameId": "F1"}))
    assert v.frame_principale == "F1"
    assert v.frames["F1"].padre is None


def test_frameDetached_porta_via_il_SOTTOALBERO_non_solo_il_nodo():
    """Un figlio orfano resterebbe a rispondere per un frame che non c'e' piu'."""
    c, v = ciclo()
    eventi(v,
           ("Page.frameAttached", {"frameId": "F1"}),
           ("Page.frameAttached", {"frameId": "F2", "parentFrameId": "F1"}),
           ("Page.frameAttached", {"frameId": "F3", "parentFrameId": "F2"}),
           ("Page.frameDetached", {"frameId": "F2"}))
    assert set(v.frames) == {"F1"}, v.albero()


def test_gli_eventi_di_UN_ALTRA_sessione_non_entrano():
    """Due pagine aperte insieme: senza il sessionId chi aspetta un load
    prende quello dell'altra scheda."""
    c, v = ciclo()
    c.su_evento("Page.frameAttached", {"frameId": "ALTRO"}, "S2")
    assert v.frames == {}


def test_non_ruba_gli_eventi_a_chi_era_gia_agganciato():
    c = ConnessioneFinta()
    visti = []
    c.su_evento = lambda m, p, s: visti.append(m)
    v = CicloDiVita(c, "S1")
    c.su_evento("Page.frameAttached", {"frameId": "F1"}, "S1")
    assert visti == ["Page.frameAttached"], "l'osservatore precedente e' diventato muto"
    assert "F1" in v.frames


# ── gli stati, e il difetto che conta ───────────────────────────────────────

def test_navigationStarted_azzera_gli_stati():
    c, v = ciclo()
    eventi(v,
           ("Page.frameAttached", {"frameId": "F1"}),
           ("Page.navigationCommitted", {"frameId": "F1", "navigationId": "A",
                                         "url": "http://a/", "name": ""}),
           ("Page.eventFired", {"frameId": "F1", "name": "load"}),
           ("Page.navigationStarted", {"frameId": "F1", "navigationId": "B"}))
    assert v.frames["F1"].stati == set(), "gli stati di A sono sopravvissuti a B"


def test_GLI_STATI_DI_UNA_NAVIGAZIONE_NON_VALGONO_PER_UN_ALTRA():
    """⛔ L'INPUT NOTO-CATTIVO DI QUESTO FILE.

    Riproduce il difetto misurato il 2026-08-27: `Page.navigate` risponde col
    navigationId PRIMA che `navigationStarted` arrivi, e in quella finestra il
    frame porta ancora `commit`/`load` del documento precedente. Con la sola
    pulizia su `navigationStarted` l'attesa si accontentava di quelli e tornava
    subito - misurato: 0,01s e `url=about:blank`.

    Qui gli stati di A ci sono, la nostra navigazione e' B, e l'attesa NON deve
    accontentarsi.
    """
    c, v = ciclo()
    eventi(v,
           ("Page.frameAttached", {"frameId": "F1"}),
           ("Page.navigationCommitted", {"frameId": "F1", "navigationId": "A",
                                         "url": "about:blank", "name": ""}),
           ("Page.eventFired", {"frameId": "F1", "name": "load"}))
    assert v.frames["F1"].stati >= {"commit", "load"}

    with pytest.raises(TimeoutError) as e:
        v.aspetta_stato("F1", "commit", navigazione="B", timeout=0.3)
    assert "non la nostra" in str(e.value), (
        "il messaggio non dice che gli stati sono di un'altra navigazione: %s" % e.value)

    # e appena B commit-a, l'attesa si sblocca
    eventi(v, ("Page.navigationCommitted", {"frameId": "F1", "navigationId": "B",
                                            "url": "http://b/", "name": ""}))
    v.aspetta_stato("F1", "commit", navigazione="B", timeout=1.0)
    assert v.frames["F1"].url == "http://b/"


def test_sameDocumentNavigation_NON_azzera_gli_stati():
    """E' lo stesso documento: un push di history non ricarica la pagina, e
    trattarlo come navigazione fa aspettare un load che non arriva mai."""
    c, v = ciclo()
    eventi(v,
           ("Page.frameAttached", {"frameId": "F1"}),
           ("Page.navigationCommitted", {"frameId": "F1", "navigationId": "A",
                                         "url": "http://a/", "name": ""}),
           ("Page.eventFired", {"frameId": "F1", "name": "load"}),
           ("Page.sameDocumentNavigation", {"frameId": "F1", "url": "http://a/#x"}))
    assert "load" in v.frames["F1"].stati
    assert v.frames["F1"].url == "http://a/#x"


def test_load_implica_domcontentloaded():
    c, v = ciclo()
    eventi(v,
           ("Page.frameAttached", {"frameId": "F1"}),
           ("Page.eventFired", {"frameId": "F1", "name": "load"}))
    assert "domcontentloaded" in v.frames["F1"].stati


def test_una_navigazione_abortita_ALZA_invece_di_scadere():
    c, v = ciclo()
    eventi(v,
           ("Page.frameAttached", {"frameId": "F1"}),
           ("Page.navigationStarted", {"frameId": "F1", "navigationId": "A"}),
           ("Page.navigationAborted", {"frameId": "F1", "navigationId": "A",
                                       "errorText": "NS_ERROR_UNKNOWN_HOST"}))
    with pytest.raises(ErroreNavigazione) as e:
        v.aspetta_stato("F1", "load", navigazione="A", timeout=5)
    assert "NS_ERROR_UNKNOWN_HOST" in str(e.value)


def test_uno_stato_inventato_viene_rifiutato_subito():
    c, v = ciclo()
    with pytest.raises(ValueError) as e:
        v.aspetta_stato("F1", "quandoMiPare", timeout=0.1)
    assert "quattro" in str(e.value)


# ── networkidle ─────────────────────────────────────────────────────────────

def test_il_contatore_in_volo_non_va_sotto_zero():
    """Una risposta senza la sua richiesta arriva davvero - un caricamento
    cominciato prima che ci agganciassimo - e un contatore negativo renderebbe
    networkidle irraggiungibile per SEMPRE."""
    c, v = ciclo()
    eventi(v, ("Network.requestFinished", {"requestId": "R"}),
           ("Network.requestFinished", {"requestId": "R2"}))
    assert v.richieste_in_volo == 0


def test_networkidle_vuole_il_SILENZIO_non_solo_lo_zero():
    c, v = ciclo()
    eventi(v, ("Page.frameAttached", {"frameId": "F1"}),
           ("Network.requestWillBeSent", {"requestId": "R"}),
           ("Network.requestFinished", {"requestId": "R"}))
    assert v.richieste_in_volo == 0
    # Subito dopo lo zero il silenzio non e' ancora maturato.
    with pytest.raises(TimeoutError):
        v.aspetta_stato("F1", "networkidle", timeout=QUIETE / 2)
    # Aspettando la quiete, invece, si sblocca.
    v.aspetta_stato("F1", "networkidle", timeout=QUIETE * 4)


def test_networkidle_si_sblocca_per_SCADENZA_non_per_un_evento():
    """⛔ La condizione si avvera quando NON succede niente. Se l'attesa
    dormisse fino al prossimo evento, resterebbe ferma proprio nel caso che
    deve riuscire. Qui non arriva nessun evento dopo l'ultimo."""
    c, v = ciclo()
    eventi(v, ("Page.frameAttached", {"frameId": "F1"}),
           ("Network.requestWillBeSent", {"requestId": "R"}),
           ("Network.requestFinished", {"requestId": "R"}))
    t0 = time.monotonic()
    v.aspetta_stato("F1", "networkidle", timeout=5)
    assert time.monotonic() - t0 < 2, "si e' sbloccata troppo tardi"


# ── naviga ──────────────────────────────────────────────────────────────────

def test_un_navigationId_NULLO_non_e_un_errore():
    """Il protocollo lo dichiara Nullable: capita quando la navigazione non
    crea un documento nuovo (un ancoraggio). Aspettare un load li' sarebbe un
    timeout su una cosa riuscita."""
    c, v = ciclo({"Page.navigate": {"navigationId": None}})
    eventi(v, ("Page.frameAttached", {"frameId": "F1"}))
    esito = v.naviga("http://a/#x", timeout=1)
    assert esito == {"navigationId": None, "url": "http://a/#x"}


def test_naviga_senza_frame_principale_lo_DICE():
    c, v = ciclo()
    with pytest.raises(RuntimeError) as e:
        v.naviga("http://a/")
    assert "frame principale" in str(e.value)


# ── col browser ─────────────────────────────────────────────────────────────

@pytest.mark.e2e
def test_i_quattro_stati_si_raggiungono_su_una_pagina_vera(firefox_binary):
    import http.server
    import socketserver

    from invisible_core.launch import build_launch_plan
    from invisible_playwright._juggler import connection as conn

    PAGINA = (b"<!doctype html><html><head><title>t</title></head><body>"
              b"<h1>ciao</h1><iframe src='/dentro'></iframe></body></html>")

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            corpo = b"<html><body>figlio</body></html>" if self.path == "/dentro" else PAGINA
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *a):
            pass

    profilo = tempfile.mkdtemp(prefix="ciclo_e2e_")
    piano = build_launch_plan(11, profile_dir=profilo, timezone="UTC", locale="en-US")

    with socketserver.TCPServer(("127.0.0.1", 0), H) as srv:
        porta = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        c = conn.avvia(firefox_binary, profilo, headless=True, ambiente=piano.env)
        try:
            sessioni: dict = {}
            c.su_evento = lambda m, p, s: (
                sessioni.__setitem__(p["targetInfo"]["targetId"], p["sessionId"])
                if m == "Browser.attachedToTarget" else None)
            c.manda("Browser.enable", {"attachToDefaultContext": True})
            ctx = c.manda("Browser.createBrowserContext", {"removeOnDetach": True})
            pag = c.manda("Browser.newPage",
                          {"browserContextId": ctx["browserContextId"]})
            fine = time.time() + 15
            while pag["targetId"] not in sessioni and time.time() < fine:
                time.sleep(0.02)
            v = CicloDiVita(c, sessioni[pag["targetId"]])
            time.sleep(0.5)

            esito = v.naviga("http://127.0.0.1:%d/" % porta,
                             aspetta="load", timeout=30)
            assert esito["navigationId"], esito
            # ⛔ Il difetto che il test unitario riproduce, verificato anche
            # qui: dopo `commit` l'URL NON deve essere about:blank.
            assert esito["url"].startswith("http://127.0.0.1:"), esito["url"]

            v.aspetta_stato(v.frame_principale, "networkidle", timeout=30)
            assert v.richieste_in_volo == 0

            albero = v.albero()
            figli = [d for d in albero.values() if d["padre"]]
            assert len(figli) == 1, albero
            assert "load" in albero[v.frame_principale]["stati"]
        finally:
            c.chiudi()
        srv.shutdown()

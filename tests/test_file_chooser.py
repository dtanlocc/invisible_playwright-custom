"""Il dialogo di scelta file si intercetta, e quello NATIVO non si apre.

PERCHE' SERVE UN GATE. Questa e' la classe di guasto piu' silenziosa che il
progetto abbia visto: tutta la catena JS/Juggler esisteva ed era cablata
correttamente - il comando `Page.setInterceptFileChooserDialog`, l'evento
`Page.fileChooserOpened`, il flag sul docShell, l'observer in PageAgent.js - ma
MANCAVA l'ultimo anello nativo. Il flag veniva scritto e non lo leggeva nessuno
(il commento in `nsDocShell.cpp` lo diceva: "storage only"), e l'observer che
PageAgent ascoltava, `juggler-file-picker-shown`, in tutto l'albero compariva
solo sulla riga che lo ascoltava: nessuno lo notificava mai.

Il risultato: `expect_file_chooser()` restava appeso fino al timeout mentre una
finestra "Apri file" di Windows si apriva davvero, rubando il focus al sistema
operativo - e i documenti pubblici del pacchetto promettono per iscritto il
contrario ("The native OS window never appears on screen"). Nessun test della
suite lo copriva: gli unici che lo toccano sono quelli upstream di Microsoft,
che stanno in `tests/playwright-upstream/`, cartella esclusa da pytest.

⛔ IL TERZO TEST E' IL CONTROLLO E NON VA TOLTO. Sopprimere il dialogo nativo e'
facile; sopprimerlo SOLO quando l'automazione lo ha chiesto e' il punto. Senza
il controllo, questo file resterebbe verde anche se avessimo rotto i file input
per tutti - che e' esattamente il modo in cui si "aggiusta" un difetto
peggiorando il prodotto.
"""
from __future__ import annotations

import http.server
import socketserver
import threading

import pytest

from invisible_playwright import InvisiblePlaywright

PAGINA = b"""<!DOCTYPE html><html><body>
<input id="f" type="file">
<button id="b" onclick="document.getElementById('f').click()">carica</button>
<pre id="out"></pre>
<script>
document.getElementById('f').addEventListener('change', (e) => {
  const n = e.target.files.length ? e.target.files[0].name : '(nessuno)';
  document.getElementById('out').textContent = 'change:' + n;
});
</script></body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(PAGINA)))
        self.end_headers()
        self.wfile.write(PAGINA)

    def log_message(self, *a):
        pass


@pytest.fixture
def pagina_locale():
    """Una pagina vera da 127.0.0.1: i `data:` URL portano una CSP propria."""
    with socketserver.TCPServer(("127.0.0.1", 0), _Handler) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            yield "http://127.0.0.1:%d" % srv.server_address[1]
        finally:
            srv.shutdown()


@pytest.fixture
def file_campione(tmp_path):
    p = tmp_path / "campione.txt"
    p.write_bytes(b"contenuto di prova")
    return str(p)


@pytest.mark.e2e
def test_expect_file_chooser_riceve_levento(firefox_binary, pagina_locale):
    """L'evento arriva. Prima del 2026-08-25 questo scadeva sempre."""
    with InvisiblePlaywright(seed=42, binary_path=firefox_binary) as browser:
        page = browser.new_page()
        page.goto(pagina_locale, wait_until="load")
        with page.expect_file_chooser(timeout=15000) as info:
            page.click("#b")
        chooser = info.value
        # is_multiple e' un METODO su questo client, non una proprieta'.
        assert chooser.is_multiple() is False
        assert chooser.element is not None


@pytest.mark.xfail(
    reason="difetto PREESISTENTE, non di questa patch: impostare file REALI su "
           "un input fallisce (`setFileInputFiles` -> 'object ... no longer "
           "usable', e `set_input_files` va in timeout). Verificato sul binario "
           "dell'ultima release, dove fallisce identico. Vedi 70-known-bugs.md "
           "[B178]. Questo test diventa verde da solo il giorno in cui B178 e' "
           "chiuso, e per questo non e' stato cancellato.",
    strict=False)
@pytest.mark.e2e
def test_i_file_scelti_arrivano_alla_pagina(firefox_binary, pagina_locale,
                                            file_campione):
    """Non basta che l'evento scatti: il file deve arrivare davvero al DOM.

    Un `change` che non parte sarebbe un segnale soppresso, che per la regola 12
    e' un FALLIMENTO e non un successo.
    """
    with InvisiblePlaywright(seed=42, binary_path=firefox_binary) as browser:
        page = browser.new_page()
        page.goto(pagina_locale, wait_until="load")
        with page.expect_file_chooser(timeout=15000) as info:
            page.click("#b")
        info.value.set_files(file_campione)
        page.wait_for_timeout(400)
        assert "campione.txt" in page.inner_text("#out")


@pytest.mark.xfail(
    reason="stesso difetto PREESISTENTE di B178: `set_input_files` con un "
           "percorso reale va in timeout anche sul binario dell'ultima "
           "release. Resta qui perche' e' IL CONTROLLO - il giorno in cui B178 "
           "e' chiuso deve tornare a dimostrare che il dialogo si sopprime "
           "SOLO su richiesta - ma non puo' essere un'asserzione dura finche' "
           "l'API che usa e' rotta a monte.",
    strict=False)
@pytest.mark.e2e
def test_senza_intercettazione_i_file_input_restano_normali(firefox_binary,
                                                            pagina_locale,
                                                            file_campione):
    """IL CONTROLLO. Il rimedio deve sopprimere il dialogo SOLO su richiesta.

    Qui nessuno chiede di intercettare: `set_input_files` deve continuare a
    funzionare e la pagina deve vedere il suo `change`. Se questo diventa rosso,
    il rimedio ha rotto i file input per tutti invece di intercettarli per noi.
    """
    with InvisiblePlaywright(seed=42, binary_path=firefox_binary) as browser:
        page = browser.new_page()
        page.goto(pagina_locale, wait_until="load")
        page.set_input_files("#f", file_campione)
        page.wait_for_timeout(300)
        assert "campione.txt" in page.inner_text("#out")

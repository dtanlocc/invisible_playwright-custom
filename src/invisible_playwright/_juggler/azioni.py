"""Il ciclo di ritentativo, e le azioni che ci girano dentro.

⛔ QUESTO E' IL PEZZO CHE SBAGLIA IN SILENZIO, e il motivo e' la forma del
ciclo: se una condizione viene controllata UNA VOLTA e poi si agisce, fra il
controllo e l'azione la pagina puo' essere cambiata. Non si rompe: si rompe
UNA VOLTA SU VENTI, quando il caricamento e' piu' lento del solito.

LA FORMA GIUSTA, e ogni riga di questo file serve a tenerla:

    finche' non scade:
        RISOLVI IL SELETTORE DA CAPO        <- non si riusa l'handle vecchio
        chiedi se e' azionabile
        prendi il punto
        agisci
        se qualcosa dice "non e' piu' li'": RICOMINCIA

⛔ **Il selettore si risolve a OGNI giro.** Riusare l'handle del giro
precedente e' l'errore che rende il ciclo inutile: se il DOM e' cambiato,
quell'handle punta a un nodo staccato, e l'azione va a vuoto senza dire niente.

⛔ **E un timeout deve dire PERCHE'.** Un `TimeoutError` nudo su un ciclo di
ritentativi e' la cosa meno utile che si possa stampare: il motivo dell'ultimo
giro - "manca visible", "il selettore non trova niente", "nessun quad" - e'
l'unica informazione che fa capire cosa guardare.
"""
from __future__ import annotations

import time
from typing import Optional

from .injected import ErroreValutazione

#: Gli stati che un'azione di puntatore pretende, nell'ordine in cui Playwright
#: li chiede. `stable` e' il piu' caro (aspetta due fotogrammi) e viene per
#: primo perche' e' anche quello che piu' spesso non e' ancora vero.
STATI_AZIONE = ["visible", "stable", "enabled"]


class ElementoNonAzionabile(TimeoutError):
    """Il ciclo e' scaduto. Il messaggio porta il motivo dell'ULTIMO giro."""


class Azioni:
    def __init__(self, connessione, sessione: str, ciclo, iniettato):
        self.c = connessione
        self.sessione = sessione
        self.ciclo = ciclo
        self.inj = iniettato

    # ── geometria ───────────────────────────────────────────────────────────
    def _punto(self, frame_id: str, elemento: str):
        """Il centro del primo quad, o None se l'elemento non ne ha.

        ⛔ Nessun quad NON e' un errore da propagare: e' "non e' visibile
        adesso", cioe' una condizione RITENTABILE. Alzare qui trasformerebbe un
        elemento che sta per comparire in un guasto.
        """
        r = self.c.manda("Page.getContentQuads",
                         {"frameId": frame_id, "objectId": elemento},
                         sessione=self.sessione, timeout=10) or {}
        quads = r.get("quads") or []
        if not quads:
            return None
        q = quads[0]
        punti = [q["p1"], q["p2"], q["p3"], q["p4"]]
        return (sum(p["x"] for p in punti) / 4.0,
                sum(p["y"] for p in punti) / 4.0)

    # ── il ciclo ────────────────────────────────────────────────────────────
    def _ritenta(self, selettore: str, esegui, *, stati=None,
                 timeout: float = 30.0, frame_id: Optional[str] = None):
        """Risolvi, verifica, agisci, e se qualcosa non torna RICOMINCIA."""
        f = frame_id or self.ciclo.frame_principale
        if f is None:
            raise RuntimeError("nessun frame principale: la pagina non e' pronta")
        stati = STATI_AZIONE if stati is None else stati
        scade = time.monotonic() + timeout
        motivo = "non ho ancora provato"
        giri = 0
        while True:
            giri += 1
            elemento = None
            try:
                # ⛔ DA CAPO a ogni giro. Un handle del giro precedente
                # punterebbe a un nodo che il DOM puo' aver sostituito.
                elemento = self.inj.risolvi(f, selettore)
                if not elemento:
                    motivo = "il selettore non trova niente"
                elif stati:
                    esito = self.inj.stati(f, elemento, stati)
                    if not esito.get("ok"):
                        motivo = "manca %s" % esito.get("manca", "uno stato")
                        elemento_ok = False
                    else:
                        elemento_ok = True
                else:
                    elemento_ok = True

                if elemento and elemento_ok:
                    punto = self._punto(f, elemento)
                    if punto is None:
                        motivo = "l'elemento non ha nessun quad (non e' visibile)"
                    else:
                        return esegui(f, elemento, punto)
            except ErroreValutazione as e:
                # ⛔ "notconnected" vuol dire che il nodo e' sparito FRA la
                # risoluzione e l'uso: e' il caso che il ciclo esiste per
                # assorbire, non un guasto. Tutto il resto risale.
                if "notconnected" not in str(e):
                    raise
                motivo = "il nodo si e' staccato mentre lo usavo"
            finally:
                if elemento:
                    self.inj.libera(f, elemento)

            if time.monotonic() > scade:
                raise ElementoNonAzionabile(
                    "%r non azionabile in %.0fs dopo %d tentativi. Ultimo "
                    "motivo: %s" % (selettore, timeout, giri, motivo))
            time.sleep(0.05)

    # ── le azioni ───────────────────────────────────────────────────────────
    def passa_sopra(self, selettore: str, *, timeout: float = 30.0):
        def esegui(f, elemento, punto):
            self._mouse("mousemove", punto)
            return punto
        return self._ritenta(selettore, esegui, timeout=timeout)

    def clicca(self, selettore: str, *, timeout: float = 30.0, bottone: int = 0):
        def esegui(f, elemento, punto):
            # L'ordine e' quello di un utente: ci si avvicina, si preme, si
            # rilascia. Saltare il mousemove lascia la pagina senza l'hover, e
            # ci sono siti che aprono il menu proprio li'.
            self._mouse("mousemove", punto)
            self._mouse("mousedown", punto, bottone=bottone, premuti=1 << bottone,
                        clic=1)
            self._mouse("mouseup", punto, bottone=bottone, premuti=0, clic=1)
            return punto
        return self._ritenta(selettore, esegui, timeout=timeout)

    def riempi(self, selettore: str, testo: str, *, timeout: float = 30.0):
        """Scrive in un campo.

        ⛔ Non si scrive `element.value = ...` e basta: un sito che ascolta
        `input`/`change` non vedrebbe niente. Lo script iniettato fa la
        mutazione e dice cosa serve dopo - `needsinput` se il testo va
        digitato, `done` se il valore e' stato messo e mancano solo gli eventi.
        E quegli eventi si chiedono a `Page.dispatchTrustedInputEvents`, o
        escono con `isTrusted: false`, che e' il tell misurato in [B175].
        """
        def esegui(f, elemento, punto):
            self.inj.chiama(f, "(injected, el) => injected.focusNode(el, true)",
                            {"objectId": elemento})
            esito = self.inj.chiama(
                f, "(injected, el, v) => injected.fill(el, v)",
                {"objectId": elemento}, testo)
            if isinstance(esito, str) and esito.startswith("error:"):
                raise ErroreValutazione("fill: %s" % esito)
            if esito == "needsinput":
                if testo:
                    self._digita(testo)
                else:
                    # Svuotare un campo non genera tasti: gli eventi vanno
                    # chiesti lo stesso, o la pagina non sa che e' cambiato.
                    self._eventi_fidati(f, elemento, ["input", "change"])
            else:
                self._eventi_fidati(f, elemento, ["input", "change"])
            return esito
        return self._ritenta(selettore, esegui,
                             stati=["visible", "stable", "enabled", "editable"],
                             timeout=timeout)

    # ── i mezzi ─────────────────────────────────────────────────────────────
    def _mouse(self, tipo: str, punto, *, bottone: int = 0, premuti: int = 0,
               clic: Optional[int] = None, modificatori: int = 0):
        p = {"type": tipo, "x": punto[0], "y": punto[1], "button": bottone,
             "buttons": premuti, "modifiers": modificatori}
        if clic is not None:
            p["clickCount"] = clic
        self.c.manda("Page.dispatchMouseEvent", p,
                     sessione=self.sessione, timeout=10)

    def _digita(self, testo: str):
        """⛔ DUE tipi soltanto, e nessuno dei due e' `keypress`.

        Letto in `juggler/content/PageAgent.js` `_dispatchKeyEvent`, non
        dedotto: il ramo conosce `keydown` e `keyup` e su tutto il resto alza
        `Unknown type <x>`. Un `keypress` - che e' quello che verrebbe da
        scrivere per abitudine - fa fallire l'intera digitazione.

        E il carattere lo produce il `keydown`: il TextInputProcessor di Gecko
        lo genera dal `key`. ⛔ Un `keyup` con `text` alza
        `keyup does not support text option`, quindi il campo va messo solo sul
        primo dei due.
        """
        for ch in testo:
            self.c.manda("Page.dispatchKeyEvent",
                         {"type": "keydown", "key": ch, "code": "", "keyCode": 0,
                          "location": 0, "repeat": False, "text": ch},
                         sessione=self.sessione, timeout=10)
            self.c.manda("Page.dispatchKeyEvent",
                         {"type": "keyup", "key": ch, "code": "", "keyCode": 0,
                          "location": 0, "repeat": False},
                         sessione=self.sessione, timeout=10)

    def _eventi_fidati(self, frame_id: str, elemento: str, tipi: list):
        """⛔ Passa dal comando che il NOSTRO fork ha aggiunto a Juggler.

        Dispatchare dallo script iniettato produrrebbe `isTrusted: false`, e la
        mescolanza fra eventi fidati e non sullo stesso form e' un tell piu'
        economico di qualunque segnale singolo: nessuna API di enumerazione, un
        solo `addEventListener`. Misurato in [B175].
        """
        self.c.manda("Page.dispatchTrustedInputEvents",
                     {"frameId": frame_id, "objectId": elemento, "types": tipi},
                     sessione=self.sessione, timeout=10)

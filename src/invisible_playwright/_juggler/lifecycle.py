"""Il ciclo di vita: albero dei frame, navigazioni, load state.

⛔ E' IL PEZZO CHE DECIDE SE LO STACCO STA IN PIEDI, e il motivo e' il modo in
cui sbaglia: non va in crash, va in "funziona diciannove volte su venti". Per
questo qui i commenti dicono PERCHE' una riga e' com'e', non cosa fa.

IL DIFETTO CLASSICO, e la ragione di meta' di questo file: **gli stati vanno
tenuti per NAVIGAZIONE, non per frame.** Se si tengono per frame, un `load`
rimasto dal documento PRECEDENTE soddisfa l'attesa del successivo, e la
`goto()` torna prima che la pagina esista. E' l'errore che non si vede quasi
mai, perche' serve che i due eventi arrivino nell'ordine sbagliato.

LA CORRELAZIONE, che il protocollo NON regala. `Page.eventFired` porta
`frameId` e `name` (`load` o `DOMContentLoaded`) e **non porta il
navigationId**. Quindi l'appartenenza si stabilisce per ORDINE: dopo il
`navigationCommitted` della navigazione N, il primo `load` di quel frame e' di
N. E' cio' che rende obbligatorio azzerare gli stati su `navigationStarted`.

LE QUATTRO ATTESE, e quale evento le chiude:

    commit             Page.navigationCommitted
    domcontentloaded   Page.eventFired name=DOMContentLoaded
    load               Page.eventFired name=load
    networkidle        zero richieste in volo per QUIETE secondi

⛔ `sameDocumentNavigation` NON azzera niente: e' lo stesso documento, e un
push di history non ricarica la pagina. Trattarlo come una navigazione fa
aspettare un `load` che non arrivera' mai.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

#: Quanto silenzio serve perche' la rete sia "ferma". E' il valore di
#: Playwright: piu' corto prende una pausa fra due richieste per una quiete.
QUIETE = 0.5

STATI = ("commit", "domcontentloaded", "load", "networkidle")


class ErroreNavigazione(RuntimeError):
    """La navigazione e' stata abortita dal browser, col suo testo."""


class Frame:
    def __init__(self, frame_id: str, padre: Optional[str]):
        self.id = frame_id
        self.padre = padre
        self.url = ""
        #: la navigazione corrente, e SOLO i suoi stati
        self.navigazione: Optional[str] = None
        self.stati: set = set()
        #: le navigazioni abortite, col loro testo, per chi le stava aspettando
        self.abortite: dict = {}


class CicloDiVita:
    """Segue una pagina sola. Si aggancia agli eventi di una `Connessione`."""

    def __init__(self, connessione, sessione: str):
        self.c = connessione
        self.sessione = sessione
        self.frames: dict = {}
        self.frame_principale: Optional[str] = None
        self.pronta = False
        self._in_volo = 0
        self._ultimo_movimento = time.monotonic()
        self._cv = threading.Condition()
        precedente = connessione.su_evento

        def instrada(metodo, params, sessione_evento):
            if sessione_evento == self.sessione:
                self._evento(metodo, params)
            # ⛔ Non si INGOIA l'evento: chi era agganciato prima resta
            # agganciato. Un ciclo di vita che ruba gli eventi rende muto
            # qualunque altro osservatore, e il guasto sarebbe silenzioso.
            precedente(metodo, params, sessione_evento)

        connessione.su_evento = instrada

    # ── ingresso degli eventi ───────────────────────────────────────────────
    def _evento(self, metodo: str, p: dict) -> None:
        with self._cv:
            f = self._applica(metodo, p)
            if f is not None or metodo.startswith("Network."):
                self._cv.notify_all()

    def _applica(self, metodo: str, p: dict):
        if metodo == "Page.ready":
            self.pronta = True
            return None

        if metodo == "Page.frameAttached":
            fid = p["frameId"]
            self.frames[fid] = Frame(fid, p.get("parentFrameId"))
            if p.get("parentFrameId") is None:
                self.frame_principale = fid
            return self.frames[fid]

        if metodo == "Page.frameDetached":
            fid = p["frameId"]
            # Si toglie il sottoalbero, non il solo nodo: un figlio orfano
            # resterebbe a rispondere per un frame che non esiste piu'.
            for x in [k for k, v in self.frames.items()
                      if k == fid or self._discende(k, fid)]:
                self.frames.pop(x, None)
            return None

        if metodo == "Page.navigationStarted":
            f = self._frame(p["frameId"])
            f.navigazione = p["navigationId"]
            # ⛔ QUI sta la correttezza di tutto il file: gli stati del
            # documento precedente NON valgono per questo.
            f.stati = set()
            return f

        if metodo == "Page.navigationCommitted":
            f = self._frame(p["frameId"])
            nav = p.get("navigationId")
            if nav is not None:
                f.navigazione = nav
            f.url = p.get("url", f.url)
            f.stati.add("commit")
            return f

        if metodo == "Page.navigationAborted":
            f = self._frame(p["frameId"])
            f.abortite[p["navigationId"]] = p.get("errorText", "abortita")
            return f

        if metodo == "Page.sameDocumentNavigation":
            f = self._frame(p["frameId"])
            f.url = p.get("url", f.url)
            # ⛔ Nessun azzeramento: e' lo stesso documento.
            return f

        if metodo == "Page.eventFired":
            f = self._frame(p["frameId"])
            nome = p.get("name")
            if nome == "load":
                f.stati.add("load")
                # `load` implica `domcontentloaded`: se per un ordine di eventi
                # inatteso il secondo non fosse arrivato, chi lo aspetta
                # resterebbe fermo davanti a una pagina gia' carica.
                f.stati.add("domcontentloaded")
            elif nome == "DOMContentLoaded":
                f.stati.add("domcontentloaded")
            return f

        if metodo == "Network.requestWillBeSent":
            self._in_volo += 1
            self._ultimo_movimento = time.monotonic()
        elif metodo in ("Network.requestFinished", "Network.requestFailed"):
            # Non si scende sotto zero: una risposta senza la sua richiesta
            # arriva davvero, per esempio per un caricamento cominciato prima
            # che ci agganciassimo, e un contatore negativo renderebbe
            # `networkidle` irraggiungibile per sempre.
            self._in_volo = max(0, self._in_volo - 1)
            self._ultimo_movimento = time.monotonic()
        return None

    def _discende(self, fid: str, avo: str) -> bool:
        visto = set()
        cur = self.frames.get(fid)
        while cur and cur.padre and cur.padre not in visto:
            if cur.padre == avo:
                return True
            visto.add(cur.padre)
            cur = self.frames.get(cur.padre)
        return False

    def _frame(self, fid: str) -> Frame:
        # Un evento puo' nominare un frame che non abbiamo visto attaccare (ci
        # siamo agganciati a pagina gia' viva). Si crea invece di perderlo.
        if fid not in self.frames:
            self.frames[fid] = Frame(fid, None)
            if self.frame_principale is None:
                self.frame_principale = fid
        return self.frames[fid]

    # ── attese ──────────────────────────────────────────────────────────────
    def _raggiunto(self, f: Frame, stato: str) -> bool:
        if stato == "networkidle":
            return (self._in_volo == 0
                    and time.monotonic() - self._ultimo_movimento >= QUIETE)
        return stato in f.stati

    def aspetta_stato(self, frame_id: str, stato: str, *,
                      navigazione: Optional[str] = None,
                      timeout: float = 30.0) -> None:
        if stato not in STATI:
            raise ValueError("stato sconosciuto: %r (i quattro sono %s)"
                             % (stato, ", ".join(STATI)))
        scade = time.monotonic() + timeout
        with self._cv:
            while True:
                f = self.frames.get(frame_id)
                if f is not None:
                    if navigazione and navigazione in f.abortite:
                        raise ErroreNavigazione(f.abortite[navigazione])
                    # ⛔ AZZERARE GLI STATI SU `navigationStarted` NON BASTA, e
                    # questo e' il difetto vero misurato il 2026-08-27.
                    #
                    # `Page.navigate` risponde con il navigationId PRIMA che
                    # `navigationStarted` sia arrivato. In quella finestra il
                    # frame porta ancora gli stati del documento precedente -
                    # `about:blank` ne ha gia' commit, domcontentloaded e load -
                    # e chi aspetta `commit` lo trova subito e torna. Misurato:
                    # la prima `naviga(aspetta="commit")` tornava in 0,01s con
                    # `url=about:blank`, cioe' prima ancora di partire.
                    #
                    # Il rimedio non e' aspettare un attimo: e' pretendere che
                    # gli stati appartengano ALLA NOSTRA navigazione. Finche'
                    # `f.navigazione` e' un'altra, quello che vediamo non e'
                    # nostro, qualunque cosa dica.
                    if navigazione is not None and f.navigazione != navigazione:
                        pass
                    elif self._raggiunto(f, stato):
                        return
                resta = scade - time.monotonic()
                if resta <= 0:
                    if f is None:
                        dove = "il frame non esiste"
                    elif navigazione is not None and f.navigazione != navigazione:
                        # Il messaggio deve dire QUESTO, perche' e' il caso in
                        # cui gli stati ci sono ma non sono nostri, e senza la
                        # riga sembrerebbe che il browser non risponda.
                        dove = ("la navigazione corrente e' %s, non la nostra %s"
                                % (f.navigazione, navigazione))
                    else:
                        dove = "stati raggiunti: %s" % (sorted(f.stati) or "nessuno")
                    raise TimeoutError(
                        "%s non raggiunto in %.0fs (%s, richieste in volo: %d)"
                        % (stato, timeout, dove, self._in_volo))
                # ⛔ Con `networkidle` non si dorme fino al prossimo evento: la
                # condizione si avvera per SCADENZA DI SILENZIO, cioe' quando
                # NON succede niente. Aspettare un notify li' significherebbe
                # aspettare per sempre proprio nel caso che deve riuscire.
                self._cv.wait(min(resta, 0.05 if stato == "networkidle" else resta))

    # ── navigazione ─────────────────────────────────────────────────────────
    def naviga(self, url: str, *, frame_id: Optional[str] = None,
               aspetta: str = "load", timeout: float = 30.0,
               referer: Optional[str] = None) -> dict:
        fid = frame_id or self.frame_principale
        if fid is None:
            raise RuntimeError("nessun frame: la pagina non ha ancora "
                               "annunciato il suo frame principale")
        params = {"frameId": fid, "url": url}
        if referer:
            params["referer"] = referer
        esito = self.c.manda("Page.navigate", params,
                             sessione=self.sessione, timeout=timeout) or {}
        nav = esito.get("navigationId")

        # ⛔ `navigationId` NULLO non e' un errore: il protocollo lo dichiara
        # `Nullable`, e capita quando la navigazione non crea un documento
        # nuovo - un ancoraggio, o la stessa URL. Non c'e' nessun `load` da
        # aspettare, e aspettarlo sarebbe un timeout su una cosa riuscita.
        if nav is None:
            return {"navigationId": None, "url": url}

        self.aspetta_stato(fid, aspetta, navigazione=nav, timeout=timeout)
        return {"navigationId": nav, "url": self.frames[fid].url}

    # ── ispezione ───────────────────────────────────────────────────────────
    def albero(self) -> dict:
        return {fid: {"padre": f.padre, "url": f.url,
                      "stati": sorted(f.stati), "navigazione": f.navigazione}
                for fid, f in self.frames.items()}

    @property
    def richieste_in_volo(self) -> int:
        return self._in_volo

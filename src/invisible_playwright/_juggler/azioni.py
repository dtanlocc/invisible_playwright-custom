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
from .tastiera import MASCHERA_BOTTONI, Tastiera, TastoSconosciuto

#: Gli stati che un'azione di puntatore pretende, nell'ordine in cui Playwright
#: li chiede. `stable` e' il piu' caro (aspetta due fotogrammi) e viene per
#: primo perche' e' anche quello che piu' spesso non e' ancora vero.
STATI_AZIONE = ["visible", "stable", "enabled"]


class ElementoNonAzionabile(TimeoutError):
    """Il ciclo e' scaduto. Il messaggio porta il motivo dell'ULTIMO giro."""


class BersaglioSbagliato(RuntimeError):
    """L'evento sarebbe finito su un ALTRO elemento. Condizione RITENTABILE.

    ⛔ E' la finestra che il resto del ciclo non chiude, ed e' stata MISURATA,
    non temuta. Fra il controllo di azionabilita' e l'evento passano un paio di
    comandi; se in quel mezzo il layout si muove - un banner che compare, un
    font che finisce di caricare, un `setTimeout` che sposta la pagina - il
    punto calcolato prima non appartiene piu' all'elemento voluto.

    Il caso del 2026-08-27: una pagina che a 1200 ms rende visibile un blocco
    piu' in alto. `doppio_clic` riusciva, la pagina non vedeva NESSUN
    `dblclick`, e sulla stessa pagina senza quel timer lo stesso codice
    funzionava. Nessun errore da nessuna parte: il click era finito diciannove
    pixel piu' su.
    """


def _normalizza_opzioni(opzioni) -> list:
    """Una stringa diventa `{"valueOrLabel": ...}`, e NON e' un dettaglio.

    ⛔ IL FILTRO DELLO SCRIPT INIETTATO PARTE DA `matches = true` e lo
    restringe SOLO se il criterio porta uno fra `valueOrLabel`, `value`,
    `label` o `index`. Una stringa nuda non ne ha nessuno, quindi ogni opzione
    corrisponde e viene scelta **la prima**.

    Misurato il 2026-08-27 su un `<select>` con A/a e B/b: `["b"]` ha risposto
    `['a']` lasciando il valore a `a`. Nessun errore, nessuna eccezione,
    l'operazione riuscita e l'opzione sbagliata - che e' peggio di un rifiuto,
    perche' il guasto emerge sulla pagina dopo. Con `[{"value": "b"}]` la stessa
    chiamata risponde `['b']`.
    """
    fuori = []
    for o in opzioni:
        fuori.append({"valueOrLabel": o} if isinstance(o, str) else dict(o))
    return fuori


class Azioni:
    def __init__(self, connessione, sessione: str, ciclo, iniettato):
        self.c = connessione
        self.sessione = sessione
        self.ciclo = ciclo
        self.inj = iniettato
        #: ⛔ UNA SOLA tastiera per pagina, ed e' il punto: tiene lo stato dei
        #: modificatori. Costruirne una per azione perderebbe "Shift e' giu'"
        #: fra un `giu` e il tasto successivo, e `Shift+a` scriverebbe `a`.
        self.tastiera = Tastiera(connessione, sessione)
        #: L'ultima posizione del puntatore. Serve per la rotella e per il
        #: trascinamento, che partono da dove il mouse E' - non da 0,0.
        self.dove = (0.0, 0.0)

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
            except BersaglioSbagliato as e:
                # ⛔ Anche questa e' una condizione del MONDO, non un guasto: la
                # pagina si e' mossa fra il controllo e l'evento. Si ricomincia,
                # e il punto viene ricalcolato sulla nuova geometria.
                motivo = "l'evento sarebbe finito altrove (%s)" % e
            finally:
                if elemento:
                    self.inj.libera(f, elemento)

            if time.monotonic() > scade:
                raise ElementoNonAzionabile(
                    "%r non azionabile in %.0fs dopo %d tentativi. Ultimo "
                    "motivo: %s" % (selettore, timeout, giri, motivo))
            time.sleep(0.05)

    # ── il bersaglio ────────────────────────────────────────────────────────
    def _con_bersaglio(self, f, elemento, punto, azione, agisci):
        """Agisce SOLO se l'evento finisce davvero sull'elemento voluto.

        ⛔ NON e' un controllo in piu' prima di agire: e' un intercettore
        installato PER TUTTA la durata dell'azione. La differenza conta, perche'
        un controllo prima lascia aperta esattamente la finestra che questo
        chiude - la pagina puo' muoversi fra il controllo e l'evento. Qui il
        listener guarda l'evento MENTRE arriva, e se il punto non appartiene
        all'elemento voluto lo BLOCCA e lo dice.

        E' il meccanismo del driver (`setupHitTargetInterceptor`), quindi non
        aggiunge nessuna superficie nuova: i listener che lo servono sono gia'
        installati, **nel mondo di utilita'** dopo la correzione di
        `31-client-fork.md` §3.9. Nel mondo della pagina sarebbero contabili.
        """
        h = self.inj.chiama(
            f,
            "(injected, el, a, p) => {"
            "  const r = injected.setupHitTargetInterceptor(el, a, p, false);"
            "  return typeof r === 'string' ? {errore: r} : {fermo: r.stop}; }",
            {"objectId": elemento}, azione,
            {"x": punto[0], "y": punto[1]}, per_valore=False)
        try:
            guasto = self.inj.chiama(f, "(injected, h) => h.errore || ''",
                                     {"objectId": h})
            if guasto:
                raise BersaglioSbagliato(guasto)
            esito = agisci()
            # ⛔ `stop()` torna `"done"` OPPURE un oggetto che descrive cosa e'
            # stato colpito davvero. Leggerlo come booleano direbbe sempre di
            # si', che e' lo stesso difetto di `elementState`.
            finito = self.inj.chiama(
                f, "(injected, h) => { const r = h.fermo ? h.fermo() : 'done';"
                   " return typeof r === 'string' ? r : JSON.stringify(r); }",
                {"objectId": h})
            if finito != "done":
                raise BersaglioSbagliato(finito)
            return esito
        finally:
            self.inj.libera(f, h)

    # ── le azioni ───────────────────────────────────────────────────────────
    def passa_sopra(self, selettore: str, *, timeout: float = 30.0):
        def esegui(f, elemento, punto):
            return self._con_bersaglio(
                f, elemento, punto, "hover",
                lambda: self._mouse("mousemove", punto) or punto)
        return self._ritenta(selettore, esegui, timeout=timeout)

    def clicca(self, selettore: str, *, timeout: float = 30.0, bottone: int = 0,
               volte: int = 1):
        def esegui(f, elemento, punto):
            def agisci():
                # L'ordine e' quello di un utente: ci si avvicina, si preme, si
                # rilascia. Saltare il mousemove lascia la pagina senza
                # l'hover, e ci sono siti che aprono il menu proprio li'.
                self._mouse("mousemove", punto)
                self._clic_qui(punto, bottone=bottone, volte=volte)
                return punto
            return self._con_bersaglio(f, elemento, punto, "mouse", agisci)
        return self._ritenta(selettore, esegui, timeout=timeout)

    def doppio_clic(self, selettore: str, *, timeout: float = 30.0,
                    bottone: int = 0):
        """⛔ NON sono due `clicca` di fila: il secondo deve portare
        `clickCount: 2`, ed e' quel campo - non l'intervallo fra i due - che fa
        nascere l'evento `dblclick`. Due click con `clickCount: 1` producono due
        `click` e nessun `dblclick`, che e' un guasto silenzioso: l'azione
        riesce e il gestore del sito non parte mai."""
        return self.clicca(selettore, timeout=timeout, bottone=bottone, volte=2)

    def spunta(self, selettore: str, *, timeout: float = 30.0):
        return self._imposta_spunta(selettore, True, timeout=timeout)

    def togli_spunta(self, selettore: str, *, timeout: float = 30.0):
        return self._imposta_spunta(selettore, False, timeout=timeout)

    def _imposta_spunta(self, selettore: str, voluto: bool, *, timeout: float):
        """`check` / `uncheck`.

        ⛔ Si CONTROLLA PRIMA, e si ricontrolla dopo. Cliccare senza guardare
        inverte una casella gia' giusta - e' il difetto ovvio - ma il secondo
        controllo e' quello che conta: un `<label>` che intercetta il click, o
        un gestore che rimette il valore, fanno riuscire l'azione e lasciano lo
        stato sbagliato. Senza il ricontrollo il guasto emerge molto dopo,
        altrove.
        """
        def esegui(f, elemento, punto):
            stato = "checked" if voluto else "unchecked"
            if self.inj.stato(f, elemento, stato):
                return "gia' cosi'"

            def agisci():
                self._mouse("mousemove", punto)
                self._clic_qui(punto)
            # ⛔ PASSA DALL'INTERCETTORE come `clicca`, e non e' una rifinitura:
            # la prima stesura chiamava `_clic_qui` diretto e falliva sulla
            # stessa pagina che sposta il layout a 1200 ms. Un solo posto sa
            # come si clicca; due lo sanno finche' uno dei due non impara
            # qualcosa che l'altro non sa.
            self._con_bersaglio(f, elemento, punto, "mouse", agisci)
            if not self.inj.stato(f, elemento, stato):
                raise ErroreValutazione(
                    "cliccato ma la casella e' rimasta %s: qualcuno ha "
                    "intercettato il click o ha rimesso il valore"
                    % ("non spuntata" if voluto else "spuntata"))
            return stato
        return self._ritenta(selettore, esegui, timeout=timeout)

    def metti_a_fuoco(self, selettore: str, *, timeout: float = 30.0):
        """⛔ NON pretende `visible`: `focus()` funziona su un elemento fuori
        schermo, e imporre gli stati del puntatore farebbe scadere un'azione
        che sarebbe riuscita. Playwright fa lo stesso."""
        def esegui(f, elemento, punto):
            return self.inj.chiama(
                f, "(injected, el) => injected.focusNode(el, true)",
                {"objectId": elemento})
        return self._ritenta(selettore, esegui, stati=[], timeout=timeout)

    def togli_fuoco(self, selettore: str, *, timeout: float = 30.0):
        def esegui(f, elemento, punto):
            return self.inj.chiama(
                f,
                "(injected, el) => { if (!el.isConnected) return "
                "'error:notconnected'; el.blur(); return 'done'; }",
                {"objectId": elemento})
        return self._ritenta(selettore, esegui, stati=[], timeout=timeout)

    def seleziona_testo(self, selettore: str, *, timeout: float = 30.0):
        def esegui(f, elemento, punto):
            r = self.inj.chiama(f, "(injected, el) => injected.selectText(el)",
                                {"objectId": elemento})
            if isinstance(r, str) and r.startswith("error:"):
                raise ErroreValutazione("selectText: %s" % r)
            return r
        return self._ritenta(selettore, esegui, stati=["visible"],
                             timeout=timeout)

    def scegli_opzioni(self, selettore: str, opzioni, *, timeout: float = 30.0):
        """`select_option`. Le opzioni si danno per valore, etichetta o indice.

        ⛔ E gli eventi `input`/`change` si chiedono al comando FIDATO dopo la
        mutazione, come per `riempi`: senza, un `<select>` cambia valore e la
        pagina non lo sa - e se li dispatchasse lo script iniettato uscirebbero
        con `isTrusted: false`, che e' [B175].
        """
        voluti = _normalizza_opzioni(opzioni)

        def esegui(f, elemento, punto):
            r = self.inj.chiama(
                f, "(injected, el, o) => injected.selectOptions(el, o)",
                {"objectId": elemento}, voluti)
            if isinstance(r, str) and r.startswith("error:"):
                raise ErroreValutazione("selectOptions: %s" % r)
            self._eventi_fidati(f, elemento, ["input", "change"])
            return r
        return self._ritenta(selettore, esegui,
                             stati=["visible", "stable", "enabled"],
                             timeout=timeout)

    def manda_evento(self, selettore: str, tipo: str, dettagli=None, *,
                     timeout: float = 30.0):
        """`dispatch_event`.

        ⛔ Questo e' l'UNICO punto del file in cui un evento esce NON fidato, e
        va detto invece che scoperto: lo costruisce lo script iniettato, quindi
        `isTrusted` e' falso. E' cio' che l'API di Playwright promette - serve
        proprio a fabbricare un evento arbitrario - ma non e' un modo di
        simulare un utente: per quello ci sono `clicca` e `digita_su`, che
        passano dai comandi del browser.
        """
        def esegui(f, elemento, punto):
            return self.inj.chiama(
                f, "(injected, el, t, d) => injected.dispatchEvent(el, t, d)",
                {"objectId": elemento}, tipo, dettagli or {})
        return self._ritenta(selettore, esegui, stati=[], timeout=timeout)

    def premi_su(self, selettore: str, tasto: str, *, timeout: float = 30.0):
        """`press`: mette a fuoco e preme, con i modificatori del nome."""
        def esegui(f, elemento, punto):
            self.inj.chiama(f, "(injected, el) => injected.focusNode(el, true)",
                            {"objectId": elemento})
            self.tastiera.premi(tasto)
            return tasto
        return self._ritenta(selettore, esegui,
                             stati=["visible", "stable", "enabled"],
                             timeout=timeout)

    def digita_su(self, selettore: str, testo: str, *, timeout: float = 30.0,
                  ritardo: float = 0.0):
        """`type`: un tasto per carattere, SENZA svuotare prima.

        ⛔ Non e' `riempi`: quello sostituisce il contenuto, questo lo
        aggiunge. Scambiarli e' il modo piu' facile di scrivere `pippopluto` in
        un campo che doveva contenere `pluto`.
        """
        def esegui(f, elemento, punto):
            self.inj.chiama(f, "(injected, el) => injected.focusNode(el, true)",
                            {"objectId": elemento})
            self.tastiera.digita(testo, ritardo=ritardo)
            return testo
        return self._ritenta(selettore, esegui,
                             stati=["visible", "stable", "enabled"],
                             timeout=timeout)

    def imposta_file(self, selettore: str, percorsi, *, timeout: float = 30.0):
        """`set_input_files`. I percorsi sono ASSOLUTI e li risolve il browser.

        ⛔ Passa da `Page.setFileInputFiles` e non dallo script iniettato: una
        pagina non puo' costruire un `FileList`, e provarci lascerebbe l'input
        vuoto senza errore.
        """
        def esegui(f, elemento, punto):
            self.c.manda("Page.setFileInputFiles",
                         {"frameId": f, "objectId": elemento,
                          "files": [str(p) for p in percorsi]},
                         sessione=self.sessione, timeout=30)
            return list(percorsi)
        return self._ritenta(selettore, esegui, stati=[], timeout=timeout)

    def tocca(self, selettore: str, *, timeout: float = 30.0):
        """`tap`. ⛔ Richiede che il contesto abbia il tocco ACCESO: senza,
        l'evento parte e la pagina non ha `ontouchstart`, quindi non lo
        ascolta - riesce e non fa niente. Il tocco si accende con
        `Browser.setTouchOverride`, che e' un'operazione di contesto."""
        def esegui(f, elemento, punto):
            self.c.manda("Page.dispatchTapEvent",
                         {"x": punto[0], "y": punto[1],
                          "modifiers": self.tastiera.maschera()},
                         sessione=self.sessione, timeout=10)
            return punto
        return self._ritenta(selettore, esegui, timeout=timeout)

    def trascina(self, da: str, a: str, *, timeout: float = 30.0):
        """`drag_and_drop`, in quattro tempi.

        ⛔ IL PRIMO `mousemove` DOPO IL `mousedown` NON SI SALTA. Gecko fa
        nascere il trascinamento da un movimento con il bottone premuto: premi
        e rilascia sul bersaglio, e hai fatto due click. E i due estremi si
        risolvono SEPARATAMENTE, ciascuno col suo ciclo di ritentativo, perche'
        prendere il secondo punto prima di aver premuto il primo lo misura su
        una pagina che sta per cambiare.
        """
        partenza = self._ritenta(da, lambda f, el, p: p, timeout=timeout)
        self._mouse("mousemove", partenza)
        self._mouse("mousedown", partenza, premuti=MASCHERA_BOTTONI[0], clic=1)

        def esegui(f, elemento, punto):
            # Due movimenti: uno fa nascere il trascinamento, il secondo lo
            # porta sul bersaglio. Con uno solo Gecko a volte non lo avvia.
            self._mouse("mousemove", punto, premuti=MASCHERA_BOTTONI[0])
            self._mouse("mousemove", punto, premuti=MASCHERA_BOTTONI[0])
            self._mouse("mouseup", punto, premuti=0, clic=1)
            return punto
        try:
            return self._ritenta(a, esegui, timeout=timeout)
        except BaseException:
            # ⛔ Un bottone lasciato giu' avvelena OGNI azione successiva: il
            # `buttons` di ogni evento dopo direbbe "premuto".
            self._mouse("mouseup", partenza, premuti=0, clic=1)
            raise

    # ── il puntatore, per coordinate ────────────────────────────────────────
    def muovi(self, x: float, y: float, *, passi: int = 1) -> None:
        """`mouse.move`. Con `passi > 1` interpola, come fa Playwright."""
        x0, y0 = self.dove
        for i in range(1, max(1, passi) + 1):
            self._mouse("mousemove",
                        (x0 + (x - x0) * i / passi, y0 + (y - y0) * i / passi))

    def giu(self, *, bottone: int = 0, volte: int = 1) -> None:
        self._mouse("mousedown", self.dove, bottone=bottone,
                    premuti=MASCHERA_BOTTONI[bottone], clic=volte)

    def su(self, *, bottone: int = 0, volte: int = 1) -> None:
        self._mouse("mouseup", self.dove, bottone=bottone, premuti=0,
                    clic=volte)

    def clic(self, x: float, y: float, *, bottone: int = 0, volte: int = 1):
        self.muovi(x, y)
        self._clic_qui((x, y), bottone=bottone, volte=volte)

    def rotella(self, dx: float, dy: float) -> None:
        """`mouse.wheel`, dove il puntatore E' - non a 0,0."""
        self.c.manda("Page.dispatchWheelEvent",
                     {"x": self.dove[0], "y": self.dove[1], "deltaX": dx,
                      "deltaY": dy, "deltaZ": 0,
                      "modifiers": self.tastiera.maschera()},
                     sessione=self.sessione, timeout=10)

    def _clic_qui(self, punto, *, bottone: int = 0, volte: int = 1) -> None:
        """⛔ `clickCount` CRESCE fra i colpi: 1, poi 2. E' quel campo a far
        nascere `dblclick`, non l'intervallo. E il `buttons` del rilascio e'
        zero, perche' descrive cosa resta premuto DOPO."""
        for n in range(1, volte + 1):
            self._mouse("mousedown", punto, bottone=bottone,
                        premuti=MASCHERA_BOTTONI[bottone], clic=n)
            self._mouse("mouseup", punto, bottone=bottone, premuti=0, clic=n)

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
             "buttons": premuti,
             # I modificatori vengono dalla TASTIERA se non li impone il
             # chiamante: un click con Shift giu' deve dirlo, o la pagina vede
             # un click normale mentre l'utente ne stava facendo un altro.
             "modifiers": modificatori or self.tastiera.maschera()}
        if clic is not None:
            p["clickCount"] = clic
        self.c.manda("Page.dispatchMouseEvent", p,
                     sessione=self.sessione, timeout=10)
        self.dove = (punto[0], punto[1])

    def _digita(self, testo: str):
        """La digitazione carattere per carattere.

        ⛔ E' un rinvio alla tastiera, e la ragione per cui non e' piu' scritto
        qui e' un difetto misurato: questa funzione mandava `code: ""` e
        `keyCode: 0` per OGNI carattere. L'evento parte lo stesso, il testo
        compare nel campo, l'azione riesce e i test passano - mentre la pagina
        legge un `event.code` vuoto su un tasto che ogni Firefox vero nomina.
        Il layout vero sta in `keylayout.py`, generato dal bundle.

        ⛔ E i caratteri che il layout US non ha (un ideogramma, un'emoji) non
        si DIGITANO: `tastiera.digita` li rifiuta e vanno a `Page.insertText`.
        Fingere una pressione per un tasto che non esiste e' esattamente il
        difetto di sopra, in una forma piu' difficile da vedere.
        """
        try:
            self.tastiera.digita(testo)
        except TastoSconosciuto:
            # ⛔ SOLO questa eccezione, e non `Exception`: un errore di
            # trasporto a meta' digitazione verrebbe inghiottito e il testo
            # reinserito da capo, raddoppiando cio' che era gia' entrato.
            self.tastiera.inserisci(testo)

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

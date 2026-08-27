"""La tastiera: dal nome di un tasto ai quattro campi che Juggler pretende.

⛔ QUESTO FILE ESISTE PERCHE' `Page.dispatchKeyEvent` NON PERDONA UN CAMPO
SBAGLIATO IN SILENZIO - lo perdona TROPPO. Vuole `key`, `code`, `keyCode` e
`location` insieme, e se `code` e' vuoto e `keyCode` e' zero l'evento parte lo
stesso: il carattere compare nel campo, l'azione riesce, i test passano, e la
pagina legge `event.code === ""` su un tasto che su ogni Firefox vero ha un nome
fisico. E' un tell che vive nei campi che nessuno guarda perche' l'azione ha
funzionato.

La prima stesura di `_digita` in `azioni.py` mandava esattamente cosi':
`code: ""`, `keyCode: 0`, per ogni carattere.

**TRE DETTAGLI LETTI NEL CODICE DEL DRIVER, non dedotti** (`coreBundle.js`,
`RawKeyboardImpl3`), e ognuno cambia i byte che escono:

1. Il campo `keyCode` porta **`keyCodeWithoutLocation`**, non `keyCode`. Sono
   diversi proprio sui tasti che esistono due volte: `ShiftLeft` ha `keyCode`
   160 e `keyCodeWithoutLocation` 16, e 16 e' quello che un Firefox vero mette
   nell'evento.
2. Per Invio il `text` va messo a **stringa vuota**, non a `"\\r"`: il carattere
   lo genera Gecko. Mandarlo esplicito inserisce due volte.
3. Il `keyup` non porta `text` MAI. Con `text` Juggler alza
   `keyup does not support text option` e la digitazione muore a meta'.

**E il layout non e' qui**: sta in `keylayout.py`, GENERATO dal bundle da
`scripts/gen_key_layout.py`. Qui c'e' solo come si risolve un nome, che e'
l'algoritmo di `buildLayoutClosure` letto nel driver e riscritto.
"""
from __future__ import annotations

from typing import Optional

from .keylayout import LAYOUT

#: I quattro che contano come modificatori, e nell'ordine del driver.
MODIFICATORI = ("Alt", "Control", "Meta", "Shift")

#: ⛔ La maschera di Firefox NON e' quella di Gecko e non e' `1 << indice`:
#: letta in `toModifiersMask2` del bundle. Juggler la traduce lui nei
#: `nsIDOMWindowUtils.MODIFIER_*`, quindi qui vanno questi numeri.
MASCHERA_MODIFICATORI = {"Alt": 1, "Control": 2, "Shift": 4, "Meta": 8}

#: ⛔ E questa e' ANCORA un'altra codifica, per il campo `buttons`: letta in
#: `toButtonsMask2`. **Destro e centrale sono scambiati** rispetto al numero del
#: bottone (`button`: 0 sinistro, 1 centrale, 2 destro). Scrivere `1 << bottone`
#: sembra giusto, da' 1 per il sinistro - e sbaglia gli altri due.
MASCHERA_BOTTONI = {0: 1, 1: 4, 2: 2}

#: Gli alias del driver: un nome comodo che punta a un tasto fisico.
ALIAS = {"ShiftLeft": ["Shift"], "ControlLeft": ["Control"],
         "AltLeft": ["Alt"], "MetaLeft": ["Meta"], "Enter": ["\n", "\r"]}

#: ⛔ Tre tasti su cui Firefox non e' d'accordo col layout generico. Letti in
#: `kFirefoxKeyOverrides`: senza, `AudioVolumeMute` esce con il `code` sbagliato.
CORREZIONI_FIREFOX = {
    "AudioVolumeMute": {"code": "VolumeMute", "keyCodeWithoutLocation": 181},
    "AudioVolumeDown": {"code": "VolumeDown", "keyCodeWithoutLocation": 182},
    "AudioVolumeUp": {"code": "VolumeUp", "keyCodeWithoutLocation": 183},
}


class TastoSconosciuto(ValueError):
    """Il nome non sta nel layout. ⛔ Si RIFIUTA invece di inventare un evento
    vuoto: un `keyCode: 0` non fallisce, mente."""


def _chiusura() -> dict:
    """Il dizionario nome -> descrizione, con la stessa forma del driver.

    Un tasto e' raggiungibile per `code` (`KeyA`), per `key` se e' un solo
    carattere (`a`), per il suo shiftato (`A`), e per alias (`Shift`).
    ⛔ Un tasto con `location` NON entra per `key`: `NumpadEnter` non deve
    rispondere al nome `Enter`, o `press("Enter")` finirebbe sul tastierino.
    """
    fuori: dict = {}
    for code, d in LAYOUT.items():
        chiave = d.get("key") or ""
        descr = {
            "key": chiave,
            "keyCode": d.get("keyCode") or 0,
            "keyCodeWithoutLocation": d.get("keyCodeWithoutLocation")
                                      or d.get("keyCode") or 0,
            "code": code,
            "text": d.get("text") or "",
            "location": d.get("location") or 0,
        }
        if len(chiave) == 1:
            descr["text"] = chiave
        shiftato = None
        if d.get("shiftKey"):
            shiftato = dict(descr)
            shiftato["key"] = d["shiftKey"]
            shiftato["text"] = d["shiftKey"]
            if d.get("shiftKeyCode"):
                shiftato["keyCode"] = d["shiftKeyCode"]
        fuori[code] = dict(descr, shifted=shiftato)
        for alias in ALIAS.get(code, []):
            fuori[alias] = descr
        if d.get("location"):
            continue
        if len(descr["key"]) == 1:
            fuori.setdefault(descr["key"], descr)
        if shiftato:
            fuori.setdefault(shiftato["key"], dict(shiftato, shifted=None))
    return fuori


CHIUSURA = _chiusura()


class Tastiera:
    """Lo stato dei modificatori e dei tasti premuti, piu' i quattro verbi.

    Lo STATO e' la ragione per cui questa e' una classe e non tre funzioni:
    `press("Shift+a")` deve mandare `A` e non `a`, e per saperlo deve ricordare
    che Shift e' giu' fra il keydown di Shift e quello di `a`.
    """

    def __init__(self, connessione, sessione: str):
        self.c = connessione
        self.sessione = sessione
        self.modificatori: set = set()
        self.premuti: set = set()

    # ── la risoluzione ──────────────────────────────────────────────────────
    def descrivi(self, tasto: str) -> dict:
        nome = "Control" if tasto == "ControlOrMeta" else tasto
        d = CHIUSURA.get(nome)
        if d is None:
            raise TastoSconosciuto(
                "tasto sconosciuto: %r. I nomi validi sono i `code` del layout "
                "(KeyA, Digit1, Enter), un carattere singolo, o un alias "
                "(Shift, Control, Alt, Meta)." % tasto)
        if "Shift" in self.modificatori and d.get("shifted"):
            d = d["shifted"]
        d = dict(d)
        # ⛔ Con un modificatore diverso da Shift premuto, il testo NON esce:
        # `Control+a` non scrive una "a" nel campo. Letto nel driver, e senza
        # questa riga un `press("Control+a")` inserirebbe il carattere.
        if len(self.modificatori) > 1 or \
                (len(self.modificatori) == 1 and "Shift" not in self.modificatori):
            d["text"] = ""
        d.update(CORREZIONI_FIREFOX.get(d["key"], {}))
        return d

    def maschera(self) -> int:
        m = 0
        for nome in self.modificatori:
            m |= MASCHERA_MODIFICATORI.get(nome, 0)
        return m

    # ── i verbi ─────────────────────────────────────────────────────────────
    def giu(self, tasto: str) -> None:
        d = self.descrivi(tasto)
        ripetuto = d["code"] in self.premuti
        self.premuti.add(d["code"])
        if d["key"] in MODIFICATORI:
            self.modificatori.add(d["key"])
        testo = d["text"]
        # ⛔ Invio: il testo lo genera Gecko. Mandarlo esplicito inserisce due
        # volte. Letto in `RawKeyboardImpl3.keydown`.
        if testo == "\r":
            testo = ""
        self.c.manda("Page.dispatchKeyEvent",
                     {"type": "keydown", "key": d["key"], "code": d["code"],
                      "keyCode": d["keyCodeWithoutLocation"],
                      "location": d["location"], "repeat": ripetuto,
                      "text": testo},
                     sessione=self.sessione, timeout=10)

    def su(self, tasto: str) -> None:
        d = self.descrivi(tasto)
        if d["key"] in MODIFICATORI:
            self.modificatori.discard(d["key"])
        self.premuti.discard(d["code"])
        # ⛔ NIENTE `text` qui: Juggler alza `keyup does not support text
        # option` e la digitazione muore a meta'.
        self.c.manda("Page.dispatchKeyEvent",
                     {"type": "keyup", "key": d["key"], "code": d["code"],
                      "keyCode": d["keyCodeWithoutLocation"],
                      "location": d["location"], "repeat": False},
                     sessione=self.sessione, timeout=10)

    def premi(self, tasto: str) -> None:
        """`press("a")`, `press("Enter")`, `press("Control+Shift+KeyA")`.

        I modificatori si tengono giu' per tutto il tasto finale e si
        rilasciano al contrario, come farebbe una mano.
        """
        pezzi = tasto.split("+")
        finale, tenuti = pezzi[-1], pezzi[:-1]
        # ⛔ Un `+` finale e' il tasto piu', non un separatore: `press("+")`
        # deve funzionare. `"+".split("+")` da' `["", ""]`, quindi il pezzo
        # vuoto va rimesso al suo posto invece di dare "tasto sconosciuto: ''".
        if finale == "" and tenuti:
            finale, tenuti = "+", tenuti[:-1]
        for m in tenuti:
            self.giu(m)
        try:
            self.giu(finale)
            self.su(finale)
        finally:
            for m in reversed(tenuti):
                self.su(m)

    def digita(self, testo: str, *, ritardo: float = 0.0) -> None:
        """Un tasto per carattere, come una mano.

        ⛔ NON e' `inserisci`: un carattere che il layout non conosce (un
        ideogramma, un'emoji) non ha un tasto, quindi qui si RIFIUTA e si
        rimanda a `inserisci`. Digitare cio' che non ha un tasto significherebbe
        mandare `code: ""`, che e' esattamente il difetto che questo file esiste
        per non avere.
        """
        import time as _t
        for ch in testo:
            if ch not in CHIUSURA:
                raise TastoSconosciuto(
                    "%r non ha un tasto sul layout US: usa `inserisci`, che "
                    "passa da `Page.insertText` e non finge una pressione."
                    % ch)
            self.premi(ch)
            if ritardo:
                _t.sleep(ritardo)

    def inserisci(self, testo: str) -> None:
        """Il testo entra senza eventi di tasto. E' cio' che serve per un
        carattere che sul layout non c'e'."""
        self.c.manda("Page.insertText", {"text": testo},
                     sessione=self.sessione, timeout=10)

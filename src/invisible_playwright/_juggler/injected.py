"""Lo script iniettato, chiamato da Python.

⛔ QUESTO MODULO NON REIMPLEMENTA NIENTE, e la ragione e' che non potrebbe: i
motori di selettori e l'actionability lavorano sul DOM, e Python non e' nella
pagina. Il JavaScript resta JavaScript; qui c'e' solo il modo di caricarlo nel
mondo giusto e di chiamarlo.

I DUE MONDI, che sono la ragione di tutto il file. Firefox da' all'automazione
un contesto separato che vede lo stesso DOM **attraverso un Xray**: li' dentro
`addEventListener`, `textContent` e `querySelector` sono quelli NATIVI, non
quelli che il sito puo' aver sostituito. Nel mondo MAIN tutto e' del sito, e
ogni lettura e' contabile da chi ha avvolto l'accessore. Il 2026-08-27 due
punti che sbagliavano mondo hanno prodotto 13 listener piu' una lettura di
`textContent` per ogni `bounding_box()`: vedi `31-client-fork.md` §3.9 e §3.10.

**Regola: qui si lavora SEMPRE nel mondo di utilita'.**

COME SI CREA. Non c'e' un comando "crea un mondo": si manda
`Page.setInitScripts` con uno script **vuoto** e un `worldName`, e Juggler
annuncia il contesto con `Runtime.executionContextCreated`, il cui
`auxData.name` porta quel nome. ⛔ Il nome e' `__ctx_aux__` e **non e' quello di
upstream**: il nostro fork lo ha rinominato perche' viaggiava sul window della
pagina (`31-client-fork.md` §3.5). Cambiarlo qui senza cambiarlo li' rompe
l'aggancio in silenzio.
"""
from __future__ import annotations

import json
import pathlib
import time
from typing import Any, Optional

#: ⛔ Deve restare uguale a `UTILITY_WORLD_NAME` del driver e al nome che
#: `31-client-fork.md` §3.5 dichiara. Non e' un dettaglio estetico: e' la chiave
#: con cui si riconosce il contesto giusto in `executionContextCreated`.
MONDO_UTILITA = "__ctx_aux__"

_SORGENTE = pathlib.Path(__file__).with_name("injected.js")


class ErroreValutazione(RuntimeError):
    """Il JavaScript ha lanciato. Porta il testo e lo stack della PAGINA."""


class ScriptIniettato:
    """Un `InjectedScript` per frame, nel mondo di utilita'."""

    def __init__(self, connessione, sessione: str):
        self.c = connessione
        self.sessione = sessione
        #: (frameId, nomeMondo) -> executionContextId
        self.contesti: dict = {}
        #: frameId -> objectId dell'InjectedScript
        self._handle: dict = {}
        precedente = connessione.su_evento

        def instrada(metodo, params, sessione_evento):
            if sessione_evento == self.sessione:
                self._evento(metodo, params)
            precedente(metodo, params, sessione_evento)

        connessione.su_evento = instrada

    def _evento(self, metodo: str, p: dict) -> None:
        if metodo == "Runtime.executionContextCreated":
            aux = p.get("auxData") or {}
            self.contesti[(aux.get("frameId"), aux.get("name") or "")] = \
                p["executionContextId"]
        elif metodo == "Runtime.executionContextDestroyed":
            morto = p["executionContextId"]
            for k in [k for k, v in self.contesti.items() if v == morto]:
                self.contesti.pop(k, None)
            # ⛔ E si butta l'handle: un objectId di un contesto distrutto non
            # da' errore subito, da' risultati sbagliati. Il documento e'
            # cambiato sotto, quindi lo script iniettato va ricostruito.
            for f in [f for f, _ in list(self._handle.items())
                      if (f, MONDO_UTILITA) not in self.contesti]:
                self._handle.pop(f, None)

    # ── il mondo ────────────────────────────────────────────────────────────
    def prepara(self) -> None:
        """Crea il mondo di utilita'. Uno script VUOTO basta: cio' che conta e'
        il `worldName`, che e' l'unica cosa che fa nascere il contesto."""
        self.c.manda("Page.setInitScripts",
                     {"scripts": [{"script": "", "worldName": MONDO_UTILITA}]},
                     sessione=self.sessione)

    def contesto(self, frame_id: str, *, timeout: float = 10.0) -> str:
        chiave = (frame_id, MONDO_UTILITA)
        scade = time.monotonic() + timeout
        while chiave not in self.contesti:
            if time.monotonic() > scade:
                mondi = sorted(n for f, n in self.contesti if f == frame_id)
                raise TimeoutError(
                    "il mondo di utilita' (%s) non e' nato per il frame %s in "
                    "%.0fs. Mondi visti per quel frame: %s. Hai chiamato "
                    "prepara()?" % (MONDO_UTILITA, frame_id, timeout,
                                    mondi or "nessuno"))
            time.sleep(0.01)
        return self.contesti[chiave]

    # ── la valutazione ──────────────────────────────────────────────────────
    def _esito(self, risposta: dict) -> dict:
        """⛔ Un'eccezione della pagina NON arriva come errore di protocollo:
        arriva come un campo `exceptionDetails` dentro una risposta RIUSCITA.
        Chi guarda solo il codice di ritorno legge `None` e prosegue."""
        ecc = (risposta or {}).get("exceptionDetails")
        if ecc:
            raise ErroreValutazione(
                "%s%s" % (ecc.get("text") or ecc.get("value") or "eccezione",
                          ("\n" + ecc["stack"]) if ecc.get("stack") else ""))
        return (risposta or {}).get("result") or {}

    def valuta(self, frame_id: str, espressione: str, *,
               per_valore: bool = True, timeout: float = 30.0) -> Any:
        r = self._esito(self.c.manda(
            "Runtime.evaluate",
            {"executionContextId": self.contesto(frame_id),
             "expression": espressione, "returnByValue": per_valore},
            sessione=self.sessione, timeout=timeout))
        return r.get("value") if per_valore else r.get("objectId")

    def chiama(self, frame_id: str, funzione: str, *argomenti,
               per_valore: bool = True, timeout: float = 30.0) -> Any:
        """`funzione` e' una dichiarazione JS; il PRIMO argomento passato e'
        sempre l'InjectedScript, come fa il driver."""
        args = [{"objectId": self.handle(frame_id)}]
        for a in argomenti:
            args.append(a if isinstance(a, dict) and
                        ("objectId" in a or "value" in a) else {"value": a})
        r = self._esito(self.c.manda(
            "Runtime.callFunction",
            {"executionContextId": self.contesto(frame_id),
             "functionDeclaration": funzione, "args": args,
             "returnByValue": per_valore},
            sessione=self.sessione, timeout=timeout))
        return r.get("value") if per_valore else r.get("objectId")

    def handle(self, frame_id: str) -> str:
        """L'InjectedScript del frame, costruito una volta sola."""
        if frame_id in self._handle:
            return self._handle[frame_id]
        opzioni = {
            # ⛔ `isUnderTest` FALSO, sempre. A vero, l'InjectedScript pianta
            # `window.builtins` e `window.__injectedScript` sul window della
            # pagina, ENUMERABILI: e' il tell che `31-client-fork.md` §3.3
            # dichiara spento, e riaccenderlo da qui lo rimetterebbe.
            "isUnderTest": False,
            "sdkLanguage": "python",
            "testIdAttributeName": "data-testid",
            "stableRafCount": 1,
            "browserName": "firefox",
            "shouldPrependErrorPrefix": False,
            # ⛔ VERO, ed e' la riga che tiene fuori i 13 listener: con falso
            # il costruttore li installa sull'addEventListener della PAGINA.
            "isUtilityWorld": True,
            "customEngines": [],
        }
        sorgente = _SORGENTE.read_text(encoding="utf-8")
        espressione = ("(() => { const module = {};\n%s\n"
                       "return new (module.exports.InjectedScript())"
                       "(globalThis, %s); })();"
                       % (sorgente, json.dumps(opzioni)))
        oid = self.valuta(frame_id, espressione, per_valore=False)
        if not oid:
            raise ErroreValutazione(
                "l'InjectedScript non ha restituito un oggetto: "
                "il sorgente e' quello giusto?")
        self._handle[frame_id] = oid
        return oid

    # ── il poco che serve sopra ─────────────────────────────────────────────
    def risolvi(self, frame_id: str, selettore: str,
                *, stretto: bool = False) -> Optional[str]:
        """L'objectId del primo elemento che corrisponde, o None."""
        return self.chiama(
            frame_id,
            "(injected, sel, stretto) => {"
            "  const p = injected.parseSelector(sel);"
            "  return injected.querySelector(p, document, stretto) || null; }",
            selettore, stretto, per_valore=False)

    def quanti(self, frame_id: str, selettore: str) -> int:
        return self.chiama(
            frame_id,
            "(injected, sel) => injected.querySelectorAll("
            "injected.parseSelector(sel), document).length",
            selettore)

    def stati(self, frame_id: str, elemento: str, stati: list) -> dict:
        """Chiede allo script iniettato se l'elemento e' azionabile.

        Torna `{"ok": True}` oppure `{"ok": False, "manca": "<stato>"}`. Gli
        stati sono quelli di Playwright: `visible`, `stable`, `enabled`,
        `editable`. ⛔ `stable` e' ASINCRONO (aspetta due fotogrammi), quindi la
        funzione e' `async` e il valore va atteso: senza `await` si otterrebbe
        una Promise e ogni elemento risulterebbe azionabile.
        """
        return self.chiama(
            frame_id,
            "async (injected, el, stati) => {"
            "  const r = await injected.checkElementStates(el, stati);"
            "  if (r === undefined) return { ok: true };"
            "  if (typeof r === 'string') return { ok: false, manca: r };"
            "  return { ok: false, manca: r.missingState }; }",
            {"objectId": elemento}, stati)

    def testo(self, frame_id: str, elemento: str) -> str:
        """⛔ Passa dal mondo di utilita', quindi dall'Xray: la stessa lettura
        fatta nel mondo MAIN sarebbe contabile dal sito."""
        return self.chiama(
            frame_id,
            "(injected, el) => el.textContent || ''",
            {"objectId": elemento})

    def libera(self, frame_id: str, elemento: str) -> None:
        """Un objectId trattenuto tiene vivo un nodo del DOM della pagina.

        ⛔ `Runtime.disposeObject` vuole ANCHE l'`executionContextId`: un
        objectId da solo non identifica niente, perche' lo stesso numero puo'
        esistere in due contesti.
        """
        try:
            self.c.manda("Runtime.disposeObject",
                         {"executionContextId": self.contesto(frame_id),
                          "objectId": elemento},
                         sessione=self.sessione, timeout=5)
        except Exception:
            pass

"""La connessione a Juggler: la pipe, senza Node in mezzo.

IL CONTRATTO, letto in `juggler/pipe/nsRemoteDebuggingPipe.cpp` e non dedotto:

  - i messaggi sono JSON delimitati da un BYTE ZERO, non da un a capo
    (`ReaderLoop` accumula finche' non trova `'\\0'`);
  - su POSIX i descrittori sono **cablati a 3 e 4**: `const int readFD = 3;
    const int writeFD = 4;`. Non si negoziano;
  - su Windows NON esistono descrittori: sono HANDLE letti dall'ambiente,
    `GetEnvironmentVariableA("PW_PIPE_READ", ...)` piu' `atoi`, quindi il valore
    va passato in DECIMALE e l'handle va reso ereditabile;
  - i nomi sono dal punto di vista del BROWSER: il suo `PW_PIPE_READ` e' cio' da
    cui LUI legge, cioe' dove NOI scriviamo.

⛔ E il flag `-juggler-pipe` deve comparire sulla riga di comando, o su Windows
gli handle non vengono armati affatto e la pipe si tronca alla transizione
launcher -> parent.

⛔ IL SEGNALE DI PRONTEZZA NON PASSA DALLA PIPE. Il browser stampa
`Juggler listening to the pipe` su stdout, e quella riga esce da una `dump()`
che una build `MOZILLA_OFFICIAL` spegne: una `dump()` disabilitata RITORNA CON
SUCCESSO senza scrivere. Il rimedio vive nel sorgente Firefox
(`30-upstream-playwright-patches.md`), non qui. Chi legge un timeout lungo al
lancio guardi prima li'.

Stato: primo pezzo. Apre la connessione, manda comandi, riceve risposte ed
eventi. Non e' ancora un client: non c'e' il ciclo di vita, non ci sono i
frame, non c'e' l'actionability.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Optional

ZERO = b"\x00"
_PRONTO = "Juggler listening to the pipe"


class ErroreProtocollo(RuntimeError):
    """Il browser ha rifiutato un comando. Porta il messaggio suo, non il nostro.

    ⛔ `checkScheme` e' a MONDO CHIUSO: un campo non dichiarato non viene
    ignorato, viene rifiutato, e succede a RUNTIME. Il messaggio del browser e'
    l'unica cosa che dice quale campo.
    """


class Connessione:
    """Una pipe verso un Firefox gia' avviato."""

    def __init__(self, verso_browser, dal_browser, processo=None):
        self._verso = verso_browser        # dove NOI scriviamo
        self._da = dal_browser             # dove NOI leggiamo
        self._processo = processo
        self._prossimo_id = 0
        self._attese: dict[int, list] = {}
        self._lucchetto = threading.Lock()
        self._chiuso = False
        self._errore: Optional[BaseException] = None
        self.su_evento: Callable[[str, dict], None] = lambda metodo, params: None
        self._lettore = threading.Thread(target=self._ciclo_lettura, daemon=True)
        self._lettore.start()

    # ── lettura ─────────────────────────────────────────────────────────────
    def _ciclo_lettura(self) -> None:
        resto = b""
        try:
            while not self._chiuso:
                pezzo = os.read(self._da, 65536)
                if not pezzo:
                    break
                resto += pezzo
                while ZERO in resto:
                    grezzo, resto = resto.split(ZERO, 1)
                    if grezzo:
                        self._consegna(grezzo)
        except OSError as e:
            self._errore = e
        finally:
            self._chiuso = True
            with self._lucchetto:
                attese = list(self._attese.values())
                self._attese.clear()
            for cassetta in attese:
                cassetta.append({"error": {"message": "la pipe si e' chiusa"}})

    def _consegna(self, grezzo: bytes) -> None:
        try:
            msg = json.loads(grezzo.decode("utf-8"))
        except Exception:
            return
        ident = msg.get("id")
        if ident is None:
            metodo = msg.get("method")
            if metodo:
                try:
                    self.su_evento(metodo, msg.get("params") or {})
                except Exception:
                    pass
            return
        with self._lucchetto:
            cassetta = self._attese.pop(ident, None)
        if cassetta is not None:
            cassetta.append(msg)

    # ── scrittura ───────────────────────────────────────────────────────────
    def manda(self, metodo: str, params: Optional[dict] = None,
              sessione: Optional[str] = None, timeout: float = 30.0) -> Any:
        if self._chiuso:
            raise ErroreProtocollo("la pipe e' chiusa: %s" % (self._errore or ""))
        with self._lucchetto:
            self._prossimo_id += 1
            ident = self._prossimo_id
            cassetta: list = []
            self._attese[ident] = cassetta
        msg: dict = {"id": ident, "method": metodo, "params": params or {}}
        if sessione:
            msg["sessionId"] = sessione
        os.write(self._verso, json.dumps(msg).encode("utf-8") + ZERO)

        scade = time.monotonic() + timeout
        while not cassetta:
            if time.monotonic() > scade:
                with self._lucchetto:
                    self._attese.pop(ident, None)
                raise ErroreProtocollo(
                    "%s: nessuna risposta in %.0fs. Se e' il PRIMO comando, "
                    "guarda il segnale di prontezza prima della pipe." % (metodo, timeout))
            time.sleep(0.002)
        risposta = cassetta[0]
        if "error" in risposta:
            e = risposta["error"]
            raise ErroreProtocollo("%s: %s" % (metodo, e.get("message", e)))
        return risposta.get("result")

    def chiudi(self, attesa: float = 5.0) -> None:
        """Chiude la pipe e aspetta che il browser se ne vada da solo.

        ⛔ NON si comincia da `terminate()`, e la ragione e' misurata in questo
        progetto: su Windows il pid che `Popen` restituisce e' lo stub del
        LAUNCHER, che esce dopo circa un secondo, quindi al momento del kill
        l'albero del browser non e' piu' suo figlio e sopravvive. Contati un
        giorno: 88 processi orfani.

        La via pulita passa dal contratto: `nsRemoteDebuggingPipe::ReaderLoop`
        chiama `Disconnected` quando la lettura torna zero, e Juggler spegne il
        browser. Chiudere la pipe E' il comando di uscita. `terminate()` resta
        solo come ultima spiaggia, e su cio' che non e' morto da solo.
        """
        self._chiuso = True
        for fd in (self._verso, self._da):
            try:
                os.close(fd)
            except OSError:
                pass
        p = self._processo
        if not p:
            return
        scade = time.monotonic() + attesa
        while p.poll() is None and time.monotonic() < scade:
            time.sleep(0.05)
        if p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass


# ── avvio ───────────────────────────────────────────────────────────────────

def _avvia_windows(eseguibile, argv, ambiente):
    import _winapi
    import msvcrt

    def ereditabile(h):
        """⛔ `_winapi.CreatePipe` di CPython chiama la CreatePipe di Windows con
        security attributes NULL, quindi gli handle NON sono ereditabili. Passarli
        in `handle_list` cosi' com'erano faceva fallire `CreateProcess` con
        `WinError 87 - The parameter is incorrect`, che non nomina la causa.
        Si duplicano chiedendo l'ereditarieta' e si chiude l'originale."""
        io = _winapi.GetCurrentProcess()
        nuovo = _winapi.DuplicateHandle(io, h, io, 0, True,
                                        _winapi.DUPLICATE_SAME_ACCESS)
        _winapi.CloseHandle(h)
        return nuovo

    # Due pipe. I nomi seguono il punto di vista del BROWSER, come l'ambiente
    # che leggera': "read" e' cio' da cui lui legge, quindi dove NOI scriviamo.
    suo_read, nostro_write = _winapi.CreatePipe(0, 0)
    nostro_read, suo_write = _winapi.CreatePipe(0, 0)
    suo_read, suo_write = ereditabile(suo_read), ereditabile(suo_write)

    ambiente = dict(ambiente)
    # `atoi` lato C++: il valore va in DECIMALE.
    ambiente["PW_PIPE_READ"] = str(int(suo_read))
    ambiente["PW_PIPE_WRITE"] = str(int(suo_write))

    si = subprocess.STARTUPINFO()
    si.lpAttributeList = {"handle_list": [int(suo_read), int(suo_write)]}
    # `handle_list` PRETENDE close_fds=True: e' l'unico modo in cui Windows
    # eredita esattamente quei due handle e nient'altro.
    p = subprocess.Popen([eseguibile] + argv, env=ambiente, startupinfo=si,
                         close_fds=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    # Gli estremi del figlio non servono piu' a noi: tenerli aperti impedirebbe
    # di accorgersi che il browser ha chiuso.
    _winapi.CloseHandle(suo_read)
    _winapi.CloseHandle(suo_write)
    return (msvcrt.open_osfhandle(nostro_write, 0),
            msvcrt.open_osfhandle(nostro_read, os.O_RDONLY), p)


def _avvia_posix(eseguibile, argv, ambiente):
    suo_read, nostro_write = os.pipe()
    nostro_read, suo_write = os.pipe()

    def sistema_descrittori():
        # Su POSIX i numeri sono CABLATI nel C++: 3 in lettura, 4 in scrittura.
        os.dup2(suo_read, 3)
        os.dup2(suo_write, 4)

    p = subprocess.Popen([eseguibile] + argv, env=ambiente,
                         preexec_fn=sistema_descrittori,
                         pass_fds=(suo_read, suo_write),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    os.close(suo_read)
    os.close(suo_write)
    return nostro_write, nostro_read, p


def avvia(eseguibile: str, profilo: str, *, headless: bool = True,
          argv_extra: Optional[list] = None, ambiente: Optional[dict] = None,
          attesa_prontezza: float = 60.0) -> Connessione:
    """Lancia Firefox con la pipe e torna una connessione gia' pronta."""
    argv = ["-no-remote"]
    if headless:
        argv.append("-headless")
    else:
        argv += ["-wait-for-browser", "-foreground"]
    argv += ["-profile", profilo, "-juggler-pipe"]
    argv += list(argv_extra or [])
    argv.append("-silent")

    amb = dict(os.environ if ambiente is None else ambiente)
    avvio = _avvia_windows if sys.platform == "win32" else _avvia_posix
    verso, da, p = avvio(eseguibile, argv, amb)

    # ⛔ La prontezza si legge su stdout, non sulla pipe, e la riga puo' non
    # uscire affatto su una build MOZILLA_OFFICIAL senza il rimedio in Juggler.
    # Si aspetta la riga, ma NON si muore se non arriva: si prova comunque a
    # parlare, cosi' il modo di fallire e' un errore di protocollo che nomina il
    # comando invece di un timeout muto.
    visto = _aspetta_prontezza(p, attesa_prontezza)
    c = Connessione(verso, da, p)
    c.prontezza_vista = visto
    return c


def _aspetta_prontezza(p, timeout: float) -> bool:
    scade = time.monotonic() + timeout
    while time.monotonic() < scade:
        if p.poll() is not None:
            return False
        riga = p.stdout.readline()
        if not riga:
            time.sleep(0.01)
            continue
        if _PRONTO in riga.decode("utf-8", "replace"):
            return True
    return False

"""Estrae lo script iniettato dal bundle del driver in `_juggler/injected.js`.

PERCHE' SI ESTRAE E NON SI RISCRIVE. Quel JavaScript e' i motori di selettori
(css, xpath, text, role, testid, label), l'actionability, lo snapshot ARIA e
`expect`: migliaia di righe di logica DOM sottile che **gira nella pagina** e
che nessuna riscrittura in Python potrebbe sostituire, perche' Python non e'
nella pagina. Non e' lavoro da rifare: e' merce da trasportare.

⛔ MA NON E' UPSTREAM VERGINE. Porta gia' correzioni nostre - `markTargetElements`
svuotata, `__pwClock` letto via descrittore, `Symbol.hasInstance` catturato, e
dal 2026-08-27 le installazioni di listener guardate da `_isUtilityWorld`.
Estrarlo da un bundle diverso da QUESTO le perde tutte, in silenzio.
Vedi `31-client-fork.md` §3.

⛔ E NON E' ANCORA TAGLIATO. Il perimetro scelto (`32-stacco-da-playwright.md`
§1) lascia fuori snapshot ARIA, `locatorGenerators`, `highlight` e `consoleApi`,
cioe' **87.468 byte su 311.365**. Qui si estrae INTERO: il taglio e' un passo a
se', e va fatto sui confini veri dei moduli, che nel bundle emesso **non sono
confini** (§3.3).

    python scripts/gen_injected_source.py            (estrae)
    python scripts/gen_injected_source.py --check    (rigenera e confronta)
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ANCORA = "source4 = '"


def estrai(bundle: str) -> str:
    """Il valore della stringa `source4`, de-escapato.

    ⛔ E' una stringa ad APICE SINGOLO su UNA riga fisica da trecentomila
    caratteri. Si scandisce a mano rispettando le barre rovesce: una regex
    ingorda prende fino all'ultimo apice del FILE, e una pigra si ferma al primo
    apostrofo dentro un commento.
    """
    i = bundle.index(ANCORA) + len(ANCORA)
    bs = chr(92)
    j = i
    n = len(bundle)
    while j < n:
        if bundle[j] == bs:
            j += 2
            continue
        if bundle[j] == "'":
            break
        j += 1
    else:
        raise SystemExit("la stringa source4 non si chiude: bundle corrotto?")
    grezzo = bundle[i:j]
    # De-escape: la stringa e' JavaScript, ma gli escape usati sono quelli che
    # `unicode_escape` capisce. Si passa da latin-1 per non rompere i byte alti.
    return grezzo.encode("latin-1", "backslashreplace").decode("unicode_escape")


def main() -> int:
    qui = pathlib.Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default=str(
        qui / "src" / "invisible_playwright" / "_driver" / "package" / "lib" / "coreBundle.js"))
    ap.add_argument("--out", default=str(
        qui / "src" / "invisible_playwright" / "_juggler" / "injected.js"))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    bundle = pathlib.Path(a.bundle).read_bytes().decode("utf-8", "replace")
    sorgente = estrai(bundle)

    # Prova che cio' che abbiamo estratto e' DAVVERO lo script iniettato, non
    # una stringa qualsiasi che comincia allo stesso modo. Un controllo su cio'
    # che DEVE contenere costa niente e impedisce di spedire un blob sbagliato.
    ATTESI = ("InjectedScript", "internal:role", "internal:testid",
              "_setupHitTargetInterceptors", "createRoleEngine")
    mancanti = [x for x in ATTESI if x not in sorgente]
    if mancanti:
        raise SystemExit("l'estratto non sembra lo script iniettato: mancano %s"
                         % ", ".join(mancanti))
    # E che porti le NOSTRE correzioni: un bundle upstream le perderebbe tutte
    # senza che niente dia errore.
    if "MODIFICATO da invisible_playwright" not in sorgente:
        raise SystemExit("l'estratto NON porta le modifiche di invisible_playwright: "
                         "e' un bundle upstream, non il nostro")

    print("estratto: %d byte, %d righe" % (len(sorgente.encode("utf-8")),
                                           sorgente.count(chr(10))))
    print("  modifiche nostre marcate: %d"
          % sorgente.count("MODIFICATO da invisible_playwright"))

    out = pathlib.Path(a.out)
    nuovo = sorgente.encode("utf-8")
    if a.check:
        if not out.is_file():
            print("MANCA: %s" % out)
            return 1
        if out.read_bytes() == nuovo:
            print("SCRIPT INIETTATO ALLINEATO")
            return 0
        print("DERIVA: l'estratto non corrisponde al file in albero")
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(nuovo)
    print("scritto %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

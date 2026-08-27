"""Estrae il layout di tastiera US dal bundle del driver in `_juggler/keylayout.py`.

⛔ NON SI RIBATTE A MANO. `Page.dispatchKeyEvent` pretende `key`, `code`,
`keyCode` e `location` insieme, e sono ~230 voci: una tabella copiata a mano ha
due modi di sbagliare che nessun test vede. Il primo e' un `keyCode` sbagliato,
che la pagina legge in `event.keyCode` senza che l'azione fallisca. Il secondo,
peggiore, e' una tabella INCOMPLETA: un tasto assente non da' errore, produce
`keyCode: 0` per un tasto che su ogni Firefox vero ha un numero, e quello e' un
tell che vive in un campo che nessuno guarda.

E' la stessa forma di `gen_juggler_protocol.py` e `gen_injected_source.py`: una
fonte sola, generata, mai due numeri per la stessa cosa (regola 16).

    python scripts/gen_key_layout.py            # rigenera _juggler/keylayout.py
    python scripts/gen_key_layout.py --check    # 1 se il file in albero e' vecchio
    python scripts/gen_key_layout.py --selftest # 6 mutazioni, piu' 2 che NON devono scattare
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

RADICE = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = RADICE / "src/invisible_playwright/_driver/package/lib/coreBundle.js"
USCITA = RADICE / "src/invisible_playwright/_juggler/keylayout.py"

#: Il letterale comincia qui. ⛔ Si ancora al NOME della variabile, non a una
#: voce della tabella: ancorarsi a `"KeyA"` legherebbe l'estrazione a un tasto
#: che un domani puo' spostarsi di riga.
INIZIO = re.compile(r"USKeyboardLayout\s*=\s*\{")


#: Le fughe che il bundle usa davvero. Cio' che non e' qui viene passato com'e',
#: che e' il comportamento giusto per `\'` e `\"`: la fuga sparisce e resta il
#: carattere.
FUGHE = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
         "0": "\0", chr(92): chr(92)}


class EstrazioneFallita(RuntimeError):
    pass


def _letterale(testo: str) -> str:
    """Il corpo `{...}` bilanciato che segue `USKeyboardLayout =`.

    ⛔ Conta le graffe invece di cercare la prima `};`: il valore contiene
    stringhe con graffe dentro (`"key": "{"` esiste davvero, e' BracketLeft con
    shift) e una ricerca ingenua taglierebbe la tabella a meta' senza errore.
    """
    m = INIZIO.search(testo)
    if not m:
        raise EstrazioneFallita(
            "`USKeyboardLayout = {` non compare nel bundle. Se il bundler ha "
            "rinominato la variabile, l'ancora va cambiata qui e non aggirata.")
    i = m.end() - 1
    prof, j, in_str, virg, fuga = 0, i, False, "", False
    while j < len(testo):
        c = testo[j]
        if in_str:
            if fuga:
                fuga = False
            elif c == chr(92):
                fuga = True
            elif c == virg:
                in_str = False
        elif c in "\"'":
            in_str, virg = True, c
        elif c == "{":
            prof += 1
        elif c == "}":
            prof -= 1
            if prof == 0:
                return testo[i:j + 1]
        j += 1
    raise EstrazioneFallita("graffe non bilanciate a partire da USKeyboardLayout")


def _pulisci(letterale: str) -> str:
    """Da letterale JS a JSON, con un solo passaggio che SCANDISCE.

    Tre cose che una regex non puo' fare bene, e tutte e tre compaiono nel
    bundle vero:

    1. ⛔ **Gli apici singoli.** `"Quote": { "shiftKey": '"' }` e' JS valido e
       JSON non lo accetta. Vanno riscritti come stringhe JSON, non sostituiti
       carattere per carattere: il contenuto puo' contenere la virgoletta
       doppia, che e' esattamente questo caso.
    2. ⛔ **I commenti.** Toglierli con `//[^\\n]*` cancella anche un `//`
       DENTRO una stringa. Qui non succede, ma il modo di sbagliare e'
       silenzioso - accorcia un valore invece di dare errore - e non vale la
       pena tenerlo.
    3. Le virgole pendenti prima di una graffa, che JS accetta e JSON no.
    """
    fuori, i = [], 0
    while i < len(letterale):
        c = letterale[i]
        if c == "/" and letterale[i + 1:i + 2] == "/":
            i = letterale.find("\n", i)
            if i < 0:
                break
            continue
        if c in "\"'":
            virg, j, dentro = c, i + 1, []
            while j < len(letterale):
                d = letterale[j]
                if d == chr(92):
                    # ⛔ Si DECODIFICA qui invece di ricitare il testo grezzo.
                    # Ricitarlo significherebbe raddoppiare un `\"` gia'
                    # sfuggito, e il carattere che il bundle scrive con l'apice
                    # singolo e' proprio la virgoletta doppia.
                    seg = letterale[j + 1:j + 2]
                    if seg == "u":
                        dentro.append(chr(int(letterale[j + 2:j + 6], 16)))
                        j += 6
                    else:
                        dentro.append(FUGHE.get(seg, seg))
                        j += 2
                    continue
                if d == virg:
                    break
                dentro.append(d)
                j += 1
            fuori.append(json.dumps("".join(dentro)))
            i = j + 1
            continue
        fuori.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(fuori))


def estrai(testo: str) -> dict:
    dati = json.loads(_pulisci(_letterale(testo)))
    if not isinstance(dati, dict) or not dati:
        raise EstrazioneFallita("la tabella e' vuota")
    # ⛔ Il controllo di SANITA' e' qui e non nel chiamante: una tabella che si
    # estrae ma non contiene i tasti che ogni layout ha e' un'estrazione
    # sbagliata che ha avuto fortuna con le graffe.
    mancanti = [k for k in ("KeyA", "Enter", "Backspace", "Digit0", "Space",
                            "ShiftLeft", "ArrowLeft", "Tab", "Escape")
                if k not in dati]
    if mancanti:
        raise EstrazioneFallita(
            "estratta ma incompleta: mancano %s. Non e' il layout US."
            % ", ".join(mancanti))
    return dati


def rendi(dati: dict) -> str:
    corpo = json.dumps(dati, indent=4, sort_keys=True, ensure_ascii=False)
    corpo = corpo.replace("true", "True").replace("false", "False") \
                 .replace(": null", ": None")
    return (
        '"""Il layout di tastiera US, ESTRATTO dal bundle del driver.\n'
        "\n"
        "GENERATO da `python scripts/gen_key_layout.py`. Non modificare a mano:\n"
        "il gate `--check` rifiuta un albero in cui questo file e il bundle non\n"
        "coincidono, e una voce corretta a mano tornerebbe indietro al primo\n"
        "rigenera.\n"
        "\n"
        "Ogni voce e' indicizzata per `code` (il tasto FISICO) e porta `keyCode`,\n"
        "il `key` senza shift e, dove esiste, `shiftKey`. E' cio' che\n"
        "`Page.dispatchKeyEvent` pretende: quattro campi insieme, e uno sbagliato\n"
        "non fa fallire l'azione - si limita a mentire in `event.keyCode`.\n"
        '"""\n'
        "from __future__ import annotations\n"
        "\n"
        "#: %d voci, indicizzate per `code`.\n" % len(dati) +
        "LAYOUT = " + corpo + "\n"
        "\n"
        "#: `key` senza shift -> `code`. Serve per `press(\"a\")` e per digitare:\n"
        "#: un carattere si cerca prima qui, poi fra gli shiftati.\n"
        "PER_TASTO = {v[\"key\"]: k for k, v in LAYOUT.items() if \"key\" in v}\n"
        "\n"
        "#: `shiftKey` -> `code`. `A`, `!`, `{` stanno qui e NON in PER_TASTO.\n"
        "PER_TASTO_SHIFT = {v[\"shiftKey\"]: k for k, v in LAYOUT.items()\n"
        "                   if \"shiftKey\" in v}\n")


# ── il selftest ─────────────────────────────────────────────────────────────
def selftest() -> int:
    buono = ('var x = 1;\n'
             'USKeyboardLayout = {\n'
             '  // prima riga\n'
             '  "KeyA": { "keyCode": 65, "shiftKey": "A", "key": "a" },\n'
             '  "Digit0": { "keyCode": 48, "shiftKey": ")", "key": "0" },\n'
             '  "BracketLeft": { "keyCode": 219, "shiftKey": "{", "key": "[" },\n'
             '  "Enter": { "keyCode": 13, "key": "Enter", "text": "\\r" },\n'
             '  "Backspace": { "keyCode": 8, "key": "Backspace" },\n'
             '  "Space": { "keyCode": 32, "key": " " },\n'
             '  "ShiftLeft": { "keyCode": 16, "key": "Shift", "location": 1 },\n'
             '  "ArrowLeft": { "keyCode": 37, "key": "ArrowLeft" },\n'
             '  "Tab": { "keyCode": 9, "key": "Tab" },\n'
             '  "Escape": { "keyCode": 27, "key": "Escape" },\n'
             '};\nvar dopo = 2;\n')

    def prova(nome, testo, deve_alzare=True):
        try:
            d = estrai(testo)
        except Exception as e:
            if deve_alzare:
                print("  uccisa: %s (%s)" % (nome, str(e).splitlines()[0][:60]))
                return 0
            print("  FALSO POSITIVO: %s -> %s" % (nome, e))
            return 1
        if deve_alzare:
            print("  SOPRAVVISSUTA: %s -> ha estratto %d voci" % (nome, len(d)))
            return 1
        print("  taciuto: %s (%d voci)" % (nome, len(d)))
        return 0

    print("--- mutazioni che DEVONO scattare ---")
    male = 0
    male += prova("la variabile rinominata dal bundler",
                  buono.replace("USKeyboardLayout", "UsKbLayout"))
    male += prova("la tabella troncata: mancano i tasti che ogni layout ha",
                  'USKeyboardLayout = {\n  "KeyA": { "keyCode": 65, "key": "a" },\n};')
    male += prova("graffe non bilanciate",
                  buono.replace('"Escape": { "keyCode": 27, "key": "Escape" },\n};',
                                '"Escape": { "keyCode": 27, "key": "Escape" },\n'))
    male += prova("la tabella vuota",
                  buono[:buono.index("{", buono.index("USKeyboardLayout")) + 1] + "};")
    # ⛔ Questa e' la mutazione che ha giustificato il conteggio delle graffe:
    # con una ricerca del primo `};` la tabella si taglia su BracketLeft, che
    # contiene una graffa DENTRO una stringa, e l'estrazione riesce a meta'.
    tagliata = buono.replace('"Enter": { "keyCode": 13, "key": "Enter", "text": "\\r" },\n', "")
    male += prova("Enter tolto: incompleta ma sintatticamente valida", tagliata)
    male += prova("il letterale sostituito da un array",
                  buono.replace("USKeyboardLayout = {", "USKeyboardLayout = ["))

    print("--- casi che NON devono scattare ---")
    male += prova("il bundle buono", buono, deve_alzare=False)
    male += prova("una graffa dentro una stringa non chiude la tabella",
                  buono.replace('"shiftKey": "{"', '"shiftKey": "}"'),
                  deve_alzare=False)
    print()
    print("selftest: %s" % ("TUTTO BENE" if not male else "%d PROBLEMI" % male))
    return 1 if male else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--check", action="store_true")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()
    if a.selftest:
        return selftest()
    if not BUNDLE.exists():
        print("il bundle non c'e': %s" % BUNDLE)
        return 2
    try:
        dati = estrai(BUNDLE.read_text(encoding="utf-8", errors="replace"))
    except EstrazioneFallita as guasto:
        print("estrazione fallita: %s" % guasto)
        return 2
    testo = rendi(dati)
    if a.check:
        vivo = USCITA.read_bytes().decode("utf-8") if USCITA.exists() else ""
        if vivo != testo:
            print("keylayout.py non coincide col bundle (%d voci estratte). "
                  "`python scripts/gen_key_layout.py`" % len(dati))
            return 1
        print("keylayout.py coincide: %d voci" % len(dati))
        return 0
    # ⛔ `write_bytes`: `write_text` su Windows tradurrebbe ogni newline.
    USCITA.write_bytes(testo.encode("utf-8"))
    print("scritto %s: %d voci" % (USCITA.name, len(dati)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

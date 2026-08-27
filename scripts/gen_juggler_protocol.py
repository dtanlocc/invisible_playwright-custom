"""Genera `_juggler/protocol.py` dal `Protocol.js` di Juggler.

PERCHE' SI GENERA E NON SI SCRIVE. `Protocol.js` e' lo schema leggibile a
macchina del protocollo, e il browser lo applica a MONDO CHIUSO: un campo non
dichiarato non viene ignorato, viene RIFIUTATO a runtime, e la sessione muore
alla creazione del contesto con la build verde. Il costo misurato di quella
classe di guasto in questo progetto e' 97 test su 133. Una tabella scritta a
mano accanto a un file che gia' contiene la verita' e' una seconda fonte che
diverge da sola.

⛔ SI LEGGE IL PROTOCOL.JS **SPEDITO**, NON QUELLO DELL'ALBERO. Sono due file
diversi che oggi coincidono: generare dall'albero produce un client per un
browser che nessun utente esegue, e il modo di fallire e' quello a mondo chiuso.
Il default e' quindi un binario, non un percorso sorgente.

⛔ E IL JUGGLER STA IN DUE LAYOUT: `omni.ja` (Windows) e albero sciolto
`./chrome/juggler/` (Linux). Si provano tutti e due e si dice quale ha risposto.

⛔ QUESTO NON SOSTITUISCE `protocol_drift_check.py`. Quel gate confronta cio'
che un client VERO manda contro la nostra dichiarazione, e resta l'unico a
sapere rispondere a quella domanda. Generare i due lati dalla stessa fonte non
rende la deriva impossibile: la rende INOSSERVABILE. Vedi
`docs/firefox-stealth-architecture/32-stacco-da-playwright.md` §3.2.

    python scripts/gen_juggler_protocol.py --binario <cartella firefox>
    python scripts/gen_juggler_protocol.py --check     (rigenera e confronta)
"""
from __future__ import annotations

import argparse
import pprint
import os
import pathlib
import re
import sys
import zipfile

MEMBRO_JAR = "chrome/juggler/content/protocol/Protocol.js"
DENTRO_ALBERO = "chrome/juggler/content/protocol/Protocol.js"

# I combinatori che `Protocol.js` usa davvero. Il vocabolario dichiarato in
# PrimitiveTypes.js ne ha 11; questi 8 sono quelli esercitati. Se un giorno ne
# compare un altro, il generatore RIFIUTA invece di indovinare.
COMBINATORI = {"String", "Number", "Boolean", "Any", "Enum",
               "Nullable", "Optional", "Array"}


# ── lettura ──────────────────────────────────────────────────────────────────

def sorgente_protocollo(binario: str) -> tuple[str, str]:
    """(etichetta, testo) del Protocol.js SPEDITO. Prova i due layout."""
    base = pathlib.Path(binario)
    sciolto = base / DENTRO_ALBERO
    if sciolto.is_file():
        return ("albero sciolto: %s" % sciolto,
                sciolto.read_bytes().decode("utf-8", "replace"))
    for nome in ("omni.ja", os.path.join("browser", "omni.ja")):
        jar = base / nome
        if not jar.is_file():
            continue
        try:
            with zipfile.ZipFile(jar) as z:
                if MEMBRO_JAR in z.namelist():
                    return ("%s!%s" % (jar, MEMBRO_JAR),
                            z.read(MEMBRO_JAR).decode("utf-8", "replace"))
        except zipfile.BadZipFile:
            # Firefox puo' impacchettare un jar ottimizzato che zipfile non
            # legge. Non e' un caso da ingoiare: si dice quale file e perche'.
            raise SystemExit("il jar %s non si apre con zipfile (jar ottimizzato). "
                             "Estrarlo con 7z e passare --proto." % jar)
    raise SystemExit("Protocol.js non trovato in %s: ne albero sciolto ne omni.ja"
                     % binario)


def senza_commenti(s: str) -> str:
    """Toglie // e /* */ senza toccare cio' che sta dentro le stringhe."""
    fuori, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c in ("'", '"', "`"):
            j = i + 1
            while j < n:
                if s[j] == chr(92):
                    j += 2
                    continue
                if s[j] == c:
                    break
                j += 1
            fuori.append(s[i:j + 1])
            i = j + 1
        elif s.startswith("//", i):
            j = s.find(chr(10), i)
            i = n if j < 0 else j
        elif s.startswith("/*", i):
            j = s.find("*/", i)
            i = n if j < 0 else j + 2
        else:
            fuori.append(c)
            i += 1
    return "".join(fuori)


def blocco(s: str, da: int) -> str:
    """Dal primo '{' a `da`, il blocco bilanciato, saltando le stringhe."""
    i = s.index("{", da)
    d, j, n = 0, i, len(s)
    while j < n:
        c = s[j]
        if c in ("'", '"', "`"):
            k = j + 1
            while k < n:
                if s[k] == chr(92):
                    k += 2
                    continue
                if s[k] == c:
                    break
                k += 1
            j = k + 1
            continue
        if c == "{":
            d += 1
        elif c == "}":
            d -= 1
            if d == 0:
                return s[i:j + 1]
        j += 1
    raise SystemExit("blocco non bilanciato a partire da %d" % da)


def voci(corpo: str) -> list[tuple[str, str]]:
    """Le coppie chiave/valore di PRIMO livello di un blocco { ... }."""
    dentro = corpo[1:-1]
    fuori, i, n = [], 0, len(dentro)
    while i < n:
        m = re.compile(r"\s*'?([A-Za-z_$][\w$]*)'?\s*:\s*").match(dentro, i)
        if not m:
            i += 1
            continue
        chiave, i = m.group(1), m.end()
        d, j, inizio = 0, i, i
        while j < n:
            c = dentro[j]
            if c in ("'", '"', "`"):
                k = j + 1
                while k < n:
                    if dentro[k] == chr(92):
                        k += 2
                        continue
                    if dentro[k] == c:
                        break
                    k += 1
                j = k + 1
                continue
            if c in "{[(":
                d += 1
            elif c in "}])":
                d -= 1
            elif c == "," and d == 0:
                break
            j += 1
        fuori.append((chiave, dentro[inizio:j].strip()))
        i = j + 1
    return fuori


# ── tipi ─────────────────────────────────────────────────────────────────────

def tipo(espr: str, tabelle: dict) -> dict:
    """Un'espressione di tipo -> una struttura serializzabile in JSON."""
    e = espr.strip()
    if e.startswith("{"):
        return {"k": "Object",
                "campi": {c: tipo(v, tabelle) for c, v in voci(blocco(e, 0))}}
    m = re.match(r"t\.(\w+)\s*\((.*)\)\s*$", e, re.S)
    if m:
        nome, dentro = m.group(1), m.group(2)
        if nome not in COMBINATORI:
            raise SystemExit("combinatore non previsto: t.%s" % nome)
        if nome == "Enum":
            return {"k": "Enum", "valori": re.findall(r"'([^']*)'", dentro)}
        return {"k": nome, "di": tipo(dentro, tabelle)}
    m = re.match(r"t\.(\w+)\s*$", e)
    if m:
        if m.group(1) not in COMBINATORI:
            raise SystemExit("combinatore non previsto: t.%s" % m.group(1))
        return {"k": m.group(1)}
    m = re.match(r"(\w+)\.(\w+)\s*$", e)
    if m and m.group(1) in tabelle and m.group(2) in tabelle[m.group(1)]:
        return dict(tabelle[m.group(1)][m.group(2)], rif="%s.%s" % m.groups())
    raise SystemExit("espressione di tipo non interpretabile: %r" % e[:90])


# ── analisi ──────────────────────────────────────────────────────────────────

def analizza(testo: str) -> dict:
    s = senza_commenti(testo)
    tabelle: dict = {}
    for m in re.finditer(r"^const (\w+Types) = \{\};", s, re.M):
        tabelle[m.group(1)] = {}
    for nome in list(tabelle):
        for m in re.finditer(r"^%s\.(\w+) = " % re.escape(nome), s, re.M):
            tabelle[nome][m.group(1)] = tipo(blocco(s, m.end() - 1), tabelle)

    domini: dict = {}
    for m in re.finditer(r"^const ([A-Z]\w*) = \{", s, re.M):
        dom = m.group(1)
        corpo = blocco(s, m.end() - 1)
        if "methods:" not in corpo and "events:" not in corpo:
            continue
        d = {"comandi": {}, "eventi": {}}
        for chiave, valore in voci(corpo):
            if chiave not in ("methods", "events"):
                continue
            dove = "comandi" if chiave == "methods" else "eventi"
            for nome, corpo2 in voci(valore):
                if dove == "eventi":
                    d["eventi"][nome] = tipo(corpo2, tabelle)
                else:
                    parti = dict(voci(corpo2))
                    d["comandi"][nome] = {
                        "params": tipo(parti["params"], tabelle) if "params" in parti else None,
                        "returns": tipo(parti["returns"], tabelle) if "returns" in parti else None,
                    }
        domini[dom] = d
    return domini


# ── emissione ────────────────────────────────────────────────────────────────

INTESTAZIONE = '''"""GENERATO da scripts/gen_juggler_protocol.py. NON si modifica a mano.

Fonte: %s
Comandi: %d   Eventi: %d

Il browser applica questo schema a MONDO CHIUSO: un campo non dichiarato viene
RIFIUTATO a runtime, non ignorato. Serve quindi a verificare cio' che MANDIAMO
prima che parta, non a documentare.

⛔ Non sostituisce `protocol_drift_check.py` nel repo del sorgente: quel gate
chiede cosa manda un client VERO, ed e' una domanda che questo file non puo'
porre, perche' e' generato dalla stessa fonte che dovrebbe controllare.
"""
from __future__ import annotations

'''


def fonte_stabile(fonte: str) -> str:
    """La riga della fonte nel file generato non deve contenere un percorso
    assoluto: cambierebbe da una macchina all'altra e ogni rigenerazione
    sembrerebbe una modifica. E le barre rovesce di Windows dentro una docstring
    sono ESCAPE: `C:\\Users` alza `truncated \\UXXXXXXXX escape` e il file
    generato non si importa. Succede il 2026-08-27, e il modo di accorgersene
    e' stato che il file non si importava, non il generatore che falliva."""
    f = fonte.replace(chr(92), "/")
    return f.split("/")[-1] if "!" not in f else "omni.ja!" + f.split("!", 1)[1]


def emetti(domini: dict, fonte: str) -> str:
    fonte = fonte_stabile(fonte)
    n_cmd = sum(len(d["comandi"]) for d in domini.values())
    n_ev = sum(len(d["eventi"]) for d in domini.values())
    comandi, eventi = {}, {}
    for dom, d in sorted(domini.items()):
        for nome, spec in sorted(d["comandi"].items()):
            comandi["%s.%s" % (dom, nome)] = spec
        for nome, spec in sorted(d["eventi"].items()):
            eventi["%s.%s" % (dom, nome)] = spec
    # ⛔ pprint e non json.dumps: json emette `null`/`true`/`false`, che in
    # Python non esistono, e il file generato non si IMPORTA. Il generatore pero'
    # esce 0 lo stesso, quindi il guasto si vede solo importando - ed e' il
    # motivo per cui il test di questo generatore importa il file invece di
    # guardarne i byte.
    corpo = INTESTAZIONE % (fonte, n_cmd, n_ev)
    corpo += "DOMINI = %s\n\n" % pprint.pformat(sorted(domini), width=78)
    corpo += "COMANDI = %s\n\n" % pprint.pformat(comandi, width=88, sort_dicts=True)
    corpo += "EVENTI = %s\n" % pprint.pformat(eventi, width=88, sort_dicts=True)
    return corpo


def _selftest(testo: str) -> int:
    """Mutazioni note-cattive sul Protocol.js, senza browser e senza rete.

    La domanda: se il Protocol.js SPEDITO cambia, `--check` se ne accorge?
    Si muta il testo in memoria, si rigenera, e si confronta col corpo prodotto
    dal testo integro. Una mutazione che non muove il corpo e' un buco.
    """
    base = emetti(analizza(testo), "base")

    def corpo(t):
        i = t.find("DOMINI = ")
        return t[i:] if i >= 0 else t

    MUTAZIONI = [
        ("un comando TOLTO",
         lambda s: s.replace("    'collectGarbage': {\n      params: {},\n    },\n", "", 1)),
        ("un comando AGGIUNTO",
         lambda s: s.replace("    'collectGarbage': {",
                             "    'inventato': {\n      params: {},\n    },\n    'collectGarbage': {", 1)),
        ("un campo tolto da un comando",
         lambda s: s.replace("        attachToDefaultContext: t.Boolean,\n", "", 1)),
        ("un tipo cambiato: String -> Number",
         lambda s: s.replace("        url: t.String,", "        url: t.Number,", 1)),
        ("un Optional diventa obbligatorio",
         lambda s: s.replace("        browserContextId: t.Optional(t.String),",
                             "        browserContextId: t.String,", 1)),
        ("un valore tolto da un Enum",
         lambda s: s.replace("t.Enum(['reduce', 'no-preference'])",
                             "t.Enum(['no-preference'])", 1)),
        ("un evento RINOMINATO",
         lambda s: s.replace("    'ready': {", "    'prontoRinominato': {", 1)),
        ("un evento TOLTO",
         lambda s: s.replace("    'crashed': {" + chr(10) + "    }," + chr(10), "", 1)),
    ]
    print("mutazioni note-cattive sul Protocol.js:")
    sopravvissute = 0
    for descrizione, muta in MUTAZIONI:
        mutato = muta(testo)
        if mutato == testo:
            print("  MUTAZIONE INERTE  %-42s (non ha toccato il testo)" % descrizione)
            sopravvissute += 1
            continue
        try:
            diverso = corpo(emetti(analizza(mutato), "base")) != corpo(base)
        except SystemExit as e:
            diverso, descrizione = True, descrizione + " -> il generatore RIFIUTA: %s" % e
        if diverso:
            print("  uccisa            %s" % descrizione[:70])
        else:
            print("  SOPRAVVISSUTA     %s" % descrizione)
            sopravvissute += 1

    print()
    print("e i casi che devono NON scattare:")
    falsi = 0
    if corpo(emetti(analizza(testo), "altra fonte")) == corpo(base):
        print("  PASSA             lo stesso testo, fonte diversa nell'intestazione")
    else:
        print("  RIFIUTATO A TORTO lo stesso testo con un'altra fonte")
        falsi += 1
    # Uno spazio in piu' dentro un blocco vuoto e' una riformattazione, non una
    # deriva: se il gate scattasse qui sarebbe rosso a ogni ritocco del sorgente,
    # e un gate sempre rosso insegna a essere aggirato.
    riformattato = testo.replace("      params: {},", "      params: { },", 1)
    if riformattato == testo:
        print("  RIFIUTATO A TORTO nessun blocco vuoto da riformattare: caso non provato")
        falsi += 1
    elif corpo(emetti(analizza(riformattato), "base")) == corpo(base):
        print("  PASSA             uno spazio in piu' non e' una deriva")
    else:
        print("  RIFIUTATO A TORTO uno spazio in piu'")
        falsi += 1
    # E un COMMENTO nuovo non e' una deriva: il parser li toglie.
    commentato = testo.replace("const Heap = {", "// una nota\nconst Heap = {", 1)
    if commentato != testo and corpo(emetti(analizza(commentato), "base")) == corpo(base):
        print("  PASSA             un commento nuovo non e' una deriva")
    else:
        print("  RIFIUTATO A TORTO un commento nuovo")
        falsi += 1

    print()
    print("sopravvissute: %d su %d, rifiuti a torto: %d"
          % (sopravvissute, len(MUTAZIONI), falsi))
    return 1 if (sopravvissute or falsi) else 0


def main() -> int:
    qui = pathlib.Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--binario", help="cartella del firefox SPEDITO")
    ap.add_argument("--proto", help="un Protocol.js gia' estratto (per un jar che non si apre)")
    ap.add_argument("--out", default=str(qui / "src" / "invisible_playwright" / "_juggler" / "protocol.py"))
    ap.add_argument("--check", action="store_true",
                    help="rigenera e confronta, senza scrivere")
    ap.add_argument("--selftest", action="store_true",
                    help="mutazioni note-cattive sul Protocol.js, senza browser")
    a = ap.parse_args()

    if a.proto:
        fonte, testo = a.proto, pathlib.Path(a.proto).read_bytes().decode("utf-8", "replace")
    elif a.binario:
        fonte, testo = sorgente_protocollo(a.binario)
    else:
        ap.error("serve --binario (il firefox spedito) oppure --proto")

    if a.selftest:
        return _selftest(testo)

    domini = analizza(testo)
    n_cmd = sum(len(d["comandi"]) for d in domini.values())
    n_ev = sum(len(d["eventi"]) for d in domini.values())
    nuovo = emetti(domini, fonte)

    print("fonte: %s" % fonte)
    for dom in sorted(domini):
        print("  %-10s %3d comandi %3d eventi"
              % (dom, len(domini[dom]["comandi"]), len(domini[dom]["eventi"])))
    print("  %-10s %3d comandi %3d eventi" % ("TOTALE", n_cmd, n_ev))

    out = pathlib.Path(a.out)
    if a.check:
        if not out.is_file():
            print("MANCA: %s" % out)
            return 1
        vecchio = out.read_bytes().decode("utf-8")
        # si confronta il CORPO, non l'intestazione: la riga della fonte porta
        # un percorso che cambia da una macchina all'altra.
        def corpo(t):
            i = t.find("DOMINI = ")
            return t[i:] if i >= 0 else t
        if corpo(vecchio) == corpo(nuovo):
            print("PROTOCOLLO ALLINEATO")
            return 0
        print("DERIVA: il file generato non corrisponde al Protocol.js spedito")
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(nuovo.encode("utf-8"))
    print("scritto %s (%d byte)" % (out, len(nuovo)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""La copia della mappa dei generici dentro il gate non puo' divergere dal core.

`scripts/ci_font_gate.py` porta una copia letterale di
`zoom.stealth.fonts.generics`, ed e' l'unica copia di quel dato nel progetto.
Esiste per una ragione stretta: il job di gate della CI installa soltanto
Playwright, quindi `invisible_core` non e' importabile li' e non puo' esserlo
senza cambiare il workflow del repo sorgente, cioe' senza ricostruire i cinque
archivi.

La regola 16 vieta le seconde fonti. Una copia che nessuno puo' vedere andare
alla deriva sarebbe esattamente quello. Questo test la lega: se il core cambia
la dichiarazione e il gate resta indietro, la suite diventa rossa e il messaggio
dice quale delle due si e' mossa.

Perche' serve DAVVERO, e non e' una formalita': senza quella dichiarazione un
motore lanciato grezzo non mappa i generici, perche' da quando la mappa e'
dichiarata invece che compilata il motore non se la inventa (engine rule 7).
Misurato 2026-08-11 sullo stesso binario, lancio grezzo su Linux: serif,
sans-serif, monospace, cursive e fantasy collassano TUTTI su Arial. Con la
dichiarazione consegnata mappano su Times New Roman, Arial, Consolas e Comic
Sans, con gli stessi identici numeri di Windows.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_GATE = Path(__file__).resolve().parents[1] / "scripts" / "ci_font_gate.py"


def _generics_decl_dal_gate() -> str:
    """Il letterale dentro il gate, letto senza importare Playwright.

    Il file importa playwright dentro `main()`, quindi si compila e si esegue
    solo la parte che precede la definizione: le costanti ci sono, il driver no.
    """
    src = _GATE.read_text(encoding="utf-8")
    testa = src.split("def main")[0]
    ns: dict = {}
    exec(compile(testa, str(_GATE), "exec"), ns)  # noqa: S102 - e' il nostro file
    return ns["GENERICS_DECL"]


@pytest.mark.unit
def test_ci_font_gate_generics_match_the_core():
    from invisible_core._fpforge import generate_profile
    from invisible_core.prefs import translate_profile_to_prefs

    prefs = translate_profile_to_prefs(generate_profile(970411))
    dal_core = prefs["zoom.stealth.fonts.generics"]
    dal_gate = _generics_decl_dal_gate()

    assert dal_gate == dal_core, (
        "la mappa dei generici dentro scripts/ci_font_gate.py non e' piu' "
        "quella che invisible_core dichiara.\n"
        "  core: %r\n  gate: %r\n"
        "Aggiorna GENERICS_DECL nel gate. Se non lo fai, il gate misura un "
        "browser con una persona diversa da quella che spediamo, e il suo "
        "verde non vuol dire piu' niente."
        % (dal_core[-70:], dal_gate[-70:]))


@pytest.mark.unit
def test_the_generics_declaration_does_not_depend_on_the_seed():
    """Se dipendesse dal seme, una copia fissa sarebbe sbagliata per costruzione.

    E' il presupposto che rende lecita la copia: va verificato, non assunto.
    """
    from invisible_core._fpforge import generate_profile
    from invisible_core.prefs import translate_profile_to_prefs

    valori = {
        translate_profile_to_prefs(generate_profile(s))["zoom.stealth.fonts.generics"]
        for s in (1, 42, 970411, 20260811, 999999)
    }
    assert len(valori) == 1, (
        "zoom.stealth.fonts.generics cambia con il seme (%d valori distinti su "
        "5 semi): la copia dentro il gate non puo' piu' essere un letterale "
        "fisso e va letta dal core." % len(valori))

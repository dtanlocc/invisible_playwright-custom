# Il client Python di Playwright, biforcato

Copia modificabile di `playwright` **1.61.0** (`_impl`, `sync_api`, `async_api`),
Apache-2.0. **67 file, 2,4 MB.** La meta' Node del fork sta in `../_driver/`, e
il documento che spiega la decisione e' [quello](../_driver/README.md): qui ci
sono solo le cose che riguardano il lato Python.

## Cosa e' stato cambiato rispetto all'originale

**Gli import, in 52 file su 67.** Il client usa **446 import assoluti**
(`from playwright...`) e **zero relativi**: copiarlo sotto un altro nome senza
riscriverli avrebbe prodotto un pacchetto che importa quello *installato*, cioe'
un fork che sembra funzionare e non e' un fork.

Le riscritture sono **ancorate a inizio riga**. Non e' pignoleria: la parola
`playwright` compare 423 volte in docstring, URL della documentazione ed esempi
(`browser = playwright.chromium.launch()`), e in due punti e' una **variabile
locale** (`_impl/_browser_type.py:286`, `_impl/_fetch.py:66`). Un replace globale
le avrebbe rovinate tutte.

Cinque forme, censite invece che indovinate:

| forma | quante |
|---|---|
| `from playwright.X import ...` | 353 |
| `from playwright.{sync,async}_api import ...` | 74 |
| `import playwright.X[.Y] [as Z]` | 10 |
| `import playwright` | 2 |
| `from playwright._repo_version import ...` | 1 |

⛔ La terza forma **era sfuggita al primo giro**, e il primo giro sembrava
riuscito. Dieci import sopravvissuti puntavano ancora al pacchetto installato.
Li ha trovati il controllo che rilegge l'albero riscritto cercando residui: e'
per quello che esiste, non per fare bella figura.

**Un effetto collaterale degli import puntati.** `import playwright._impl._X`
senza alias lasciava usabile il nome nudo `playwright`, e i due `__init__.py`
delle API se ne servono ventitre volte a testa (`playwright._impl._api_structures.Cookie`).
Dopo la riscrittura quel nome non era piu' legato da nessuno: il modulo sarebbe
esploso con `NameError` alla prima riga eseguita. Il generatore aggiunge il
legame nei file che si trovavano in quella condizione.

**`_impl/_driver.py` e' l'unico file in cui e' cambiato del COMPORTAMENTO**, e
la modifica e' dichiarata in testa al file come chiede Apache-2.0: punta al
`cli.js` in `../_driver/` e prende `node` da `invisible_playwright._node`.
L'originale calcolava entrambi da `inspect.getfile(playwright)`, che dopo la
vendorizzazione punterebbe a `_pw/driver/` - una cartella che non esiste.

## Cosa NON e' stato toccato

Tutto il resto, byte per byte. Il fork esiste per poter cambiare
`../_driver/package/lib/coreBundle.js`; il client Python e' venuto dietro solo
perche' senza di lui la dipendenza da `playwright` sarebbe rimasta.

## Come rifarlo

`playwright` resta fra le dipendenze di **sviluppo** apposta: serve come
sorgente per rigenerare questa cartella, e serve a poter confrontare i due
bracci sulla stessa macchina. Un fork che non si puo' confrontare con
l'originale non si puo' nemmeno difendere.

Il generatore vive nel workbench (`C:/tmp/vendor_client.py` al momento della
prima stesura) e va rimesso in un posto stabile prima di servirne un secondo
giro.

## Verificato

- **454 test** della suite del wrapper, verdi sullo stack interamente biforcato.
- Una sessione completa del prodotto confrontata coi valori misurati **prima**
  del fork: user agent, `navigator.languages`, geometria dello schermo, renderer
  WebGL e **screenshot identico byte per byte** (9656). Zero differenze.
- `tests/test_fork.py` impedisce il modo silenzioso in cui questo fork
  morirebbe: qualcuno che scrive `from playwright...` in un file nuovo. Quella
  riga **funziona** - il pacchetto resta installato - e semplicemente esegue
  codice che non e' il nostro.

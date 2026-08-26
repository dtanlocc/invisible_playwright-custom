# Il driver Playwright, biforcato

Questa cartella e' una **copia modificabile del driver Node di Playwright**, non
una dipendenza. Esiste perche' il comportamento che ci serve non si ottiene
configurando Playwright: si ottiene cambiandolo.

## Provenienza

- Preso da `playwright` **1.61.0**, `site-packages/playwright/driver/package/`.
- Licenza **Apache-2.0**. `LICENSE`, `NOTICE` e `ThirdPartyNotices.txt` sono
  conservati dentro `package/` e non si toccano: sono la condizione per poter
  ridistribuire questo codice.
- Le modifiche nostre vanno elencate qui sotto, come pretende la licenza.

⛔ Cio' che spediamo e' **MIT piu' Apache-2.0**, e il `pyproject.toml` lo
dichiara: `license = "MIT AND Apache-2.0"`. Non e' burocrazia. Questo stesso
repository aveva gia' incontrato la questione e aveva scelto di NON spedire,
escludendo `tests/playwright-upstream` dall'sdist con la ragione scritta li'
accanto; qui si sceglie di spedire, quindi va detto.

## Il fork e' completo: anche il client Python

Questa cartella e' meta' del lavoro. L'altra e' [`../_pw/`](../_pw/README.md),
la copia del client Python (67 file, 2,4 MB), e insieme fanno sparire la
dipendenza da `playwright`: non e' piu' in `[project].dependencies`, resta solo
fra quelle di sviluppo per poter rigenerare il fork e confrontare i due bracci.

## Cosa NON c'e', e perche'

`node` non e' qui, ed e' l'unica cosa che non spediamo. Pesa 92,3 MB su 105:
committarlo vorrebbe dire un binario da 92 MB nella storia di git per sempre,
contro un limite GitHub di 100 MB per file, moltiplicato per quattro
piattaforme. Lo scarica `invisible_playwright._node` al primo uso da nodejs.org,
con il checksum verificato, ed estrae il solo eseguibile invece di srotolare i
50 MB di headers, npm e documentazione che non eseguiamo mai.

⛔ La tentazione di riusare il `node.exe` di `playwright`, se per caso e'
installato, e' stata scartata: due utenti finirebbero per eseguire due Node
diversi a seconda di cosa hanno installato per altri motivi. Una versione
dichiarata, uguale per tutti.

Tolto dal clone perche' misurato non necessario - ogni riga verificata lanciando
un browser vero e rifacendo un flusso completo, non a occhio:

| tolto | peso | ragione |
|---|---|---|
| `lib/vite/` | 3,66 MB | trace viewer e report HTML: non registriamo trace |
| `types/` | 1,82 MB | definizioni TypeScript: a runtime Python non le legge nessuno |
| `lib/serverRegistry.js` | 0,25 MB | rimosso e riprovato: il browser si pilota uguale |
| `lib/tools/` | 0,18 MB | idem |
| `lib/server/` | 0,10 MB | idem |

Restano **6,69 MB in 38 file**, contro i 12,70 MB di partenza.

⛔ `lib/utilsBundle.js` (3,14 MB) **SERVE**: tolto, il driver muore con
`Connection closed while reading`. Non riprovarci.

⛔ `lib/xdg-open` e `bin/` sono rimasti dentro **apposta**. Su Windows si tolgono
senza che niente cambi, ma su Windows non vengono eseguiti nemmeno quando ci
sono: quel verde non prova niente. Si tolgono solo dopo una prova su Linux.

## Come si aggancia

`playwright._impl._driver.compute_driver_executable()` costruisce il percorso dal
file del pacchetto e non legge nessuna variabile d'ambiente per la directory.
`_vendor_driver.py` la sostituisce all'import di `invisible_playwright`,
tenendo il `node` che la funzione originale avrebbe scelto e puntando il `cli.js`
qui dentro.

Il client Python e il driver parlano un protocollo versionato: la versione di
`playwright` installata deve essere **esattamente** quella da cui questo fork e'
stato preso, e `_vendor_driver.py` rifiuta di partire se non lo e'.

## Verificato

Driver clonato e sfoltito contro driver installato, stesso binario Firefox,
stessa pagina servita in locale, undici campi confrontati: `status`, `title`,
`content`, click, `inner_text`, `evaluate` di un numero e di un oggetto,
`screenshot`, `userAgent`, versione del browser. **Identici, screenshot compreso
byte per byte** (6165 in entrambi i bracci).

## Modifiche nostre rispetto a 1.61.0

Nessuna al contenuto di `coreBundle.js`, per ora: il fork e' l'infrastruttura,
non ancora le rimozioni. Ogni voce qui sotto va scritta quando la modifica entra,
**con la misura che la giustifica** - una patch che non sposta nessuna misura non
e' una patch.

La prima della lista e' gia' misurata e aspetta solo di essere scritta: il
serializzatore in `packages/isomorphic/utilityScriptSerializers.ts`, che gira
nel mondo del sito e interroga i suoi costruttori (`obj instanceof RegExp`,
`Date`, `URL`, `Error`, undici TypedArray, `ArrayBuffer`). Sono **sedici letture
regalate alla pagina per ogni oggetto** restituito da una `evaluate`, lineari
nell'annidamento: un oggetto con due array annidati ne regala 48.
